from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from portal import jobs
from portal.connectors import base, registry
from portal.connectors.base import EventSource, FakeEventSource, NormalizedEvent
from portal.connectors.http import AuthRejected, RateLimited
from portal.models import ConnectorCheckpoint, Job, SecurityEvent
from portal.worker import __main__ as worker  # noqa: F401  (registers the task handlers)
from portal.worker import tasks

NOW = datetime.now(UTC)


@pytest.fixture(autouse=True)
def _registries():
    base.EVENT_SOURCES.clear()
    registry.LIVE.clear()
    yield
    base.EVENT_SOURCES.clear()
    registry.LIVE.clear()


def events(n, severity="info"):
    return [
        NormalizedEvent(
            source="fake",
            source_event_id=f"e{i}",
            event_type="t.x",
            occurred_at=NOW - timedelta(minutes=1),
            severity=severity,
        )
        for i in range(n)
    ]


def poll(db, name="fake", now=None):
    jobs.enqueue(db, "connector.poll", {"name": name})
    db.commit()
    return jobs.run_one(db, now)


def n_events(db):
    return db.scalar(select(func.count()).select_from(SecurityEvent))


def test_poll_drains_pages_and_stores_cursor(db):
    base.register_event_source(FakeEventSource("fake", events(5), page_size=2))
    assert poll(db)
    assert n_events(db) == 5
    cp = db.get(ConnectorCheckpoint, "fake")
    assert cp.cursor == "5" and cp.last_error is None and cp.last_success_at is not None
    assert poll(db) and n_events(db) == 5  # nothing new, no duplicates


def test_poll_resumes_from_stored_cursor(db):
    src = base.register_event_source(FakeEventSource("fake", events(3), page_size=10))
    poll(db)
    src.events += [
        NormalizedEvent(source="fake", source_event_id="late", event_type="t.x", occurred_at=NOW)
    ]
    poll(db)
    assert n_events(db) == 4


def test_failing_source_is_visible_then_retried_with_backoff_then_parked(db):
    base.register_event_source(FakeEventSource("fake", events(1), fail=True))
    jobs.enqueue(db, "connector.poll", {"name": "fake"}, max_attempts=3)
    db.commit()
    t = datetime.now(UTC) + timedelta(seconds=1)
    for attempt in range(3):
        assert jobs.run_one(db, t)
        db.expire_all()
        job = db.scalars(select(Job)).one()
        if attempt < 2:
            assert job.status == "queued" and job.run_at > t
        t = job.run_at + timedelta(seconds=1)
    assert job.status == "failed" and "fake source failure" in job.last_error
    cp = db.get(ConnectorCheckpoint, "fake")
    assert "fake source failure" in cp.last_error and cp.last_success_at is None


class Raising(EventSource):
    name = "fake"

    def __init__(self, exc):
        self.exc = exc

    def fetch(self, cursor):
        raise self.exc


def test_revoked_credentials_surface_as_connector_error_without_retry_storm(db):
    base.register_event_source(Raising(AuthRejected("GET /: credentials rejected (401)")))
    poll(db)
    job = db.scalars(select(Job)).one()
    assert job.status == "succeeded"
    assert "credentials rejected" in db.get(ConnectorCheckpoint, "fake").last_error


def test_rate_limit_schedules_a_later_poll(db):
    base.register_event_source(Raising(RateLimited(120)))
    poll(db, now=datetime.now(UTC) + timedelta(seconds=1))
    db.expire_all()
    later = db.scalars(select(Job).where(Job.status == "queued")).one()
    assert later.kind == "connector.poll" and later.run_at >= datetime.now(UTC) + timedelta(
        seconds=110
    )
    assert "rate limited" in db.get(ConnectorCheckpoint, "fake").last_error


def test_poll_of_disabled_connector_is_a_noop(db):
    assert poll(db, name="ghost")
    assert db.scalars(select(Job)).one().status == "succeeded"


def test_snapshot_connector_poll_records_probe_and_stats(db):
    class Snap:
        name = "snap"

        def capabilities(self):
            return {"edition": "x"}

        def poll(self, db):
            return {"hosts": 2}

    registry.LIVE["snap"] = Snap()
    poll(db, "snap")
    cp = db.get(ConnectorCheckpoint, "snap")
    assert cp.capabilities == {"edition": "x", "stats": {"hosts": 2}} and cp.last_success_at


def test_wazuh_events_open_cases_through_the_job(db):
    src = FakeEventSource("fake", events(2, severity="critical"))
    src.case_min_severity = "high"
    base.register_event_source(src)
    poll(db)
    from portal.models import Case

    assert db.scalar(select(func.count()).select_from(Case)) == 2


def test_tick_queues_polls_once_per_bucket_and_chains(db, monkeypatch):
    monkeypatch.setenv("CONNECTOR_POLL_SECONDS", "60")
    registry.LIVE["wazuh"] = object()
    registry.LIVE["xrdp"] = object()  # operator-task only: never polled
    tasks.schedule(db)
    tasks.schedule(db)  # idempotent
    assert db.scalar(select(func.count()).select_from(Job).where(Job.kind == "scheduler.tick")) == 1
    assert jobs.run_one(db)
    kinds = sorted(j.kind + ":" + j.payload.get("name", "") for j in db.scalars(select(Job)))
    assert "connector.poll:wazuh" in kinds and "connector.poll:xrdp" not in kinds
    assert "sessions.purge:" in kinds and "export.expire:" in kinds
    assert "retention.apply:" in kinds and kinds.count("scheduler.tick:") == 2
    tick_runs = sorted(
        j.run_at for j in db.scalars(select(Job).where(Job.kind == "scheduler.tick"))
    )
    assert tick_runs[1] > tick_runs[0]
