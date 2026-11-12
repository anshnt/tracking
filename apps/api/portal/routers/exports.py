"""Export requests (PLAN.md sections 10 and 12). Mounted under /api/v1.

POST /export-requests, GET /export-requests[/{id}], POST /export-requests/{id}/decisions
(approver role, never the requester), POST /export-requests/{id}/release (approver or it,
separate capability, revalidated), POST /export-requests/{id}/cancel (requester or admin).
Logic lives in portal.flows.exports.
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from portal.authz import current_employee, has_role, require_roles
from portal.db import get_db
from portal.flows import exports as flow
from portal.models import Employee, ExportRequest

router = APIRouter(tags=["exports"])


class ExportCreate(BaseModel):
    object_ref: str = Field(max_length=512)
    object_version: str | None = Field(default=None, max_length=200)
    object_checksum: str = Field(max_length=64)
    classification: str
    recipient: str = Field(max_length=500)
    purpose: str = Field(max_length=2000)


class Decision(BaseModel):
    decision: Literal["approved", "rejected"]
    reason: str | None = Field(default=None, max_length=2000)


class ReleaseBody(BaseModel):
    recipient: str = Field(max_length=500)  # the releaser confirms who receives it
    channel_note: str = Field(min_length=1, max_length=2000)


class CancelBody(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


def _can_see(emp: Employee, req: ExportRequest) -> bool:
    return emp.id == req.requester_id or has_role(emp, "approver", "it", "admin")


def _visible(db: Session, emp: Employee, export_id: uuid.UUID, lock: bool = False) -> ExportRequest:
    """404 for missing and for not-allowed alike."""
    req = flow.lock_export(db, export_id) if lock else db.get(ExportRequest, export_id)
    if req is None or not _can_see(emp, req):
        raise HTTPException(404, "not found")
    return req


@router.post("/export-requests", status_code=201)
def create_export(
    body: ExportCreate, emp: Employee = Depends(current_employee), db: Session = Depends(get_db)
):
    req = flow.create(db, emp, **body.model_dump())
    db.commit()
    return flow.view(req)


@router.get("/export-requests")
def list_exports(
    status: str | None = None,
    mine: bool = False,
    limit: int = Query(100, ge=1, le=500),
    emp: Employee = Depends(current_employee),
    db: Session = Depends(get_db),
):
    q = select(ExportRequest).order_by(ExportRequest.created_at.desc()).limit(limit)
    if mine or not has_role(emp, "approver", "it", "admin"):
        q = q.where(ExportRequest.requester_id == emp.id)
    if status:
        q = q.where(ExportRequest.status == status)
    return [flow.view(r) for r in db.scalars(q)]


@router.get("/export-requests/{export_id}")
def get_export(
    export_id: uuid.UUID, emp: Employee = Depends(current_employee), db: Session = Depends(get_db)
):
    return flow.view(_visible(db, emp, export_id))


@router.post("/export-requests/{export_id}/decisions")
def decide_export(
    export_id: uuid.UUID,
    body: Decision,
    emp: Employee = Depends(require_roles("approver")),
    db: Session = Depends(get_db),
):
    req = flow.lock_export(db, export_id)
    flow.decide(db, emp, req, body.decision, body.reason)
    db.commit()
    return flow.view(req)


@router.post("/export-requests/{export_id}/release")
def release_export(
    export_id: uuid.UUID,
    body: ReleaseBody,
    emp: Employee = Depends(require_roles("approver", "it")),
    db: Session = Depends(get_db),
):
    req = flow.lock_export(db, export_id)
    flow.release(db, emp, req, body.recipient, body.channel_note)
    db.commit()
    return flow.view(req)


@router.post("/export-requests/{export_id}/cancel")
def cancel_export(
    export_id: uuid.UUID,
    body: CancelBody,
    emp: Employee = Depends(current_employee),
    db: Session = Depends(get_db),
):
    req = _visible(db, emp, export_id, lock=True)
    if emp.id != req.requester_id and not has_role(emp, "admin"):
        raise HTTPException(403, "only the requester or an admin can cancel")
    flow.cancel(db, emp, req, body.reason)
    db.commit()
    return flow.view(req)
