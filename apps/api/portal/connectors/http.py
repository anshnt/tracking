"""Shared HTTP plumbing for connectors: config from env, error taxonomy, secret redaction.

Env config: <NAME>_ENABLED=1, <NAME>_URL, <NAME>_TOKEN, ... (see Cfg.get). Nothing is read at
import time, and every connector accepts an httpx transport so tests use httpx.MockTransport.
"""

import os
import re
from email.utils import parsedate_to_datetime

import httpx

MAX_RETRY_AFTER = 3600.0


class ConnectorError(Exception):
    """Upstream unreachable, 5xx or unexpected reply. Safe to retry with backoff."""


class AuthRejected(ConnectorError):
    """401/403: credentials revoked or too weak. Surfaced on the health page, not retried hard."""


class RateLimited(ConnectorError):
    def __init__(self, retry_after: float):
        super().__init__(f"rate limited, retry after {retry_after:.0f}s")
        self.retry_after = retry_after


class SchemaError(ConnectorError):
    """A record is missing a required field (unknown extra fields are ignored, never an error)."""


class Cfg:
    """Reads <NAME>_<KEY> from env (or a dict, for tests)."""

    def __init__(self, name: str, env: dict | None = None):
        self.name = name
        self.env = os.environ if env is None else env

    def get(self, key: str, default: str = "") -> str:
        return self.env.get(f"{self.name.upper()}_{key.upper()}", default)

    @property
    def enabled(self) -> bool:
        return self.get("enabled").strip().lower() in ("1", "true", "yes", "on")

    def secrets(self) -> list[str]:
        return [self.get(k) for k in ("token", "password", "client_secret") if self.get(k)]


_PATTERNS = [
    (re.compile(r"(?i)(bearer|basic)\s+[A-Za-z0-9._~+/=-]{6,}"), r"\1 [redacted]"),
    (
        re.compile(r"(?i)\b(token|password|passwd|secret|api[_-]?key|authtoken)=[^&\s\"']+"),
        r"\1=[redacted]",
    ),
    (
        re.compile(r"(?i)\"(token|password|secret|access_token|authToken)\"\s*:\s*\"[^\"]*\""),
        r'"\1":"[redacted]"',
    ),
]
_known_secrets: set[str] = set()


def register_secrets(values) -> None:
    _known_secrets.update(v for v in values if v and len(v) >= 4)


def redact(text: object) -> str:
    """Strip tokens and passwords from anything headed for a log, job error or API response."""
    out = str(text)
    for secret in _known_secrets:
        out = out.replace(secret, "[redacted]")
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    return out


def _retry_after(resp: httpx.Response) -> float:
    raw = resp.headers.get("retry-after", "")
    try:
        value = float(raw)
    except ValueError:
        try:
            from datetime import UTC, datetime

            value = (parsedate_to_datetime(raw) - datetime.now(UTC)).total_seconds()
        except (TypeError, ValueError):
            value = 60.0
    return min(max(value, 1.0), MAX_RETRY_AFTER)


class Upstream:
    """Thin httpx wrapper: maps status codes to the error taxonomy and redacts messages."""

    def __init__(
        self,
        base_url: str,
        headers: dict | None = None,
        auth=None,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 10.0,
    ):
        self.client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers or {},
            auth=auth,
            transport=transport,
            timeout=timeout,
            follow_redirects=False,
        )

    def request(self, method: str, path: str, ok: tuple = (), **kw) -> httpx.Response:
        try:
            resp = self.client.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise ConnectorError(redact(f"{method} {path}: {type(exc).__name__}: {exc}")) from None
        if resp.status_code in ok:
            return resp
        if resp.status_code == 429:
            raise RateLimited(_retry_after(resp))
        if resp.status_code in (401, 403):
            raise AuthRejected(f"{method} {path}: credentials rejected ({resp.status_code})")
        if resp.status_code >= 400:
            raise ConnectorError(f"{method} {path}: HTTP {resp.status_code}")
        return resp

    def json(self, method: str, path: str, **kw):
        resp = self.request(method, path, **kw)
        try:
            return resp.json()
        except ValueError:
            raise ConnectorError(f"{method} {path}: reply was not JSON") from None


def login_for(employee, field: str) -> str:
    """Map a portal employee to the upstream username. field: email | email_local | subject."""
    if field == "subject":
        login = employee.oidc_subject
    elif field == "email_local":
        login = employee.email.split("@")[0]
    else:
        login = employee.email
    if not login:  # unverified or duplicate email at provisioning leaves email ''
        raise ConnectorError("employee has no usable upstream username (empty email)")
    return login
