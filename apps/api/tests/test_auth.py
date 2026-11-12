import base64
import hashlib
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select

from portal import auth
from portal.config import Settings
from portal.models import Employee, PortalSession

ISSUER = "https://idp.test/realms/portal"
CLIENT_ID = "portal-web"


class FakeIdp:
    """Keycloak stand-in behind httpx.MockTransport: discovery, JWKS and token endpoints."""

    def __init__(self):
        self.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        self.challenge = None
        self.claims: dict = {}
        self.signing_key = self.key
        self.seen_verifier_ok = None

    def jwks(self):
        jwk = jwt.algorithms.RSAAlgorithm.to_jwk(self.key.public_key(), as_dict=True)
        return {"keys": [{**jwk, "kid": "k1", "use": "sig", "alg": "RS256"}]}

    def id_token(self, **over):
        claims = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "sub": "kc-user-1",
            "nonce": self.nonce,
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            "name": "Ada Lovelace",
            "email": "ada@example.invalid",
            "email_verified": True,
            "realm_access": {"roles": ["employee", "manager", "bogus"]},
        }
        claims.update(over)
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(claims, self.signing_key, algorithm="RS256", headers={"kid": "k1"})

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/.well-known/openid-configuration"):
            return httpx.Response(
                200,
                json={
                    "issuer": ISSUER,
                    "authorization_endpoint": ISSUER + "/protocol/openid-connect/auth",
                    "token_endpoint": ISSUER + "/protocol/openid-connect/token",
                    "jwks_uri": ISSUER + "/protocol/openid-connect/certs",
                },
            )
        if path.endswith("/certs"):
            return httpx.Response(200, json=self.jwks())
        if path.endswith("/token"):
            form = parse_qs(request.content.decode())
            verifier = form["code_verifier"][0]
            digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            self.seen_verifier_ok = digest.rstrip(b"=").decode() == self.challenge
            if not self.seen_verifier_ok or form["client_secret"] != ["s3cret-test"]:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"id_token": self.id_token(**self.overrides)})
        return httpx.Response(404)


@pytest.fixture
def idp(monkeypatch, override_settings):
    fake = FakeIdp()
    fake.overrides = {}
    monkeypatch.setattr(
        auth, "http_client", lambda: httpx.Client(transport=httpx.MockTransport(fake.handler))
    )
    override_settings(
        oidc_issuer=ISSUER,
        oidc_client_id=CLIENT_ID,
        oidc_client_secret="s3cret-test",
        public_origin="http://testserver",
    )
    return fake


def start_login(client: TestClient, idp: FakeIdp) -> str:
    resp = client.get("/api/auth/login")
    assert resp.status_code == 302
    query = parse_qs(urlsplit(resp.headers["location"]).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["client_id"] == [CLIENT_ID]
    idp.nonce = query["nonce"][0]
    idp.challenge = query["code_challenge"][0]
    return query["state"][0]


@pytest.fixture
def browser(app):
    return TestClient(app, follow_redirects=False)


def test_login_flow_creates_employee_and_session(browser, idp, db):
    state = start_login(browser, idp)
    resp = browser.get("/api/auth/callback", params={"code": "abc", "state": state})
    assert resp.status_code == 303 and resp.headers["location"] == "/"
    cookie = resp.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert idp.seen_verifier_ok

    me = browser.get("/api/v1/me")
    assert me.status_code == 200
    assert me.json()["roles"] == ["employee", "manager"]  # unknown role dropped
    emp = db.scalars(select(Employee)).one()
    assert emp.oidc_subject == "kc-user-1"
    # pre-login row consumed, one real session remains
    assert [s.employee_id for s in db.scalars(select(PortalSession)).all()] == [emp.id]


def login_as(browser, idp, **overrides):
    idp.overrides = overrides
    state = start_login(browser, idp)
    resp = browser.get("/api/auth/callback", params={"code": "c", "state": state})
    assert resp.status_code == 303, resp.text


def test_login_never_rewrites_email_name_or_roles_after_provisioning(browser, idp, db):
    login_as(browser, idp)
    emp = db.scalars(select(Employee)).one()
    emp.roles = ["employee", "it"]  # an admin changed this through the admin API
    db.commit()
    login_as(
        browser,
        idp,
        email="ceo@corp.example",  # IdP-editable claim must not become the stored identity
        name="Someone Else",
        realm_access={"roles": ["employee", "admin"]},
    )
    db.expire_all()
    emp = db.scalars(select(Employee)).one()
    assert emp.email == "ada@example.invalid"
    assert emp.display_name == "Ada Lovelace"
    assert emp.roles == ["employee", "it"]


def test_unverified_or_duplicate_email_is_not_stored(browser, idp, db, make_employee):
    login_as(browser, idp, email_verified=False)
    assert db.scalars(select(Employee)).one().email == ""
    make_employee(email="ceo@corp.example")
    login_as(browser, idp, sub="kc-user-2", email="CEO@corp.example")
    emp = db.scalars(select(Employee).where(Employee.oidc_subject == "kc-user-2")).one()
    assert emp.email == ""


def test_unauthenticated_login_writes_nothing_so_it_cannot_exhaust_anything(browser, idp, db):
    for _ in range(5):
        assert browser.get("/api/auth/login").status_code == 302
    assert db.scalars(select(PortalSession)).all() == []


def test_callback_with_non_ascii_state_is_a_400_not_a_500(browser, idp):
    start_login(browser, idp)
    resp = browser.get("/api/auth/callback", params={"code": "x", "state": "é"})
    assert resp.status_code == 400


def test_callback_with_junk_or_expired_login_cookie(browser, idp, monkeypatch):
    start_login(browser, idp)
    browser.cookies.set(auth.LOGIN_COOKIE, "not-base64-json!!")
    assert browser.get("/api/auth/callback", params={"code": "x", "state": "y"}).status_code == 400
    start_login(browser, idp)
    monkeypatch.setattr(auth, "LOGIN_TTL_SECONDS", -1)  # cookie minted already expired
    state = start_login(browser, idp)
    assert (
        browser.get("/api/auth/callback", params={"code": "x", "state": state}).status_code == 400
    )


def test_non_ascii_nonce_claim_is_an_auth_error_not_a_type_error():
    assert auth.safe_eq("café", "cafe") is False
    assert auth.safe_eq("abc", "abc") is True


def test_bearer_request_needs_no_browser_csrf_headers_but_cookie_requests_do(
    app, override_settings, make_employee, client_for
):
    override_settings(public_origin="https://portal.example.com")
    bare = TestClient(app)
    # no cookie + Bearer: the guard steps aside (the route then rejects the bad token itself)
    r = bare.post(
        "/api/v1/devices/00000000-0000-0000-0000-000000000001/posture-observations",
        json={"source": "s"},
        headers={"Authorization": "Bearer nope"},
    )
    assert r.status_code == 401
    # a session cookie plus Bearer must still pass the browser checks
    c = client_for(make_employee())
    c.headers.clear()
    r = c.post("/api/auth/logout", headers={"Authorization": "Bearer x"})
    assert r.status_code == 403


@pytest.mark.parametrize(
    "overrides",
    [
        {"nonce": "wrong-nonce"},
        {"aud": "someone-else"},
        {"iss": "https://evil.test/realms/portal"},
        {"exp": int(time.time()) - 3600},
        {"nonce": None},
        {"realm_access": {"roles": []}},
    ],
    ids=["nonce", "audience", "issuer", "expired", "no-nonce", "no-roles"],
)
def test_login_rejects_bad_id_tokens(browser, idp, db, overrides):
    idp.overrides = overrides
    state = start_login(browser, idp)
    resp = browser.get("/api/auth/callback", params={"code": "abc", "state": state})
    assert resp.status_code == 400
    assert browser.get("/api/v1/me").status_code == 401
    assert db.scalars(select(Employee)).all() == []


def test_login_rejects_token_signed_by_other_key(browser, idp):
    idp.signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    state = start_login(browser, idp)
    assert (
        browser.get("/api/auth/callback", params={"code": "x", "state": state}).status_code == 400
    )


def test_login_rejects_bad_state_and_replay(browser, idp):
    start_login(browser, idp)
    assert (
        browser.get("/api/auth/callback", params={"code": "x", "state": "nope"}).status_code == 400
    )
    # the attempt was consumed: even a right state now fails
    assert (
        browser.get("/api/auth/callback", params={"code": "x", "state": "nope"}).status_code == 400
    )


def test_callback_without_login_cookie(browser, idp):
    assert browser.get("/api/auth/callback", params={"code": "x", "state": "y"}).status_code == 400


def test_offboarded_employee_cannot_log_in(browser, idp, make_employee):
    make_employee(oidc_subject="kc-user-1", status="offboarded")
    state = start_login(browser, idp)
    assert (
        browser.get("/api/auth/callback", params={"code": "x", "state": state}).status_code == 400
    )


def test_logout_revokes_session(make_employee, client_for):
    client = client_for(make_employee())
    assert client.get("/api/v1/me").status_code == 200
    assert client.post("/api/auth/logout").status_code == 200
    client.cookies.clear()  # the server-side row is what matters; replay the old token below
    assert client.get("/api/v1/me").status_code == 401


def test_revoked_or_expired_session_and_disabled_employee(make_employee, client_for, db):
    emp = make_employee()
    client = client_for(emp)
    assert client.get("/api/v1/me").status_code == 200
    auth.revoke_employee_sessions(db, emp.id)
    db.commit()
    assert client.get("/api/v1/me").status_code == 401

    emp2 = make_employee()
    client2 = client_for(emp2)
    emp2.status = "offboarding"
    db.commit()
    assert client2.get("/api/v1/me").status_code == 401


def test_dev_login_enabled_only_in_development_with_flag(app, override_settings, db):
    body = {"subject": "dev-1", "roles": ["employee", "admin"]}
    headers = {"Origin": "http://testserver", "X-Requested-With": "portal"}

    override_settings()  # development, PORTAL_DEV_AUTH unset
    client = TestClient(app, headers=headers)
    assert client.post("/api/auth/dev-login", json=body).status_code == 404

    override_settings(portal_dev_auth=True)
    resp = client.post("/api/auth/dev-login", json=body)
    assert resp.status_code == 200 and resp.json()["roles"] == ["admin", "employee"]
    assert client.get("/api/v1/me").status_code == 200


def test_production_refuses_dev_auth_and_placeholders():
    good = dict(
        portal_env="production",
        database_url="postgresql+psycopg://u:longsecret@db/portal",
        oidc_issuer=ISSUER,
        oidc_client_id="portal",
        oidc_client_secret="real-secret",
        public_origin="https://portal.example.invalid",
    )
    assert Settings(**good).secure_cookies
    for bad in (
        {"portal_dev_auth": True},
        {"oidc_client_secret": "CHANGE_ME"},
        {"database_url": "postgresql+psycopg://tracking:tracking@127.0.0.1:5433/tracking"},
        {"public_origin": "http://portal.example.invalid"},
        {"oidc_issuer": ""},
    ):
        with pytest.raises(ValidationError):
            Settings(**{**good, **bad})
