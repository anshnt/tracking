"""Device posture (PLAN.md section 9, P06). Observations are evidence; stale means unknown."""

import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from portal import audit
from portal.auth import safe_eq
from portal.authz import current_employee, has_role, require_roles
from portal.config import Settings, get_settings
from portal.db import get_db
from portal.models import Asset, Employee, MaintenanceException, PostureObservation
from portal.services import work

router = APIRouter(tags=["devices"])
MAX_CHECKS = 50
MAX_SKEW = work.MAX_SKEW


def _load_asset(db: Session, emp: Employee, asset_id: uuid.UUID) -> Asset:
    """Own device, or IT/security. Anything else looks like a missing device."""
    asset = db.get(Asset, asset_id)
    if asset is None or not (
        asset.assigned_employee_id == emp.id or has_role(emp, "it", "security")
    ):
        raise HTTPException(404, "not found")
    return asset


@router.get("/devices")
def list_devices(emp: Employee = Depends(current_employee), db: Session = Depends(get_db)):
    q = select(Asset).order_by(Asset.name)
    if not has_role(emp, "it", "security"):
        q = q.where(Asset.assigned_employee_id == emp.id)
    return {
        "devices": [
            {"id": str(a.id), "name": a.name, "ownership": a.ownership, "os": a.os}
            for a in db.scalars(q.limit(500))
        ]
    }


@router.get("/devices/{asset_id}/posture")
def get_posture(
    asset_id: uuid.UUID, emp: Employee = Depends(current_employee), db: Session = Depends(get_db)
):
    asset = _load_asset(db, emp, asset_id)
    return work.posture_for(db, asset)


class ObservationIn(BaseModel):
    source: str = Field(min_length=1, max_length=100)
    observed_at: Any = None  # ISO timestamp; defaults to receipt time
    checks: dict[str, Any] = Field(default_factory=dict)


def _normalize_checks(raw: dict[str, Any]) -> dict:
    if len(raw) > MAX_CHECKS:
        raise HTTPException(422, "too many checks")
    out: dict = {}
    for name, value in raw.items():
        if not name or len(name) > 64:
            raise HTTPException(422, "bad check name")
        if name == work.HEARTBEAT_CHECK:
            ts = work.parse_ts(value)
            if ts is None:
                raise HTTPException(422, "bad heartbeat timestamp")
            out[name] = ts.isoformat()
        elif isinstance(value, bool):
            out[name] = {"passed": value, "detail": None}
        elif isinstance(value, dict) and isinstance(value.get("passed"), bool):
            detail = value.get("detail")
            out[name] = {"passed": value["passed"], "detail": str(detail)[:200] if detail else None}
        else:
            raise HTTPException(422, f"check {name!r} must be a bool or an object with passed")
    return out


def ingest_actor(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Employee | None:
    """Service token (machine collector) -> None, or a logged-in employee with the it role."""
    header = request.headers.get("authorization", "")
    token = work.service_token()
    if header.lower().startswith("bearer "):
        if token and safe_eq(header[7:].strip(), token):
            return None
        raise HTTPException(401, "bad service token")
    emp = current_employee(request, db, settings)
    if not has_role(emp, "it"):
        raise HTTPException(403, "forbidden")
    return emp


@router.post("/devices/{asset_id}/posture-observations", status_code=201)
def ingest_observation(
    asset_id: uuid.UUID,
    body: ObservationIn,
    actor: Employee | None = Depends(ingest_actor),
    db: Session = Depends(get_db),
):
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(404, "not found")
    if asset.ownership == "personal":
        raise HTTPException(409, "personal devices are not observed")
    now = work.utcnow()
    observed_at = now
    if body.observed_at is not None:
        observed_at = work.parse_ts(body.observed_at)
        if observed_at is None:
            raise HTTPException(422, "bad observed_at")
        if observed_at - now > MAX_SKEW:
            raise HTTPException(422, "observed_at is in the future")
    checks = _normalize_checks(body.checks)
    failing = work.failing_checks(checks)
    # the heartbeat is liveness, not a posture check: without a real check the state is unknown
    real = [k for k in checks if k != work.HEARTBEAT_CHECK]
    state = "noncompliant" if failing else ("compliant" if real else "unknown")
    obs = PostureObservation(
        asset_id=asset.id,
        source=body.source,
        observed_at=observed_at,
        received_at=now,
        expires_at=observed_at + work.posture_max_age(),
        state=state,
        checks=checks,
    )
    db.add(obs)
    db.flush()
    # ponytail: machine ingest is not audited (rows carry source and received_at; one per
    # minute per device would drown the audit log). Human IT submissions are.
    if actor:
        audit.record(db, actor, "posture.ingest", "asset", asset.id, after={"state": state})
    db.commit()
    return {"id": str(obs.id), "state": state}


# ---- IT maintenance exceptions (PLAN.md section 11) ---------------------------------------------

MAX_EXCEPTION = timedelta(days=7)


class MaintenanceIn(BaseModel):
    reason: str = Field(min_length=10, max_length=1000)
    approver_id: uuid.UUID
    expires_at: AwareDatetime


def _exception_view(x: MaintenanceException) -> dict:
    return {
        "id": str(x.id),
        "asset_id": str(x.asset_id),
        "reason": x.reason,
        "requested_by": str(x.requested_by),
        "approver_id": str(x.approver_id),
        "expires_at": x.expires_at.isoformat(),
        "created_at": x.created_at.isoformat(),
    }


@router.post("/devices/{asset_id}/maintenance-exceptions", status_code=201)
def create_maintenance_exception(
    asset_id: uuid.UUID,
    body: MaintenanceIn,
    emp: Employee = Depends(require_roles("it")),
    db: Session = Depends(get_db),
):
    """Record why a device is out of policy for a while. Records only: it never hides a failing
    posture check. Needs a second person (approver role or admin), who is not the device's user."""
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(404, "not found")
    now = work.utcnow()
    if body.expires_at <= now or body.expires_at - now > MAX_EXCEPTION:
        raise HTTPException(422, "expires_at must be in the future, within 7 days")
    approver = db.get(Employee, body.approver_id)
    if (
        approver is None
        or approver.status != "active"
        or not has_role(approver, "approver", "admin")
        or approver.id in (emp.id, asset.assigned_employee_id)
    ):
        raise HTTPException(
            422, "approver must be an active approver/admin, not you and not the device's user"
        )
    x = MaintenanceException(
        asset_id=asset.id,
        reason=body.reason,
        requested_by=emp.id,
        approver_id=approver.id,
        expires_at=body.expires_at,
    )
    db.add(x)
    db.flush()
    audit.record(
        db,
        emp,
        "maintenance_exception.create",
        "asset",
        asset.id,
        reason=body.reason,
        after=_exception_view(x),
    )
    db.commit()
    return _exception_view(x)


@router.get("/devices/{asset_id}/maintenance-exceptions")
def list_maintenance_exceptions(
    asset_id: uuid.UUID,
    emp: Employee = Depends(require_roles("it", "security")),
    db: Session = Depends(get_db),
):
    rows = db.scalars(
        select(MaintenanceException)
        .where(MaintenanceException.asset_id == asset_id)
        .order_by(MaintenanceException.created_at.desc())
        .limit(100)
    ).all()
    now = work.utcnow()
    return {"exceptions": [{**_exception_view(x), "active": x.expires_at > now} for x in rows]}
