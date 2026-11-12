"""Operations (PLAN.md section 10): connector health, failed-job queue, operator tasks. IT/admin only.

  GET  /v1/operations/connectors                  enabled, last success, cursor age, last error, capabilities, stale
  GET  /v1/operations/jobs/failed                 the operator-visible failed-job queue
  POST /v1/operations/jobs/{id}/retry             requeue a failed job
  POST /v1/operations/operator-tasks/{id}/confirm an operator confirms a manual step was done

Stale = enabled, polled, and no success within CONNECTOR_STALE_SECONDS (default 5 minutes) or never.
A successful call is not proof collection is complete, so "stale" is a flag, not a verdict.
"""

import os
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from portal import audit
from portal.authz import require_roles
from portal.connectors import registry
from portal.connectors.http import redact
from portal.connectors.xrdp import KIND as OPERATOR_TASK_KIND
from portal.db import get_db
from portal.models import ConnectorCheckpoint, Employee, Job

router = APIRouter(tags=["operations"])
ops = Depends(require_roles("it", "admin"))


def stale_seconds() -> int:
    return int(os.environ.get("CONNECTOR_STALE_SECONDS", "300"))


def _iso(dt):
    return dt.isoformat() if dt else None


@router.get("/operations/connectors")
def connectors(db: Session = Depends(get_db), _: Employee = ops):
    now = datetime.now(UTC)
    checkpoints = {c.name: c for c in db.scalars(select(ConnectorCheckpoint))}
    out = []
    for name in registry.CONNECTOR_NAMES:
        enabled = registry.is_enabled(name)
        cp = checkpoints.get(name)
        polled = name not in registry.NOT_POLLED
        age = (now - cp.last_success_at).total_seconds() if cp and cp.last_success_at else None
        out.append(
            {
                "name": name,
                "enabled": enabled,
                "polled": polled,
                "last_success_at": _iso(cp.last_success_at) if cp else None,
                "last_attempt_at": _iso(cp.last_attempt_at) if cp else None,
                "cursor_age_seconds": age,
                "last_error": redact(cp.last_error) if cp and cp.last_error else None,
                "capabilities": cp.capabilities if cp else {},
                "stale": bool(enabled and polled and (age is None or age > stale_seconds())),
            }
        )
    return out


def _job_view(j: Job) -> dict:
    return {
        "id": str(j.id),
        "kind": j.kind,
        "attempts": j.attempts,
        "max_attempts": j.max_attempts,
        "last_error": redact(j.last_error) if j.last_error else None,
        "created_at": _iso(j.created_at),
        "finished_at": _iso(j.finished_at),
    }


@router.get("/operations/jobs/failed")
def failed_jobs(limit: int = 100, db: Session = Depends(get_db), _: Employee = ops):
    rows = db.scalars(
        select(Job)
        .where(Job.status == "failed")
        .order_by(Job.finished_at.desc().nullslast())
        .limit(min(max(limit, 1), 500))
    )
    return [_job_view(j) for j in rows]


@router.post("/operations/jobs/{job_id}/retry")
def retry_job(job_id: uuid.UUID, db: Session = Depends(get_db), emp: Employee = ops):
    job = db.get(Job, job_id, with_for_update=True)
    if job is None:
        raise HTTPException(404, "not found")
    if job.status != "failed":
        raise HTTPException(409, "only failed jobs can be retried")
    if job.kind == OPERATOR_TASK_KIND:
        raise HTTPException(409, "operator tasks are confirmed, not retried")
    job.status, job.attempts, job.run_at = "queued", 0, datetime.now(UTC)
    job.locked_at = job.finished_at = None
    audit.record(
        db, emp, "job.retry", "job", job.id, before={"status": "failed"}, after={"status": "queued"}
    )
    db.commit()
    return _job_view(job) | {"status": job.status}


class Confirm(BaseModel):
    note: str


@router.post("/operations/operator-tasks/{job_id}/confirm")
def confirm_operator_task(
    job_id: uuid.UUID, body: Confirm, db: Session = Depends(get_db), emp: Employee = ops
):
    job = db.get(Job, job_id, with_for_update=True)
    if job is None or job.kind != OPERATOR_TASK_KIND:
        raise HTTPException(404, "not found")
    if not body.note.strip():
        raise HTTPException(422, "a note describing what was done is required")
    if job.status == "succeeded":
        return {"id": str(job.id), "status": "succeeded"}
    job.status, job.finished_at, job.last_error = "succeeded", datetime.now(UTC), None
    job.payload = {**job.payload, "confirmed_by": str(emp.id), "note": body.note.strip()[:500]}
    audit.record(db, emp, "operator_task.confirm", "job", job.id, reason=body.note.strip()[:500])
    db.commit()
    return {"id": str(job.id), "status": "succeeded"}
