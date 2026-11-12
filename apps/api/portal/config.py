"""Settings (env vars / .env). Production refuses dev auth and placeholder secrets."""

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# dev-only default; production refuses to start with it
DEV_DATABASE_URL = "postgresql+psycopg://tracking:tracking@127.0.0.1:5433/tracking"
KNOWN_ROLES = ("employee", "manager", "it", "security", "approver", "admin")


def _is_placeholder(value: str) -> bool:
    v = value.lower()
    return "change_me" in v or "changeme" in v


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    portal_env: Literal["development", "production"] = "development"
    portal_dev_auth: bool = False
    database_url: str = DEV_DATABASE_URL

    # Origin the browser uses; CSRF compares Origin/Referer against it exactly.
    public_origin: str = "http://localhost:8000"

    oidc_issuer: str = ""
    oidc_client_id: str = "portal"
    oidc_client_secret: str = ""  # empty = public client (PKCE only)
    oidc_redirect_uri: str = ""  # default: <public_origin>/api/auth/callback
    oidc_roles_claim: str = "realm_access.roles"  # dotted path inside the ID token

    session_cookie_name: str = "portal_session"
    session_ttl_seconds: int = 8 * 3600  # absolute lifetime
    session_idle_seconds: int = 3600  # idle timeout
    cookie_secure: bool | None = None  # None: secure iff public_origin is https

    @property
    def is_production(self) -> bool:
        return self.portal_env == "production"

    @property
    def dev_auth_enabled(self) -> bool:
        return self.portal_env == "development" and self.portal_dev_auth

    @property
    def redirect_uri(self) -> str:
        return self.oidc_redirect_uri or self.public_origin.rstrip("/") + "/api/auth/callback"

    @property
    def secure_cookies(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return self.public_origin.startswith("https://")

    @model_validator(mode="after")
    def _production_guard(self):
        self.public_origin = self.public_origin.rstrip("/")
        if not self.is_production:
            return self
        problems = []
        if self.portal_dev_auth:
            problems.append("PORTAL_DEV_AUTH must not be set in production")
        if self.database_url == DEV_DATABASE_URL or _is_placeholder(self.database_url):
            problems.append("DATABASE_URL is the dev default or a placeholder")
        if not self.oidc_issuer or _is_placeholder(self.oidc_issuer):
            problems.append("OIDC_ISSUER must be set")
        if _is_placeholder(self.oidc_client_id) or _is_placeholder(self.oidc_client_secret):
            problems.append("OIDC client id/secret are placeholders")
        if not self.public_origin.startswith("https://"):
            problems.append("PUBLIC_ORIGIN must be https")
        if self.cookie_secure is False:
            problems.append("COOKIE_SECURE=false is not allowed")
        if problems:
            raise ValueError("refusing to start in production: " + "; ".join(problems))
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
