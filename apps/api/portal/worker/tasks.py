"""Job handlers for connectors, retention and the scheduler. Imported by portal.worker.__main__.

scheduler.tick    every POLL_SECONDS: queue one connector.poll per enabled connector, the daily
                  retention.apply, and the next tick. All keyed by time bucket, so a restarted
                  worker or a second worker never doubles anything.
connector.poll    capability probe, then (event source) fetch pages and persist each page with its
                  cursor in one transaction, or (snapshot connector) run its poll().
retention.apply   portal.retention.apply_retention.

Failure handling: 429 -> visible error + a new poll after Retry-After; 401/403 -> visible error,
no retry storm (next tick tries again); anything else -> visible error and raise, so the job
retries with the bounded exponential backoff in portal.jobs and lands in the failed queue.
"""

import logging
import os
from datetime import UTC, datetime, timedelta

from portal import ingest, jobs, retention
from portal.connectors import base, registry
from portal.connectors.http import AuthRejected, RateLimited
from portal.jobs import job_handler

log = logging.getLogger("portal.worker")
MAX_PAGES_PER_POLL = 20


def poll_seconds() -> int:
    return max(int(os.environ.get("CONNECTOR_POLL_SECONDS", "60")), 5)


def _now() -> datetime:
    return datetime.now(UTC)


def schedule(db, now: datetime | None = None) -> None:
    """Enqueue this bucket's tick (idempotent). Called at worker start; ticks chain themselves."""
    now = now or _now()
    bucket = int(now.timestamp() // poll_seconds())
    jobs.enqueue(db, "scheduler.tick", {}, idempotency_key=f"tick:{bucket}", run_at=now)
    db.commit()


@job_handler("scheduler.tick")
def tick(db, job) -> None:
    now = _now()
    step = poll_seconds()
    bucket = int(now.timestamp() // step)
    for name in registry.LIVE:
        if name in registry.NOT_POLLED:
            continue
        jobs.enqueue(db, "connector.poll", {"name": name}, idempotency_key=f"poll:{name}:{bucket}")
    jobs.enqueue(db, "retention.apply", {}, idempotency_key=f"retention:{now.date()}")
    # keyed by bucket so a dead chain (purge, export expiry) is re-seeded within one tick
    jobs.enqueue(db, "sessions.purge", {}, idempotency_key=f"sessions.purge:{now.date()}")
    jobs.enqueue(db, "export.expire", {}, idempotency_key=f"export.expire:tick:{bucket}")
    nxt = bucket + 1
    jobs.enqueue(
        db,
        "scheduler.tick",
        {},
        idempotency_key=f"tick:{nxt}",
        run_at=datetime.fromtimestamp(nxt * step, UTC),
    )


@job_handler("retention.apply")
def run_retention(db, job) -> None:
    result = retention.apply_retention(db)
    log.info("retention: deleted=%s paused=%s", result.deleted, result.paused_by_hold)


@job_handler("connector.poll")
def poll(db, job) -> None:
    name = job.payload["name"]
    conn = registry.LIVE.get(name) or base.EVENT_SOURCES.get(name)
    if conn is None:
        log.warning("connector %s is not enabled; skipping poll", name)
        return
    try:
        caps = conn.capabilities() if hasattr(conn, "capabilities") else None
        if isinstance(conn, base.EventSource):
            _pull_events(db, conn, caps)
        else:
            extra = conn.poll(db) if hasattr(conn, "poll") else None
            ingest.record_probe(db, name, {**(caps or {}), **({"stats": extra} if extra else {})})
    except RateLimited as exc:
        ingest.record_error(db, name, str(exc))
        run_at = _now() + timedelta(seconds=exc.retry_after)
        jobs.enqueue(
            db,
            "connector.poll",
            {"name": name},
            idempotency_key=f"poll:{name}:retry:{int(run_at.timestamp())}",
            run_at=run_at,
        )
    except AuthRejected as exc:
        ingest.record_error(db, name, str(exc))  # visible on the health page; not retried hard
    except Exception as exc:  # noqa: BLE001 - record, then let portal.jobs retry with backoff
        ingest.record_error(db, name, f"{type(exc).__name__}: {exc}")
        raise


def _pull_events(db, source: base.EventSource, caps: dict | None) -> None:
    from portal.models import ConnectorCheckpoint

    cp = db.get(ConnectorCheckpoint, source.name)
    cursor = cp.cursor if cp else None
    case_min = getattr(source, "case_min_severity", None)
    pulled = 0
    for _ in range(MAX_PAGES_PER_POLL):
        events, nxt = source.fetch(cursor)
        res = ingest.persist(db, source.name, events, nxt, case_min_severity=case_min)
        pulled += res.inserted
        rejected = getattr(source, "last_rejected", 0)
        if rejected:
            log.warning(
                "%s: %d records failed schema checks and were dropped", source.name, rejected
            )
        if not events or nxt == cursor:
            break
        cursor = nxt
    stats = {"rejected_last_poll": getattr(source, "last_rejected", 0)}
    ingest.record_probe(db, source.name, {**(caps or {}), **stats})
