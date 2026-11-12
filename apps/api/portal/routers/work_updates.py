"""Daily work updates. Employees write their own; corrections keep history; nobody else rewrites."""

import uuid
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from portal import audit
from portal.authz import can_view_employee, current_employee, get_visible_employee
from portal.db import get_db
from portal.models import Employee, WorkUpdate, WorkUpdateCorrection
from portal.services import work

router = APIRouter(tags=["work-updates"])


class Deliverable(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    url: str | None = Field(default=None, max_length=2000)

    @field_validator("url")
    @classmethod
    def _http_only(cls, v: str | None) -> str | None:
        if v and not v.lower().startswith(("http://", "https://")):
            raise ValueError("url must be http(s)")
        return v


class UpdateBody(BaseModel):
    summary: str = Field(min_length=1, max_length=4000)
    task_refs: list[str] = Field(default_factory=list, max_length=50)
    deliverables: list[Deliverable] = Field(default_factory=list, max_length=50)
    blocker: str | None = Field(default=None, max_length=2000)

    @field_validator("task_refs")
    @classmethod
    def _short_refs(cls, v: list[str]) -> list[str]:
        if any(not r or len(r) > 200 for r in v):
            raise ValueError("task_refs must be 1-200 characters each")
        return v


class CreateIn(UpdateBody):
    update_date: date | None = None  # default: today in the employee's timezone


class CorrectIn(UpdateBody):
    reason: str = Field(min_length=1, max_length=1000)


def _snapshot(u: WorkUpdate) -> dict[str, Any]:
    return {
        "summary": u.summary,
        "task_refs": u.task_refs,
        "deliverables": u.deliverables,
        "blocker": u.blocker,
    }


def _view(u: WorkUpdate, detail: bool = False) -> dict:
    out = {
        "id": str(u.id),
        "employee_id": str(u.employee_id),
        "update_date": u.update_date.isoformat(),
        **_snapshot(u),
        "created_at": u.created_at.isoformat(),
        "updated_at": u.updated_at.isoformat(),
        "correction_count": len(u.corrections),
    }
    if detail:
        out["corrections"] = [
            {
                "id": str(c.id),
                "corrected_by": str(c.corrected_by),
                "previous": c.previous,
                "reason": c.reason,
                "created_at": c.created_at.isoformat(),
            }
            for c in u.corrections
        ]
    return out


def _load_visible(db: Session, emp: Employee, update_id: uuid.UUID) -> WorkUpdate:
    u = db.get(WorkUpdate, update_id)
    owner = db.get(Employee, u.employee_id) if u else None
    if u is None or owner is None or not can_view_employee(emp, owner):
        raise HTTPException(404, "not found")
    return u


@router.post("/work-updates", status_code=201)
def create_update(
    body: CreateIn, emp: Employee = Depends(current_employee), db: Session = Depends(get_db)
):
    today = work.local_today(emp)
    day = body.update_date or today
    if day > today:
        raise HTTPException(422, "update_date cannot be in the future")
    if day < today - timedelta(days=30):
        raise HTTPException(422, "update_date is more than 30 days old")
    u = WorkUpdate(
        employee_id=emp.id,
        update_date=day,
        summary=body.summary,
        task_refs=body.task_refs,
        deliverables=[d.model_dump() for d in body.deliverables],
        blocker=body.blocker,
    )
    db.add(u)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "an update for that date exists; correct it instead") from None
    db.commit()
    return _view(u, detail=True)


@router.get("/work-updates")
def list_updates(
    employee_id: uuid.UUID | None = None,
    since: date | None = None,
    limit: int = Query(50, ge=1, le=200),
    emp: Employee = Depends(current_employee),
    db: Session = Depends(get_db),
):
    """Own updates; a direct manager passes employee_id."""
    target = get_visible_employee(db, emp, employee_id) if employee_id else emp
    q = select(WorkUpdate).where(WorkUpdate.employee_id == target.id)
    if since:
        q = q.where(WorkUpdate.update_date >= since)
    rows = db.scalars(q.order_by(WorkUpdate.update_date.desc()).limit(limit)).all()
    return {"work_updates": [_view(u) for u in rows]}


@router.get("/work-updates/{update_id}")
def get_update(
    update_id: uuid.UUID, emp: Employee = Depends(current_employee), db: Session = Depends(get_db)
):
    return _view(_load_visible(db, emp, update_id), detail=True)


@router.put("/work-updates/{update_id}")
def correct_update(
    update_id: uuid.UUID,
    body: CorrectIn,
    emp: Employee = Depends(current_employee),
    db: Session = Depends(get_db),
):
    """Owner-only correction. The previous text is kept; managers and admins get 403."""
    u = _load_visible(db, emp, update_id)
    if u.employee_id != emp.id:
        raise HTTPException(403, "only the author can correct a work update")
    # Lock + reload so concurrent corrections serialize and each snapshots the latest version.
    db.refresh(u, with_for_update=True)
    before = _snapshot(u)
    db.add(
        WorkUpdateCorrection(
            work_update_id=u.id, corrected_by=emp.id, previous=before, reason=body.reason
        )
    )
    u.summary = body.summary
    u.task_refs = body.task_refs
    u.deliverables = [d.model_dump() for d in body.deliverables]
    u.blocker = body.blocker
    db.flush()
    audit.record(
        db,
        emp,
        "work_update.correct",
        "work_update",
        u.id,
        reason=body.reason,
        before=before,
        after=_snapshot(u),
    )
    db.commit()
    db.refresh(u)
    return _view(u, detail=True)
