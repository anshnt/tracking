"""Audit trail: record() rows (hashes only) + request id middleware.

Usage in a handler (same transaction as the change; the handler commits once):

    audit.record(db, actor, "export.approve", "export_request", req.id,
                 reason="...", before={"status": "reviewed"}, after={"status": "approved"})
    db.commit()
"""

import hashlib
import json
import re
import uuid
from contextvars import ContextVar
from typing import Any

from sqlalchemy.orm import Session

from portal.models import AuditEvent, Employee

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")


def digest(value: Any) -> str | None:
    """sha256 of canonical JSON. Stores a fingerprint, never the metadata itself."""
    if value is None:
        return None
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def record(
    db: Session,
    actor: Employee | None,
    action: str,
    target_type: str,
    target_id: Any,
    reason: str | None = None,
    before: Any = None,
    after: Any = None,
    request_id: str | None = None,
) -> AuditEvent:
    """actor=None means the system (worker/connector). Flushes, does not commit."""
    event = AuditEvent(
        actor_id=actor.id if actor else None,
        action=action,
        target_type=target_type,
        target_id=None if target_id is None else str(target_id),
        reason=reason,
        before_hash=digest(before),
        after_hash=digest(after),
        request_id=request_id or request_id_var.get(),
    )
    db.add(event)
    db.flush()
    return event


class RequestIdMiddleware:
    """Pure ASGI: honours a sane inbound X-Request-ID, else generates one; echoes it back."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        incoming = dict(scope["headers"]).get(b"x-request-id", b"").decode("latin-1")
        rid = incoming if _VALID_ID.match(incoming) else uuid.uuid4().hex
        token = request_id_var.set(rid)

        async def send_with_id(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).append((b"x-request-id", rid.encode()))
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            request_id_var.reset(token)
