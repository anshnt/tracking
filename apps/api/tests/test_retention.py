import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select, text

from portal import jobs, retention
from portal.models import (
    AuditEvent,
    Case,
    DeletionTombstone,
    ExportDecision,
    ExportRequest,
    LegalHold,
    RetentionRule,
    SecurityEvent,
    WorkUpdate,
)
from portal.worker import __main__ as worker  # noqa: F401  (registers handlers)

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=UTC)


def event(days_old, policy="security-90d", employee_id=None, sid=None):
    return SecurityEvent(
        id=uuid.uuid4(),
        source="t",
        source_event_id=sid or uuid.uuid4().hex,
        event_type="t.x",
        occurred_at=NOW - timedelta(days=days_old),
        retention_policy=policy,
        employee_id=employee_id,
    )


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_defaults_are_seeded_without_overwriting(db):
    db.add(RetentionRule(data_class="security-90d", retention_days=7))
    db.commit()
    retention.seed_default_rules(db)
    db.commit()
    days = {r.data_class: r.retention_days for r in db.scalars(select(RetentionRule))}
    assert days == {
        "raw-activity-30d": 30,
        "security-90d": 7,  # operator's value kept
        "approvals-180d": 180,
        "work-summary-365d": 365,
    }


def test_expired_rows_deleted_fresh_kept_and_tombstoned(db):
    old_raw, new_raw = event(31, "raw-activity-30d"), event(29, "raw-activity-30d")
    old_sec, new_sec = event(91), event(89)
    db.add_all([old_raw, new_raw, old_sec, new_sec])
    db.commit()
    res = retention.apply_retention(db, NOW)
    assert res.deleted == {"security_event": 2}
    left = {e.id for e in db.scalars(select(SecurityEvent))}
    assert left == {new_raw.id, new_sec.id}
    tombs = {t.subject_id for t in db.scalars(select(DeletionTombstone))}
    assert tombs == {str(old_raw.id), str(old_sec.id)}
    assert db.scalars(select(AuditEvent).where(AuditEvent.action == "retention.applied")).one()


def test_evidence_of_an_open_case_survives_the_90_day_purge(db):
    kept, gone = event(91), event(91)
    db.add_all([kept, gone])
    db.add(Case(title="t", reason="r", evidence_refs=[str(kept.id)]))
    db.commit()
    retention.apply_retention(db, NOW)
    assert {e.id for e in db.scalars(select(SecurityEvent))} == {kept.id}


def test_employee_legal_hold_protects_only_that_employee(db, make_employee):
    held, other = make_employee(), make_employee()
    keep, drop = event(200, employee_id=held.id), event(200, employee_id=other.id)
    db.add_all(
        [keep, drop, LegalHold(employee_id=held.id, scope="case 1", reason="x", placed_by=other.id)]
    )
    db.commit()
    retention.apply_retention(db, NOW)
    assert {e.id for e in db.scalars(select(SecurityEvent))} == {keep.id}


def test_released_hold_no_longer_protects(db, make_employee):
    emp = make_employee()
    db.add_all(
        [
            event(200, employee_id=emp.id),
            LegalHold(employee_id=emp.id, scope="s", reason="r", placed_by=emp.id, released_at=NOW),
        ]
    )
    db.commit()
    retention.apply_retention(db, NOW)
    assert count(db, SecurityEvent) == 0


def test_global_hold_pauses_everything(db, make_employee):
    emp = make_employee()
    db.add_all([event(400), LegalHold(scope="all", reason="litigation", placed_by=emp.id)])
    db.commit()
    res = retention.apply_retention(db, NOW)
    assert (
        res.paused_by_hold and count(db, SecurityEvent) == 1 and count(db, DeletionTombstone) == 0
    )


def test_work_updates_and_exports_follow_their_rules(db, make_employee):
    a, b = make_employee(), make_employee()
    db.add_all(
        [
            WorkUpdate(employee_id=a.id, update_date=date(2025, 10, 1), summary="old"),
            WorkUpdate(employee_id=a.id, update_date=date(2026, 10, 1), summary="new"),
        ]
    )
    old = ExportRequest(
        requester_id=a.id, object_ref="o", classification="internal", recipient="r",
        purpose="p", status="released", updated_at=NOW - timedelta(days=200),
    )  # fmt: skip
    live = ExportRequest(
        requester_id=a.id, object_ref="o", classification="internal", recipient="r",
        purpose="p", status="requested", updated_at=NOW - timedelta(days=200),
    )  # fmt: skip
    db.add_all([old, live])
    db.flush()
    db.add(
        ExportDecision(export_request_id=old.id, reviewer_id=b.id, decision="approved", reason="ok")
    )
    db.commit()
    res = retention.apply_retention(db, NOW)
    assert res.deleted == {"work_update": 1, "export_request": 1}  # open request is never expired
    assert count(db, ExportDecision) == 0
    assert db.scalars(select(WorkUpdate.summary)).all() == ["new"]


def test_audit_events_are_never_touched(db):
    db.add(AuditEvent(action="old.thing", target_type="x", created_at=NOW - timedelta(days=4000)))
    db.commit()
    retention.apply_retention(db, NOW)
    assert db.scalars(select(AuditEvent).where(AuditEvent.action == "old.thing")).one()


def test_reapply_tombstones_after_restore(db, make_employee):
    gone = event(200)
    db.add(gone)
    db.commit()
    retention.apply_retention(db, NOW)
    assert count(db, SecurityEvent) == 0
    db.add(event(200))  # unrelated row: must survive
    restored = SecurityEvent(
        id=gone.id, source="t", source_event_id=gone.source_event_id, event_type="t.x",
        occurred_at=gone.occurred_at, retention_policy="security-90d",
    )  # fmt: skip
    db.add(restored)  # a backup brought the deleted row back
    db.commit()
    assert retention.reapply_tombstones(db) == {"security_event": 1}
    remaining = db.scalars(select(SecurityEvent)).all()
    assert len(remaining) == 1 and remaining[0].id != gone.id


def test_reapply_respects_current_legal_hold(db, make_employee):
    emp = make_employee()
    gone = event(200, employee_id=emp.id)
    db.add(gone)
    db.commit()
    retention.apply_retention(db, NOW)
    db.add(SecurityEvent(id=gone.id, source="t", source_event_id="back", event_type="t.x",
                         occurred_at=gone.occurred_at, employee_id=emp.id))  # fmt: skip
    db.add(LegalHold(employee_id=emp.id, scope="s", reason="r", placed_by=emp.id))
    db.commit()
    assert retention.reapply_tombstones(db) == {}
    assert count(db, SecurityEvent) == 1


def test_retention_runs_as_a_scheduled_job(db):
    db.add(event(500))
    db.commit()
    jobs.enqueue(db, "retention.apply", {})
    db.commit()
    assert jobs.run_one(db)
    assert count(db, SecurityEvent) == 0


def test_owner_script_expires_old_audit_events_and_records_the_run(db):
    import os
    from pathlib import Path

    import psycopg

    for age in (200, 10):
        db.execute(
            text(
                "insert into audit_events (action, target_type, created_at) "
                "values ('x', 'y', now() - make_interval(days => :d))"
            ),
            {"d": age},
        )
    db.commit()
    sql = (Path(__file__).parents[1] / "scripts" / "expire_audit_events.sql").read_text()
    url = os.environ["TEST_DATABASE_URL"].replace("+psycopg", "")
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql)
    assert db.scalar(select(func.count()).select_from(AuditEvent)) == 1
    run = db.scalars(
        select(DeletionTombstone).where(DeletionTombstone.subject_type == "audit_events_expiry")
    ).one()
    assert run.subject_id.endswith("count=1")
