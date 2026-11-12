"""OIDC login (authorization code + PKCE, Keycloak), server-side sessions, CSRF guard.

Routes (mounted under /api): GET /auth/login, GET /auth/callback, POST /auth/logout,
POST /auth/dev-login (404 unless PORTAL_ENV=development and PORTAL_DEV_AUTH=1).

CSRF (no tokens to store): every unsafe method (POST/PUT/PATCH/DELETE) must carry BOTH
  1. an Origin header (or, if absent, a Referer) whose origin equals PUBLIC_ORIGIN exactly, and
  2. the custom header `X-Requested-With: portal` (forces a CORS preflight for cross-site pages).
The session cookie is HttpOnly + SameSite=Lax (+ Secure over https). `csrf_protect` is attached to
the whole app in main.py, so routers get it automatically.

Roles come from the ID token (claim path OIDC_ROLES_CLAIM, default realm_access.roles), so the
Keycloak client needs a realm-roles mapper on the ID token. Unknown role names are dropped.
"""

import base64
import hashlib
import hmac
import json
import logging
import secrets
import threading
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode, urlsplit

import httpx
import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from portal.config import KNOWN_ROLES, Settings, get_settings
from portal.db import get_db
from portal.models import Employee, PortalSession

log = logging.getLogger("portal.auth")
router = APIRouter(prefix="/auth", tags=["auth"])

LOGIN_COOKIE = "portal_login"
LOGIN_TTL_SECONDS = 600
# The pending login (state/nonce/verifier) lives in the short-lived HttpOnly login cookie, so an
# unauthenticated /auth/login writes nothing to the database and cannot be used to fill it.
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "portal"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
ALLOWED_ALGS = {"RS256", "RS384", "RS512", "ES256", "ES384", "PS256"}


class AuthError(Exception):
    """Login failed; the message is for logs only, the client sees a generic 400."""


def now() -> datetime:
    return datetime.now(UTC)


def safe_eq(a: str, b: str) -> bool:
    """Constant-time compare that never raises on non-ASCII input (compare_digest on str does)."""
    return hmac.compare_digest(a.encode(), b.encode())


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def http_client() -> httpx.Client:
    """Tests replace this (monkeypatch) with a client using httpx.MockTransport."""
    return httpx.Client(timeout=10.0, follow_redirects=False)


# ---- discovery + JWKS (small in-process cache) -------------------------------------------------

_cache: dict = {}
_cache_lock = threading.Lock()


def reset_oidc_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _get_json(url: str) -> dict:
    with http_client() as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.json()


def discovery(settings: Settings) -> dict:
    issuer = settings.oidc_issuer.rstrip("/")
    with _cache_lock:
        doc = _cache.get(("disc", issuer))
    if doc is None:
        doc = _get_json(issuer + "/.well-known/openid-configuration")
        if doc.get("issuer", "").rstrip("/") != issuer:
            raise AuthError("discovery issuer mismatch")
        with _cache_lock:
            _cache[("disc", issuer)] = doc
    return doc


def signing_key(settings: Settings, kid: str | None):
    """Key for kid; refetches JWKS once when the kid is unknown (key rotation)."""
    jwks_uri = discovery(settings)["jwks_uri"]
    for refresh in (False, True):
        with _cache_lock:
            jwks = None if refresh else _cache.get(("jwks", jwks_uri))
        if jwks is None:
            jwks = _get_json(jwks_uri)
            with _cache_lock:
                _cache[("jwks", jwks_uri)] = jwks
        for jwk in jwks.get("keys", []):
            if jwk.get("kid") == kid and jwk.get("use", "sig") == "sig":
                return jwt.PyJWK(jwk).key
    raise AuthError("unknown signing key")


def validate_id_token(settings: Settings, id_token: str, nonce: str) -> dict:
    try:
        header = jwt.get_unverified_header(id_token)
        if header.get("alg") not in ALLOWED_ALGS:
            raise AuthError("disallowed alg")
        claims = jwt.decode(
            id_token,
            key=signing_key(settings, header.get("kid")),
            algorithms=[header["alg"]],
            audience=settings.oidc_client_id,
            issuer=settings.oidc_issuer.rstrip("/"),
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            leeway=30,
        )
    except jwt.PyJWTError as exc:
        raise AuthError(f"id token invalid: {exc}") from exc
    if not safe_eq(str(claims.get("nonce", "")), nonce):
        raise AuthError("nonce mismatch")
    return claims


def roles_from_claims(settings: Settings, claims: dict) -> list[str]:
    value = claims
    for part in settings.oidc_roles_claim.split("."):
        value = value.get(part) if isinstance(value, dict) else None
    roles = value if isinstance(value, list) else []
    return sorted({r for r in roles if r in KNOWN_ROLES})


# ---- employees + sessions ----------------------------------------------------------------------


def upsert_employee(
    db: Session, subject: str, name: str, email: str, roles: list[str], email_verified: bool = False
) -> Employee:
    """Keyed by immutable OIDC subject, never by email. Disabled accounts cannot log in.

    The IdP token provisions a NEW employee only. After that, display name, email and roles are
    owned by the admin API: a login never rewrites them (an IdP-editable email would otherwise
    become the Gitea/Guacamole/event identity, and admin role changes would silently revert).
    An email is stored only if the IdP says it is verified and nobody else already has it;
    otherwise it is left empty for an admin to set.
    """
    emp = db.scalars(select(Employee).where(Employee.oidc_subject == subject)).first()
    if emp is None:
        if not roles:
            raise AuthError("no recognised role in token")
        taken = email and db.scalar(
            select(Employee.id).where(func.lower(Employee.email) == email.lower())
        )
        if not email_verified or taken:
            email = ""
        emp = Employee(oidc_subject=subject, display_name=name, email=email, roles=roles)
        db.add(emp)
    elif emp.status != "active":
        raise AuthError(f"employee is {emp.status}")
    db.flush()
    return emp


def create_session(db: Session, employee: Employee, settings: Settings) -> str:
    token = secrets.token_urlsafe(32)
    db.add(
        PortalSession(
            token_hash=hash_token(token),
            employee_id=employee.id,
            expires_at=now() + timedelta(seconds=settings.session_ttl_seconds),
        )
    )
    db.flush()
    return token


def set_cookie(response: Response, name: str, token: str, settings: Settings, max_age: int):
    response.set_cookie(
        name,
        token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=settings.secure_cookies,
        path="/",
    )


def revoke_employee_sessions(db: Session, employee_id) -> int:
    """For offboarding: kill every live portal session for the employee. Does not commit."""
    result = db.execute(
        update(PortalSession)
        .where(PortalSession.employee_id == employee_id, PortalSession.revoked_at.is_(None))
        .values(revoked_at=now())
    )
    return result.rowcount


def purge_expired_sessions(db: Session) -> int:
    """Delete expired sessions (pending logins and real ones). Does not commit."""
    return db.execute(delete(PortalSession).where(PortalSession.expires_at < now())).rowcount


def load_session(db: Session, token: str | None, settings: Settings) -> PortalSession | None:
    """Valid, unexpired, unrevoked, not idle, owned by an active employee; else None."""
    if not token:
        return None
    sess = db.scalars(
        select(PortalSession).where(PortalSession.token_hash == hash_token(token))
    ).first()
    t = now()
    if (
        sess is None
        or sess.employee_id is None
        or sess.revoked_at is not None
        or sess.expires_at <= t
        or sess.last_seen_at + timedelta(seconds=settings.session_idle_seconds) <= t
    ):
        return None
    if t - sess.last_seen_at > timedelta(seconds=60):  # avoid a write per request
        sess.last_seen_at = t
        db.commit()
    return sess


# ---- CSRF --------------------------------------------------------------------------------------


def csrf_protect(request: Request, settings: Settings = Depends(get_settings)) -> None:
    if request.method not in UNSAFE:
        return
    # CSRF abuses ambient browser credentials. A machine caller sending an explicit Bearer token
    # and no session cookie has none, so the browser-only headers do not apply to it.
    if request.headers.get("authorization", "").lower().startswith("bearer ") and not (
        request.cookies.get(settings.session_cookie_name)
    ):
        return
    if request.headers.get(CSRF_HEADER) != CSRF_VALUE:
        raise HTTPException(403, "missing X-Requested-With header")
    source = request.headers.get("origin")
    if source is None:
        ref = request.headers.get("referer")
        if ref:
            parts = urlsplit(ref)
            source = f"{parts.scheme}://{parts.netloc}"
    if source != settings.public_origin:
        raise HTTPException(403, "origin not allowed")


# ---- routes ------------------------------------------------------------------------------------


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


@router.get("/login")
def login(settings: Settings = Depends(get_settings)):
    if not settings.oidc_issuer:
        raise HTTPException(503, "OIDC is not configured")
    try:
        meta = discovery(settings)
    except (httpx.HTTPError, AuthError, ValueError) as exc:
        log.error("OIDC discovery failed: %s", exc)
        raise HTTPException(502, "identity provider unavailable") from exc
    state, nonce, verifier = (secrets.token_urlsafe(32) for _ in range(3))
    exp = now().timestamp() + LOGIN_TTL_SECONDS
    attempt = {"state": state, "nonce": nonce, "verifier": verifier, "exp": exp}
    token = _b64url(json.dumps(attempt).encode())
    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.oidc_client_id,
            "redirect_uri": settings.redirect_uri,
            "scope": "openid profile email",
            "state": state,
            "nonce": nonce,
            "code_challenge": _b64url(hashlib.sha256(verifier.encode()).digest()),
            "code_challenge_method": "S256",
        }
    )
    resp = RedirectResponse(f"{meta['authorization_endpoint']}?{query}", status_code=302)
    set_cookie(resp, LOGIN_COOKIE, token, settings, LOGIN_TTL_SECONDS)
    return resp


def _read_attempt(raw: str | None) -> dict | None:
    try:
        attempt = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        if not all(isinstance(attempt.get(k), str) for k in ("state", "nonce", "verifier")):
            return None
        return attempt if attempt["exp"] > now().timestamp() else None
    except (TypeError, ValueError, KeyError, AttributeError):  # no cookie, junk, wrong shape
        return None


@router.get("/callback")
def callback(
    request: Request,
    code: str = "",
    state: str = "",
    error: str = "",
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    attempt = _read_attempt(request.cookies.get(LOGIN_COOKIE))
    if attempt is None:
        raise HTTPException(400, "login attempt expired or unknown")
    try:
        if error or not code:
            raise AuthError(f"idp error: {error or 'no code'}")
        if not safe_eq(state, attempt["state"]):
            raise AuthError("state mismatch")
        meta = discovery(settings)
        form = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.redirect_uri,
            "client_id": settings.oidc_client_id,
            "code_verifier": attempt["verifier"],
        }
        if settings.oidc_client_secret:
            form["client_secret"] = settings.oidc_client_secret
        with http_client() as client:
            resp = client.post(meta["token_endpoint"], data=form)
        if resp.status_code != 200 or "id_token" not in resp.json():
            raise AuthError(f"token endpoint returned {resp.status_code}")
        claims = validate_id_token(settings, resp.json()["id_token"], attempt["nonce"])
        email = claims.get("email") or ""
        name = claims.get("name") or claims.get("preferred_username") or email or claims["sub"]
        employee = upsert_employee(
            db,
            claims["sub"],
            name,
            email,
            roles_from_claims(settings, claims),
            email_verified=claims.get("email_verified") is True,
        )
        token = create_session(db, employee, settings)
        db.commit()
    except (AuthError, httpx.HTTPError, ValueError, KeyError) as exc:
        db.rollback()
        log.warning("login rejected: %s", exc)
        failed = JSONResponse({"detail": "login failed"}, status_code=400)
        failed.delete_cookie(LOGIN_COOKIE, path="/")  # single use, whatever happened
        return failed
    out = RedirectResponse("/", status_code=303)
    out.delete_cookie(LOGIN_COOKIE, path="/")
    set_cookie(out, settings.session_cookie_name, token, settings, settings.session_ttl_seconds)
    return out


@router.post("/logout")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        db.execute(
            update(PortalSession)
            .where(
                PortalSession.token_hash == hash_token(token), PortalSession.revoked_at.is_(None)
            )
            .values(revoked_at=now())
        )
        db.commit()
    response.delete_cookie(settings.session_cookie_name, path="/")
    return {"ok": True}


class DevLogin(BaseModel):
    subject: str
    display_name: str | None = None
    email: str | None = None
    roles: list[str] = ["employee"]


@router.post("/dev-login")
def dev_login(
    body: DevLogin,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not settings.dev_auth_enabled:
        raise HTTPException(404)
    roles = sorted({r for r in body.roles if r in KNOWN_ROLES})
    try:
        emp = upsert_employee(
            db,
            body.subject,
            body.display_name or body.subject,
            body.email or f"{body.subject}@example.invalid",
            roles,
            email_verified=True,
        )
    except AuthError as exc:
        raise HTTPException(403, str(exc)) from exc
    token = create_session(db, emp, settings)
    db.commit()
    set_cookie(
        response, settings.session_cookie_name, token, settings, settings.session_ttl_seconds
    )
    return {"id": str(emp.id), "roles": emp.roles}
