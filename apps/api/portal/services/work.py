"""Shared logic for the employee/manager read-write API: policy resolution, posture, overview."""

import base64
import hashlib
import json
import os
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from portal.models import (
    Asset,
    Employee,
    PolicyAssignment,
    PolicyVersion,
    PostureObservation,
    TaskSnapshot,
    Workspace,
    WorkUpdate,
)

COLLECTION_POLICY = "collection-policy"
HEARTBEAT_CHECK = (
    "agent_heartbeat_at"  # ISO timestamp inside posture checks; required for compliant
)
MAX_SKEW = timedelta(minutes=5)  # how far ahead of our clock an observation may claim to be

# PLAN.md section 9. What the employee is told is collected. Never includes window titles,
# full URLs, clipboard text, screenshots, keystrokes, passwords, personal browsing or camera/audio.
COLLECTION_CATEGORIES = [
    {
        "signal": "Tasks, review state, blockers, deliverable links",
        "default": "on",
        "visible_to": "you and your direct manager",
    },
    {
        "signal": "Daily work update you write",
        "default": "on",
        "visible_to": "you and your direct manager; corrections keep history",
    },
    {
        "signal": "Project time",
        "default": "optional",
        "visible_to": "you and your direct manager; edit history preserved",
    },
    {
        "signal": "Workspace start/end and authentication",
        "default": "on",
        "visible_to": "security and operations; not proof of continuous effort",
    },
    {
        "signal": "Device patch, encryption and agent health",
        "default": "company_devices_only",
        "visible_to": "IT and security; shown as unknown when stale; personal devices not checked",
    },
    {
        "signal": "Export and privileged actions",
        "default": "on",
        "visible_to": "security and approval roles",
    },
    {
        "signal": "Application categories and idle periods",
        "default": "off",
        "visible_to": "not collected",
    },
    {
        "signal": "Window titles, full URLs, clipboard text",
        "default": "off",
        "visible_to": "not collected",
    },
    {
        "signal": "Screenshots and full session recordings",
        "default": "off",
        "visible_to": "not collected",
    },
    {
        "signal": "Keystrokes, passwords, personal browsing, camera, audio",
        "default": "excluded",
        "visible_to": "never collected",
    },
]


def utcnow() -> datetime:
    return datetime.now(UTC)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def posture_max_age() -> timedelta:
    return timedelta(seconds=_env_int("POSTURE_MAX_AGE_SECONDS", 900))


def heartbeat_max_age() -> timedelta:
    return timedelta(seconds=_env_int("POSTURE_HEARTBEAT_MAX_SECONDS", 300))


def service_token() -> str | None:
    """Shared secret for machine posture ingest. Placeholders are never accepted in production."""
    token = os.environ.get("PORTAL_SERVICE_TOKEN", "")
    if not token or (os.environ.get("PORTAL_ENV") == "production" and "change_me" in token.lower()):
        return None
    return token


def guacamole_launch_url(connection_ref: str | None) -> str | None:
    """Link into Guacamole's own login/SSO. No credentials are ever put in the URL."""
    base = os.environ.get("GUACAMOLE_URL", "").rstrip("/")
    if not base or not connection_ref:
        return None
    datasource = os.environ.get("GUACAMOLE_DATASOURCE", "postgresql")
    ident = base64.b64encode(f"{connection_ref}\0c\0{datasource}".encode()).decode().rstrip("=")
    return f"{base}/#/client/{ident}"


def content_hash(content: dict) -> str:
    blob = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()


def local_today(emp: Employee, now: datetime | None = None) -> date:
    try:
        tz = ZoneInfo(emp.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        tz = UTC
    return (now or utcnow()).astimezone(tz).date()


def valid_timezone(name: str) -> bool:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


# ---- policy ------------------------------------------------------------------------------------


def active_policy(db: Session, emp: Employee, now: datetime | None = None):
    """(PolicyVersion, PolicyAssignment) that applies to emp now, or None.

    Employee-scoped assignments beat 'all'; within a scope the latest activation wins.
    Expired exceptions and future activations are ignored.
    """
    # Compare with the database clock by default: activates_at is stamped by the DB.
    now = now or func.now()
    rows = db.execute(
        select(PolicyVersion, PolicyAssignment)
        .join(PolicyAssignment, PolicyAssignment.policy_version_id == PolicyVersion.id)
        .where(
            PolicyVersion.name == COLLECTION_POLICY,
            PolicyAssignment.activates_at <= now,
            (PolicyAssignment.expires_at.is_(None)) | (PolicyAssignment.expires_at > now),
            (PolicyAssignment.scope_type == "all")
            | ((PolicyAssignment.scope_type == "employee") & (PolicyAssignment.scope_id == emp.id)),
        )
        .order_by(PolicyAssignment.activates_at.desc())
    ).all()
    rows.sort(key=lambda r: r[1].scope_type != "employee")  # stable: employee scope first
    return rows[0] if rows else None


# ---- posture -----------------------------------------------------------------------------------


def failing_checks(checks: dict) -> list[dict]:
    out = []
    for name, value in sorted(checks.items()):
        if name == HEARTBEAT_CHECK:
            continue
        if value is False or (isinstance(value, dict) and value.get("passed") is False):
            detail = value.get("detail") if isinstance(value, dict) else None
            out.append({"check": name, "detail": detail})
    return out


def parse_ts(value) -> datetime | None:
    try:
        ts = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=UTC)


def _beat_ok(beat, now: datetime, heartbeat_age: timedelta) -> bool:
    ts = parse_ts(beat)
    return ts is not None and -MAX_SKEW <= now - ts <= heartbeat_age


def compute_posture(
    asset: Asset,
    obs: PostureObservation | list[PostureObservation] | None,
    now: datetime | None = None,
    max_age: timedelta | None = None,
    heartbeat_age: timedelta | None = None,
) -> dict:
    """compliant | noncompliant | unknown | not_applicable. Stale evidence is unknown, never green.

    `obs` is one observation or the latest one per source. Fresh evidence is combined: any failing
    check makes it noncompliant (whichever source reported it), and a fresh collector heartbeat
    is required for compliant, so a source that went quiet or never sent one cannot be masked by
    another source reporting green.
    """
    now = now or utcnow()
    max_age = max_age or posture_max_age()
    heartbeat_age = heartbeat_age or heartbeat_max_age()
    result = {
        "asset_id": str(asset.id),
        "ownership": asset.ownership,
        "state": "unknown",
        "reason": None,
        "observed_at": None,
        "failing_checks": [],
    }
    if asset.ownership == "personal":
        # BYOD: no local posture is collected or shown.
        return {**result, "state": "not_applicable", "reason": "personal_device"}
    items = [] if obs is None else obs if isinstance(obs, list) else [obs]
    if not items:
        return {**result, "reason": "no_observation"}
    items.sort(key=lambda o: o.observed_at, reverse=True)
    result["observed_at"] = items[0].observed_at.isoformat()
    result["failing_checks"] = [f for o in items for f in failing_checks(o.checks)]

    def problem(o: PostureObservation) -> str | None:
        if o.observed_at - now > MAX_SKEW:  # a host clock in the future is not evidence
            return "future_observation"
        if now - o.observed_at > max_age:
            return "stale_observation"
        if o.expires_at <= now:
            return "expired_observation"
        return None

    fresh = [o for o in items if problem(o) is None]
    if not fresh:
        return {**result, "reason": problem(items[0])}
    if any(failing_checks(o.checks) or o.state == "noncompliant" for o in fresh):
        return {**result, "state": "noncompliant", "reason": "failing_checks"}
    beats = [o.checks.get(HEARTBEAT_CHECK) for o in fresh if HEARTBEAT_CHECK in o.checks]
    if not beats:
        return {**result, "reason": "no_heartbeat"}
    if not any(_beat_ok(b, now, heartbeat_age) for b in beats):
        return {**result, "reason": "stale_heartbeat"}
    if any(o.state == "unknown" for o in fresh):
        return {**result, "reason": "reported_unknown"}
    return {**result, "state": "compliant", "reason": None}


def posture_for(db: Session, asset: Asset) -> dict:
    return compute_posture(
        asset, None if asset.ownership == "personal" else latest_observations(db, asset.id)
    )


def workspace_posture(db: Session, ws) -> dict:
    """Posture of the device/VM behind a workspace: state, observed_at, failing checks.
    A workspace with no linked asset has no evidence, so it is unknown (never green)."""
    asset = db.get(Asset, ws.asset_id) if ws.asset_id else None
    if asset is None:
        return {
            "state": "unknown",
            "reason": "no_asset",
            "observed_at": None,
            "failing_checks": [],
        }
    full = posture_for(db, asset)
    return {k: full[k] for k in ("state", "reason", "observed_at", "failing_checks")}


def latest_observations(db: Session, asset_id) -> list[PostureObservation]:
    """Newest observation per source. Future-dated rows (bad host clock) are ignored so they
    cannot shadow real ones. ponytail: no cap on distinct sources per asset; there are a handful."""
    return list(
        db.scalars(
            select(PostureObservation)
            .where(
                PostureObservation.asset_id == asset_id,
                PostureObservation.observed_at <= utcnow() + MAX_SKEW,
            )
            .distinct(PostureObservation.source)
            .order_by(PostureObservation.source, PostureObservation.observed_at.desc())
        )
    )


# ---- overview ----------------------------------------------------------------------------------


def previous_weekday(day: date) -> date:
    day -= timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day


def task_view(t: TaskSnapshot) -> dict:
    return {
        "id": str(t.id),
        "title": t.title,
        "url": t.url,
        "state": t.state,
        "due_date": t.due_date.isoformat() if t.due_date else None,
        "blocker": t.blocker,
        "deliverables": t.deliverables,
        "review_requested_at": t.review_requested_at.isoformat() if t.review_requested_at else None,
    }


def overview_for(db: Session, people: list[Employee], now: datetime | None = None) -> list[dict]:
    """Per-person facts for a manager. Sorted by name only: no score, ranking or percentage."""
    now = now or utcnow()
    ids = [p.id for p in people]
    tasks = db.scalars(
        select(TaskSnapshot)
        .where(TaskSnapshot.assignee_id.in_(ids), TaskSnapshot.state != "done")
        .order_by(TaskSnapshot.due_date.asc().nulls_last(), TaskSnapshot.title)
    ).all()
    updates = db.scalars(
        select(WorkUpdate)
        .where(
            WorkUpdate.employee_id.in_(ids),
            WorkUpdate.update_date >= now.date() - timedelta(days=14),
        )
        .order_by(WorkUpdate.update_date.desc())
    ).all()
    workspaces = db.scalars(
        select(Workspace)
        .where(Workspace.owner_id.in_(ids), Workspace.lifecycle_state != "decommissioned")
        .order_by(Workspace.name)
    ).all()
    out = []
    for p in sorted(people, key=lambda e: e.display_name.lower()):
        today = local_today(p, now)
        mine = [t for t in tasks if t.assignee_id == p.id]
        own_updates = [u for u in updates if u.employee_id == p.id]
        expected = previous_weekday(today)
        latest = own_updates[0] if own_updates else None
        out.append(
            {
                "employee_id": str(p.id),
                "display_name": p.display_name,
                "assignments": [task_view(t) for t in mine],
                "awaiting_review": [task_view(t) for t in mine if t.state == "in_review"],
                "blockers": [task_view(t) for t in mine if t.state == "blocked" or t.blocker],
                "workspaces": [
                    {
                        "id": str(w.id),
                        "name": w.name,
                        "lifecycle_state": w.lifecycle_state,
                        "posture": workspace_posture(db, w),
                    }
                    for w in workspaces
                    if w.owner_id == p.id
                ],
                "overdue": [task_view(t) for t in mine if t.due_date and t.due_date < today],
                "latest_update": {
                    "date": latest.update_date.isoformat(),
                    "blocker": latest.blocker,
                }
                if latest
                else None,
                "missing_update_for": None
                if any(u.update_date == expected for u in own_updates)
                else expected.isoformat(),
            }
        )
    return out
