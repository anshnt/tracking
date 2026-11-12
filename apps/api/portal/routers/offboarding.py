"""Offboarding jobs (PLAN.md section 12). admin or it only. Mounted under /api/v1.

POST /offboarding-jobs (reason, Idempotency-Key header, confirm_employee_id must match),
GET /offboarding-jobs, GET /offboarding-jobs/{id},
POST /offboarding-jobs/{id}/steps/{subsystem}/complete (a person records a manual step),
POST /offboarding-jobs/{id}/retry. Logic lives in portal.flows.offboarding.
"""

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from portal.authz import require_roles
from portal.db import get_db
from portal.flows import offboarding as flow
from portal.models import Employee, OffboardingJob

router = APIRouter(tags=["offboarding"])
operator = require_roles("admin", "it")


class OffboardRequest(BaseModel):
    employee_id: uuid.UUID
    confirm_employee_id: uuid.UUID  # explicit target review: must equal employee_id
    reason: str = Field(min_length=1, max_length=2000)


class StepDone(BaseModel):
    note: str = Field(min_length=1, max_length=2000)


def _job(db: Session, job_id: uuid.UUID) -> OffboardingJob:
    job = flow._lock_job(db, job_id)
    if job is None:
        raise HTTPException(404, "not found")
    return job


@router.post("/offboarding-jobs", status_code=201)
def create_offboarding_job(
    body: OffboardRequest,
    response: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key", max_length=200),
    emp: Employee = Depends(operator),
    db: Session = Depends(get_db),
):
    if not idempotency_key or not idempotency_key.strip():
        raise HTTPException(400, "Idempotency-Key header is required")
    if not body.reason.strip():
        raise HTTPException(422, "reason is required")
    job, created = flow.create_job(
        db,
        emp,
        body.employee_id,
        body.confirm_employee_id,
        body.reason.strip(),
        idempotency_key.strip(),
    )
    db.commit()
    if not created:
        response.status_code = 200
    return flow.view(job)


@router.get("/offboarding-jobs")
def list_offboarding_jobs(
    limit: int = Query(100, ge=1, le=500),
    emp: Employee = Depends(operator),
    db: Session = Depends(get_db),
):
    q = select(OffboardingJob).order_by(OffboardingJob.requested_at.desc()).limit(limit)
    return [flow.view(j) for j in db.scalars(q)]


@router.get("/offboarding-jobs/{job_id}")
def get_offboarding_job(
    job_id: uuid.UUID, emp: Employee = Depends(operator), db: Session = Depends(get_db)
):
    job = db.get(OffboardingJob, job_id)
    if job is None:
        raise HTTPException(404, "not found")
    return flow.view(job)


@router.post("/offboarding-jobs/{job_id}/steps/{subsystem}/complete")
def complete_step(
    job_id: uuid.UUID,
    subsystem: str,
    body: StepDone,
    emp: Employee = Depends(operator),
    db: Session = Depends(get_db),
):
    job = flow.mark_step_done(db, emp, _job(db, job_id), subsystem, body.note.strip())
    db.commit()
    return flow.view(job)


@router.post("/offboarding-jobs/{job_id}/retry", status_code=202)
def retry_job(job_id: uuid.UUID, emp: Employee = Depends(operator), db: Session = Depends(get_db)):
    job = _job(db, job_id)
    if job.status == "verified_complete":
        raise HTTPException(409, "already verified complete")
    flow.wake(db, job)
    db.commit()
    return flow.view(job)
