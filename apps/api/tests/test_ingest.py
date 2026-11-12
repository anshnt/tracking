from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from portal import ingest
from portal.connectors.base import NormalizedEvent
from portal.models import Asset, Case, ConnectorCheckpoint, SecurityEvent

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


def ev(sid="e1", **kw) -> NormalizedEvent:
    kw.setdefault("event_type", "auth.login_failed")
    kw.setdefault("occurred_at", NOW - timedelta(minutes=1))
    return NormalizedEvent(source="test", source_event_id=sid, **kw)


def count(db, model=SecurityEvent):
    return db.scalar(select(func.count()).select_from(model))


def test_normalize_drops_unlisted_and_forbidden_metadata():
    out = ingest.normalize(
        ev(
            metadata={
                "rule_id": "5710",
                "window_title": "Payroll - Chrome",
                "clipboard": "hunter2",
                "password": "x",
                "api_token": "abc",
                "random_key": "nope",
                "ref": "https://git.example/org/repo/pull/3?token=SECRET&x=1#frag",
                "labels": ["a", {"nested": 1}],
                "agent_name": {"nested": "dict"},
            }
        ),
        NOW,
    )
    assert out.metadata == {
        "rule_id": "5710",
        "ref": "https://git.example/org/repo/pull/3",
        "labels": ["a"],
    }


def test_normalize_rejects_invalid():
    for bad in (ev(severity="catastrophic"), ev(classification="secret"), ev(sid=" ")):
        with pytest.raises(ingest.RejectedEvent):
            ingest.normalize(bad, NOW)


def test_normalize_clamps_future_clock_and_makes_utc():
    out = ingest.normalize(ev(occurred_at=NOW + timedelta(hours=2)), NOW)
    assert out.occurred_at == NOW and out.metadata["clock_skew_s"] == 7200
    naive = ingest.normalize(ev(occurred_at=datetime(2026, 11, 12, 10, 0)), NOW)
    assert naive.occurred_at.tzinfo is not None


def test_persist_dedups_and_replay_is_harmless(db):
    batch = [ev("a"), ev("b"), ev("a")]
    r1 = ingest.persist(db, "test", batch, "2", now=NOW)
    assert (r1.inserted, r1.duplicates) == (2, 1)
    r2 = ingest.persist(db, "test", list(reversed(batch)), "2", now=NOW)  # replay, reordered
    assert (r2.inserted, r2.duplicates) == (0, 3)
    assert count(db) == 2
    assert db.get(ConnectorCheckpoint, "test").cursor == "2"


def test_cursor_and_events_are_atomic(db, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("crash before cursor commit")

    monkeypatch.setattr(ingest, "_advance", boom)
    with pytest.raises(RuntimeError):
        ingest.persist(db, "test", [ev("a")], "9", now=NOW)
    assert count(db) == 0 and db.get(ConnectorCheckpoint, "test") is None


def test_rejected_records_are_counted_not_fatal(db):
    r = ingest.persist(db, "test", [ev("a"), ev("b", severity="bogus")], "2", now=NOW)
    assert (r.inserted, r.rejected) == (1, 1)
    assert db.get(ConnectorCheckpoint, "test").cursor == "2"


def test_cases_only_for_threshold_and_never_duplicated(db):
    events = [
        ev("lo", severity="medium"),
        ev("hi", severity="high"),
        ev("crit", severity="critical"),
    ]
    r = ingest.persist(db, "test", events, "3", case_min_severity="high", now=NOW)
    assert r.cases == 2 and count(db, Case) == 2
    ingest.persist(db, "test", list(reversed(events)), "3", case_min_severity="high", now=NOW)
    assert count(db, Case) == 2  # replay: no new cases
    case = db.scalars(select(Case).where(Case.severity == "critical")).one()
    event = db.scalars(select(SecurityEvent).where(SecurityEvent.source_event_id == "crit")).one()
    assert case.evidence_refs == [str(event.id)]


def test_no_cases_without_threshold(db):
    ingest.persist(db, "test", [ev("hi", severity="critical")], "1", now=NOW)
    assert count(db, Case) == 0


def test_identity_resolved_exactly_or_left_unresolved(db, make_employee):
    emp = make_employee(email="amy@example.invalid")
    asset = Asset(name="lap", ownership="company", upstream_ids={"test": "007"})
    db.add(asset)
    db.commit()
    ingest.persist(
        db,
        "test",
        [
            ev("known", actor="AMY@example.invalid", metadata={"agent_id": "007"}),
            ev("unknown", actor="nobody@example.invalid", metadata={"agent_id": "999"}),
            ev("anon"),
        ],
        "3",
        now=NOW,
    )
    rows = {e.source_event_id: e for e in db.scalars(select(SecurityEvent))}
    assert rows["known"].employee_id == emp.id and rows["known"].asset_id == asset.id
    assert rows["unknown"].employee_id is None and rows["unknown"].asset_id is None
    assert rows["anon"].employee_id is None


def test_stored_metadata_is_sanitized(db):
    ingest.persist(
        db, "test", [ev("a", metadata={"window_title": "secret doc", "rule_id": "1"})], "1", now=NOW
    )
    assert db.scalars(select(SecurityEvent)).one().event_metadata == {"rule_id": "1"}
