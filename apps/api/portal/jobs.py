"""Postgres-backed jobs (outbox). Enqueue in the caller's transaction; the worker claims with
SELECT ... FOR UPDATE SKIP LOCKED.

Register a handler from any module under portal/handlers/ (auto-imported by the worker):

    from portal.jobs import job_handler

    @job_handler("connector.sync")
    def sync(db, job):          # raise to retry; return normally to succeed
        ...
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from portal.models import Job

HANDLERS: dict[str, Callable[[Session, Job], None]] = {}

BACKOFF_BASE_SECONDS = 5
BACKOFF_CAP_SECONDS = 3600  # bounded exponential retry
LEASE_SECONDS = 300  # a 'running' job older than this is presumed crashed and reclaimed


def job_handler(kind: str):
    def deco(fn):
        if kind in HANDLERS:
            raise RuntimeError(f"job handler already registered for {kind!r}")
        HANDLERS[kind] = fn
        return fn

    return deco


def _now() -> datetime:
    return datetime.now(UTC)


def enqueue(
    db: Session,
    kind: str,
    payload: dict | None = None,
    idempotency_key: str | None = None,
    run_at: datetime | None = None,
    max_attempts: int = 5,
) -> Job:
    """Does not commit. A repeated idempotency_key returns the existing job unchanged."""
    # run_at comes from the app clock (not the DB default) so claim() compares like with like
    stmt = insert(Job).values(
        kind=kind,
        payload=payload or {},
        idempotency_key=idempotency_key,
        max_attempts=max_attempts,
        run_at=run_at or _now(),
    )
    if idempotency_key is not None:
        stmt = stmt.on_conflict_do_nothing(index_elements=["idempotency_key"])
    job_id = db.execute(stmt.returning(Job.id)).scalar()
    if job_id is None:
        return db.scalars(select(Job).where(Job.idempotency_key == idempotency_key)).one()
    return db.get(Job, job_id)


def claim(db: Session, now: datetime | None = None) -> Job | None:
    """Lock one due job, mark it running, and commit so other workers skip it.

    A stale 'running' job (worker died mid-run) that has used all its attempts is parked as
    'failed' instead of being run again, so a job that kills the worker cannot loop forever.
    ponytail: no lease heartbeat, so a handler longer than LEASE_SECONDS can be double-run.
    """
    now = now or _now()
    stale = now - timedelta(seconds=LEASE_SECONDS)
    while True:
        job = db.scalars(
            select(Job)
            .where(
                ((Job.status == "queued") & (Job.run_at <= now))
                | ((Job.status == "running") & (Job.locked_at < stale))
            )
            .order_by(Job.run_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).first()
        if job is None:
            db.rollback()
            return None
        if job.status == "running" and job.attempts >= job.max_attempts:
            job.status, job.finished_at, job.locked_at = "failed", now, None
            job.last_error = "worker died or lease expired on the final attempt"
            db.commit()
            continue
        job.status = "running"
        job.locked_at = now
        job.attempts += 1
        db.commit()
        return job


def complete(db: Session, job: Job, now: datetime | None = None) -> None:
    job.status = "succeeded"
    job.finished_at = now or _now()
    job.last_error = None
    db.commit()


def fail(db: Session, job: Job, error: str, now: datetime | None = None) -> None:
    """Requeue with bounded exponential backoff, or park as 'failed' (operator-visible)."""
    now = now or _now()
    job.last_error = error[:2000]
    if job.attempts >= job.max_attempts:
        job.status = "failed"
        job.finished_at = now
    else:
        delay = min(BACKOFF_BASE_SECONDS * 2 ** (job.attempts - 1), BACKOFF_CAP_SECONDS)
        job.status = "queued"
        job.run_at = now + timedelta(seconds=delay)
    job.locked_at = None
    db.commit()


def run_one(db: Session, now: datetime | None = None) -> bool:
    """Claim and execute one job. Returns False when nothing was due."""
    job = claim(db, now)
    if job is None:
        return False
    handler = HANDLERS.get(job.kind)
    try:
        if handler is None:
            raise LookupError(f"no handler registered for job kind {job.kind!r}")
        handler(db, job)
        db.commit()  # handler work commits before the success mark, so handlers must be idempotent
    except Exception as exc:  # noqa: BLE001 - any handler error means retry
        db.rollback()
        fail(db, job, f"{type(exc).__name__}: {exc}", now)
    else:
        complete(db, job, now)
    return True
