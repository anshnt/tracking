"""Keycloak admin adapter (RevocationAdapter): disable the user, log out all sessions, verify.

Env: KEYCLOAK_ENABLED, KEYCLOAK_URL, KEYCLOAK_REALM, KEYCLOAK_CLIENT_ID, KEYCLOAK_CLIENT_SECRET
(a service-account client with realm-management manage-users/view-users).
employee.oidc_subject is the Keycloak user id (the token `sub`).
Keycloak logout alone is not enough for offboarding (PLAN.md section 12); this is only the
identity layer, the gateway and OS layers have their own adapters.
"""

from urllib.parse import quote

import httpx

from portal.connectors.base import RevocationAdapter, StepResult
from portal.connectors.http import Cfg, ConnectorError, Upstream, register_secrets


class KeycloakAdapter(RevocationAdapter):
    name = "keycloak"

    def __init__(self, cfg: Cfg, transport: httpx.BaseTransport | None = None):
        self.cfg, self.transport = cfg, transport
        self.realm = cfg.get("realm", "master")
        self.base = cfg.get("url").rstrip("/")
        register_secrets(cfg.secrets())
        self.up = Upstream(self.base, transport=transport)

    def _headers(self) -> dict:
        resp = self.up.json(
            "POST",
            f"/realms/{self.realm}/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.cfg.get("client_id"),
                "client_secret": self.cfg.get("client_secret"),
            },
        )
        token = resp.get("access_token") if isinstance(resp, dict) else None
        if not token:
            raise ConnectorError("token reply had no access_token")
        register_secrets([token])
        return {"Authorization": f"Bearer {token}"}

    def _admin(self, method: str, path: str, headers: dict, **kw):
        return self.up.request(method, f"/admin/realms/{self.realm}{path}", headers=headers, **kw)

    def capabilities(self) -> dict:
        headers = self._headers()
        count = self._admin("GET", "/users/count", headers).json()
        return {"edition": "keycloak", "realm": self.realm, "users": count}

    def list_users(self, first: int = 0, max_results: int = 100) -> list[dict]:
        """Known users for the provisioning check: id, username, email, enabled only."""
        headers = self._headers()
        rows = self._admin(
            "GET", "/users", headers, params={"first": first, "max": max_results}
        ).json()
        keep = ("id", "username", "email", "enabled")
        return [{k: r.get(k) for k in keep} for r in rows]

    def _find(self, employee, headers: dict) -> dict | None:
        """Resolve the Keycloak user: by id (oidc_subject), then exact username, then exact email.

        Admin-created employees may carry a subject that is not a Keycloak id, so a 404 on the id
        alone proves nothing about whether the real account exists.
        """
        sub = employee.oidc_subject
        resp = self._admin("GET", f"/users/{quote(sub, safe='')}", headers, ok=(404,))
        if resp.status_code != 404:
            return resp.json()
        for key, val in (("username", sub), ("email", employee.email)):
            if not val:
                continue
            rows = self._admin("GET", "/users", headers, params={key: val, "exact": "true"}).json()
            if rows:
                return rows[0]
        return None

    def revoke(self, employee) -> StepResult:
        try:
            headers = self._headers()
            user = self._find(employee, headers)
            if user is None:
                # fail closed: an unresolved account may still be live
                return StepResult(
                    "manual_required",
                    "no Keycloak user matches the subject, username or email; "
                    "confirm and disable the account by operator",
                )
            uid = quote(user["id"], safe="")
            self._admin("PUT", f"/users/{uid}", headers, json={"enabled": False})
            self._admin("POST", f"/users/{uid}/logout", headers)
            return StepResult("succeeded", "user disabled and all sessions logged out")
        except ConnectorError as exc:
            return StepResult("failed", str(exc))

    def verify(self, employee) -> bool:
        try:
            headers = self._headers()
            user = self._find(employee, headers)
            if user is None or user.get("enabled") is not False:
                return False  # unresolved is not revoked
            uid = quote(user["id"], safe="")
            return self._admin("GET", f"/users/{uid}/sessions", headers).json() == []
        except ConnectorError:
            return False
