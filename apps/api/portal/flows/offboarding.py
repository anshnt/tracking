"""Offboarding (PLAN.md section 12): ordered, separately tracked, retryable steps.

Done in the request transaction (so it holds even if the worker is down): the employee is moved
to `offboarding` (new logins and every request are refused), portal sessions are revoked, open
exports are cancelled. The worker job `offboarding.run` then drives the adapter steps through the
RevocationAdapter registry, parks manual steps for a human, and finally runs `verify`.

A job is `verified_complete` only when every step succeeded (a human may mark a manual or stuck
step done with a note) and the independent verify pass confirmed access is gone. Anything else is
`incomplete` and says which step. Personal devices are never touched: there is no wipe step.
"""

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from portal import audit, auth, jobs
from portal.connectors import base
from portal.flows import exports as export_flow
from portal.jobs import job_handler
from portal.models import (
    Employee,
    ExportRequest,
    OffboardingJob,
    OffboardingStep,
    PortalSession,
    Workspace,
)

ADAPTER, INTERNAL, MANUAL, VERIFY = "adapter", "internal", "manual", "verify"
STEPS = (
    ("disable_identity", ADAPTER),
    ("terminate_portal_sessions", INTERNAL),
    ("terminate_gateway_sessions", ADAPTER),
    ("terminate_os_sessions", ADAPTER),
    ("revoke_repo_tokens", ADAPTER),
    ("revoke_vpn_peers", ADAPTER),
    ("revoke_export_grants", INTERNAL),
    ("suspend_workspaces", INTERNAL),
    ("revoke_app_passwords", MANUAL),
    ("transfer_ownership", MANUAL),  # cases, task assignments, workspaces: reassign, keep records
    ("rotate_shared_credentials", MANUAL),
    ("review_assets", MANUAL),
    ("verify", VERIFY),
)
KIND = dict(STEPS)
# step name -> name the connector registers under (registry.py). A test or operator may also
# register an adapter directly under the step name, which wins. No VPN adapter exists yet, so
# revoke_vpn_peers stays skipped_not_configured (never counted as complete).
STEP_ADAPTER = {
    "disable_identity": "keycloak",
    "terminate_gateway_sessions": "guacamole",
    "terminate_os_sessions": "xrdp",
    "revoke_repo_tokens": "gitea",
}


def adapter_for(subsystem: str):
    return base.REVOCATION_ADAPTERS.get(subsystem) or base.REVOCATION_ADAPTERS.get(
        STEP_ADAPTER.get(subsystem, "")
    )


MANUAL_NOTE = "manual: "
HUMAN_MAY_COMPLETE = ("manual_required", "failed", "skipped_not_configured")
DONE = ("succeeded", "verified")


def _now() -> datetime:
    return datetime.now(UTC)


def _lock_job(db: Session, job_id: uuid.UUID) -> OffboardingJob | None:
    return db.scalars(
        select(OffboardingJob).where(OffboardingJob.id == job_id).with_for_update()
    ).first()


def _step(job: OffboardingJob, name: str) -> OffboardingStep:
    return next(s for s in job.steps if s.subsystem == name)


def view(job: OffboardingJob) -> dict:
    return {
        "id": str(job.id),
        "employee_id": str(job.employee_id),
        "requested_by": str(job.requested_by),
        "reason": job.reason,
        "status": job.status,
        "requested_at": job.requested_at,
        "completed_at": job.completed_at,
        "steps": [
            {
                "subsystem": s.subsystem,
                "status": s.status,
                "detail": s.detail,
                "attempts": s.attempts,
                "verified_at": s.verified_at,
                "updated_at": s.updated_at,
            }
            for s in job.steps
        ],
        "outstanding": [s.subsystem for s in job.steps if s.status not in DONE],
    }


# ---------------------------------------------------------------- request


def _internal(db: Session, actor: Employee | None, job: OffboardingJob, step: OffboardingStep):
    if step.subsystem == "terminate_portal_sessions":
        n = auth.revoke_employee_sessions(db, job.employee_id)
        step.detail = f"{n} portal session(s) revoked"
    elif step.subsystem == "suspend_workspaces":
        n = db.execute(
            update(Workspace)
            .where(
                Workspace.owner_id == job.employee_id,
                Workspace.lifecycle_state.in_(("requested", "active")),
            )
            .values(lifecycle_state="suspended")
        ).rowcount
        step.detail = f"{n} workspace(s) suspended"
    else:  # revoke_export_grants
        n = export_flow.revoke_for_employee(db, actor, job.employee_id, f"offboarding job {job.id}")
        step.detail = f"{n} export request(s) cancelled or expired"
    step.status = "succeeded"
    step.attempts += 1


def create_job(
    db: Session,
    actor: Employee,
    employee_id: uuid.UUID,
    confirm_employee_id: uuid.UUID,
    reason: str,
    idempotency_key: str,
) -> tuple[OffboardingJob, bool]:
    """Returns (job, created). Replaying the same key for the same employee returns the job."""
    if employee_id != confirm_employee_id:
        raise HTTPException(422, "confirm_employee_id must equal employee_id")

    def replay() -> OffboardingJob | None:
        prior = db.scalars(
            select(OffboardingJob).where(OffboardingJob.idempotency_key == idempotency_key)
        ).first()
        if prior and prior.employee_id != employee_id:
            raise HTTPException(409, "Idempotency-Key was already used for a different employee")
        return prior

    if prior := replay():
        return prior, False
    target = db.scalars(
        select(Employee).where(Employee.id == employee_id).with_for_update()
    ).first()
    # a concurrent identical request may have committed while we waited for the row lock
    if prior := replay():
        return prior, False
    if target is None:
        raise HTTPException(404, "employee not found")
    if target.id == actor.id:
        raise HTTPException(403, "cannot offboard yourself")
    if target.status != "active":
        raise HTTPException(409, f"employee is already {target.status}")
    job = OffboardingJob(
        employee_id=target.id, requested_by=actor.id, reason=reason, idempotency_key=idempotency_key
    )
    db.add(job)
    try:
        db.flush()
    except IntegrityError:  # two identical requests raced; the other one won
        db.rollback()
        prior = db.scalars(
            select(OffboardingJob).where(OffboardingJob.idempotency_key == idempotency_key)
        ).one()
        return prior, False
    for i, (name, _kind) in enumerate(STEPS):
        db.add(OffboardingStep(job_id=job.id, seq=i, subsystem=name))
    db.flush()
    db.refresh(job)
    target.status = "offboarding"  # refuses new logins and every authenticated request
    for step in job.steps:
        if KIND[step.subsystem] == INTERNAL:
            _internal(db, actor, job, step)
    jobs.enqueue(
        db, "offboarding.run", {"job_id": str(job.id)}, idempotency_key=f"offboarding.run:{job.id}"
    )
    audit.record(
        db,
        actor,
        "offboarding.request",
        "offboarding_job",
        job.id,
        reason=reason,
        before={"employee_status": "active"},
        after={"employee_id": str(target.id), "employee_status": "offboarding"},
    )
    return job, True


def mark_step_done(
    db: Session, actor: Employee, job: OffboardingJob, subsystem: str, note: str
) -> OffboardingJob:
    step = next((s for s in job.steps if s.subsystem == subsystem), None)
    if step is None:
        raise HTTPException(404, "no such step")
    if KIND[subsystem] in (INTERNAL, VERIFY):
        raise HTTPException(409, "this step is completed by the system, not by hand")
    if step.status not in HUMAN_MAY_COMPLETE:
        raise HTTPException(409, f"step is {step.status}")
    before = step.status
    step.status = "succeeded"
    step.detail = f"{MANUAL_NOTE}{note} (by {actor.display_name})"
    audit.record(
        db,
        actor,
        "offboarding.step_manual_done",
        "offboarding_job",
        job.id,
        reason=note,
        before={"step": subsystem, "status": before},
        after={"step": subsystem, "status": "succeeded"},
    )
    wake(db, job)
    return job


def wake(db: Session, job: OffboardingJob) -> None:
    """Queue another run (retry failed steps, or verify once the last manual step is done)."""
    jobs.enqueue(
        db,
        "offboarding.run",
        {"job_id": str(job.id)},
        idempotency_key=f"offboarding.run:{job.id}:{uuid.uuid4().hex}",
    )


# ---------------------------------------------------------------- worker


def _run_adapter_step(step: OffboardingStep, emp: Employee) -> None:
    adapter = adapter_for(step.subsystem)
    if adapter is None:
        step.status, step.detail = "skipped_not_configured", "no revocation adapter configured"
        return
    step.status = "running"
    step.attempts += 1
    try:
        result = adapter.revoke(emp)
        step.status, step.detail = result.status, result.detail[:500]
    except Exception as exc:  # noqa: BLE001 - any adapter error is a failed, retryable step
        step.status, step.detail = "failed", f"{type(exc).__name__}: {exc}"[:500]


def _verify(db: Session, job: OffboardingJob, emp: Employee) -> list[str]:
    """Independent checks. Returns problems; a failed adapter verify reopens that step."""
    problems: list[str] = []
    live = db.scalar(
        select(func.count())
        .select_from(PortalSession)
        .where(PortalSession.employee_id == emp.id, PortalSession.revoked_at.is_(None))
    )
    if live:
        problems.append(f"{live} portal session(s) still live")
    pending = db.scalar(
        select(func.count())
        .select_from(ExportRequest)
        .where(
            ExportRequest.requester_id == emp.id,
            ExportRequest.status.in_(export_flow.LIVE_STATUSES + ("requested", "reviewed")),
        )
    )
    if pending:
        problems.append(f"{pending} export grant(s) still open")
    active_ws = db.scalar(
        select(func.count())
        .select_from(Workspace)
        .where(Workspace.owner_id == emp.id, Workspace.lifecycle_state == "active")
    )
    if active_ws:
        problems.append(f"{active_ws} workspace(s) still active")
    for step in job.steps:
        adapter = adapter_for(step.subsystem)
        if KIND[step.subsystem] != ADAPTER or adapter is None:
            continue
        # a human-completed adapter step is verified like any other: a note alone proves nothing
        if adapter.verify(emp):
            step.status, step.verified_at = "verified", _now()
        else:
            step.status, step.detail = "failed", "verification failed: access still present"
            problems.append(f"{step.subsystem} verification failed")
    return problems


def run_job(db: Session, job_id: uuid.UUID) -> bool:
    """Advance the job one pass. Commits. Returns True if a failed step wants a retry."""
    job = _lock_job(db, job_id)
    if job is None or job.status == "verified_complete":
        return False
    emp = db.get(Employee, job.employee_id)
    job.status = "in_progress"
    for step in job.steps:
        kind = KIND[step.subsystem]
        if step.status in DONE:
            continue
        if kind == ADAPTER:
            _run_adapter_step(step, emp)
        elif kind == INTERNAL:
            _internal(db, None, job, step)
        elif kind == MANUAL and step.status == "pending":
            step.status = "manual_required"
            step.detail = "waiting for a person to complete and record this step"
    verify = _step(job, "verify")
    others_done = all(s.status in DONE for s in job.steps if s.subsystem != "verify")
    if others_done:
        problems = _verify(db, job, emp)
        if problems:
            verify.status, verify.detail = "failed", "; ".join(problems)[:500]
        else:
            verify.status, verify.detail, verify.verified_at = (
                "succeeded",
                "all checks passed",
                _now(),
            )
            verify.attempts += 1
    else:
        verify.status, verify.detail = "pending", "runs after every other step is complete"
    if all(s.status in DONE for s in job.steps):
        job.status, job.completed_at = "verified_complete", _now()
        emp.status = "offboarded"
        action = "offboarding.verified_complete"
    else:
        job.status = "incomplete"
        action = "offboarding.incomplete"
    audit.record(
        db,
        None,
        action,
        "offboarding_job",
        job.id,
        after={"outstanding": [s.subsystem for s in job.steps if s.status not in DONE]},
    )
    retry = any(s.status == "failed" for s in job.steps)
    db.commit()  # persist progress before the job runner decides whether to retry
    return retry


@job_handler("offboarding.run")
def _run_job(db: Session, job) -> None:
    if run_job(db, uuid.UUID(job.payload["job_id"])):
        raise RuntimeError("offboarding has failed steps; retrying with backoff")
