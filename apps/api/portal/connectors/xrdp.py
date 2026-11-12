"""xrdp / OS session revocation. There is no safe remote API for this, so it is an operator task.

revoke() files an operator task (a `jobs` row of kind operator.task, parked as 'failed' so it is in
the operator-visible queue and the worker never runs it) and returns manual_required.
verify() is True only after an operator confirms via POST /v1/operations/operator-tasks/{id}/confirm.
Env: XRDP_ENABLED=1 to register this adapter.
"""

from sqlalchemy import select
from sqlalchemy.orm import object_session

from portal import jobs
from portal.connectors.base import RevocationAdapter, StepResult
from portal.models import Job

KIND = "operator.task"


def task_key(employee) -> str:
    return f"xrdp-revoke:{employee.id}"


class XrdpAdapter(RevocationAdapter):
    name = "xrdp"

    def capabilities(self) -> dict:
        return {"edition": "operator-task", "automated": False}

    def revoke(self, employee) -> StepResult:
        db = object_session(employee)
        job = jobs.enqueue(
            db,
            KIND,
            {
                "employee_id": str(employee.id),
                "instruction": "Terminate xrdp and OS sessions, background tasks and SSH/RDP "
                "connections for this employee on every workspace VM, then confirm.",
            },
            idempotency_key=task_key(employee),
            max_attempts=1,
        )
        if job.status == "queued":  # new task: park it so only a human closes it
            job.status = "failed"
            job.attempts = job.max_attempts
            job.last_error = "operator action required: terminate OS sessions for the employee"
        return StepResult("manual_required", f"operator task {job.id} filed; confirm when done")

    def verify(self, employee) -> bool:
        db = object_session(employee)
        status = db.scalars(
            select(Job.status).where(Job.idempotency_key == task_key(employee))
        ).first()
        return status == "succeeded"
