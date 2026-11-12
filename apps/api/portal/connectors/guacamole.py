"""Guacamole adapter (RevocationAdapter): list a user's active connections and kill them.

Env: GUACAMOLE_ENABLED, GUACAMOLE_URL (including the /guacamole path), GUACAMOLE_USERNAME,
GUACAMOLE_PASSWORD (admin that may read and kill active connections), GUACAMOLE_USER_FIELD
(email | email_local | subject, default email: how a portal employee maps to a Guacamole user).

Uses the REST endpoints /api/session/data/{source}/activeConnections (GET, and PATCH with
JSON-patch "remove" ops). If the pinned version does not offer them, revoke returns
manual_required and verify stays False, so offboarding shows incomplete (PLAN.md section 12).
"""

from urllib.parse import quote

import httpx

from portal.connectors.base import RevocationAdapter, StepResult
from portal.connectors.http import (
    Cfg,
    ConnectorError,
    Upstream,
    login_for,
    register_secrets,
)

UNSUPPORTED = (404, 405, 501)


class Unsupported(ConnectorError):
    pass


class GuacamoleAdapter(RevocationAdapter):
    name = "guacamole"

    def __init__(self, cfg: Cfg, transport: httpx.BaseTransport | None = None):
        self.cfg = cfg
        self.user_field = cfg.get("user_field", "email")
        register_secrets(cfg.secrets())
        self.up = Upstream(cfg.get("url"), transport=transport)

    def _session(self) -> tuple[dict, str]:
        data = self.up.json(
            "POST",
            "/api/tokens",
            data={"username": self.cfg.get("username"), "password": self.cfg.get("password")},
        )
        token = data.get("authToken") if isinstance(data, dict) else None
        source = data.get("dataSource") if isinstance(data, dict) else None
        source = quote(str(source), safe="") if source else None
        if not token or not source:
            raise ConnectorError("token reply had no authToken/dataSource")
        register_secrets([token])
        # ponytail: Guacamole-Token header needs Guacamole >= 1.5; older ones want ?token=
        return {"Guacamole-Token": token}, source

    def _active(self, headers: dict, source: str) -> dict:
        resp = self.up.request(
            "GET", f"/api/session/data/{source}/activeConnections", headers=headers, ok=UNSUPPORTED
        )
        if resp.status_code in UNSUPPORTED:
            raise Unsupported("activeConnections is not available in this Guacamole version")
        data = resp.json()
        return data if isinstance(data, dict) else {}

    def _mine(self, active: dict, employee) -> list[str]:
        user = login_for(employee, self.user_field).lower()
        return [
            cid
            for cid, conn in active.items()
            if isinstance(conn, dict) and str(conn.get("username", "")).lower() == user
        ]

    def _exists(self, headers: dict, source: str, employee) -> bool:
        user = quote(login_for(employee, self.user_field), safe="")
        resp = self.up.request(
            "GET", f"/api/session/data/{source}/users/{user}", headers=headers, ok=(404,)
        )
        return resp.status_code != 404

    def capabilities(self) -> dict:
        headers, source = self._session()
        try:
            self._active(headers, source)
            return {"edition": "guacamole", "active_connections_api": True}
        except Unsupported:
            return {"edition": "guacamole", "active_connections_api": False}

    def revoke(self, employee) -> StepResult:
        try:
            headers, source = self._session()
            if not self._exists(headers, source, employee):
                return StepResult(
                    "manual_required",
                    "no Guacamole user matches the mapped login; confirm by operator",
                )
            mine = self._mine(self._active(headers, source), employee)
            if mine:
                self.up.request(
                    "PATCH",
                    f"/api/session/data/{source}/activeConnections",
                    headers=headers,
                    json=[{"op": "remove", "path": f"/{quote(cid, safe='')}"} for cid in mine],
                )
            return StepResult("succeeded", f"killed {len(mine)} active connection(s)")
        except Unsupported as exc:
            return StepResult("manual_required", f"{exc}; terminate sessions by operator")
        except ConnectorError as exc:
            return StepResult("failed", str(exc))

    def verify(self, employee) -> bool:
        try:
            headers, source = self._session()
            if not self._exists(headers, source, employee):
                return False  # unresolved is not revoked
            return not self._mine(self._active(headers, source), employee)
        except ConnectorError:
            return False
