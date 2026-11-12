import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from alembic import command
from portal import audit, authz, jobs
from portal.connectors.base import (
    FakeEventSource,
    FakeRevocationAdapter,
    NormalizedEvent,
    StepResult,
)
from portal.main import create_app
from portal.models import AuditEvent, Employee, Job, PolicyVersion
from tests.conftest import API_DIR


def test_health(app):
    resp = TestClient(app).get("/api/health")
    assert resp.status_code == 200 and resp.json() == {"status": "ok", "db": True}


def test_security_headers_and_request_id(app):
    resp = TestClient(app).get("/api/health", headers={"X-Request-ID": "req-12345678"})
    assert resp.headers["content-security-policy"].startswith("default-src 'self'")
    assert resp.headers["x-request-id"] == "req-12345678"
    assert resp.headers["cache-control"] == "no-store"
    bad = TestClient(app).get("/api/health", headers={"X-Request-ID": "bad id!"})
    assert len(bad.headers["x-request-id"]) == 32


def test_unauthenticated_is_401(app):
    assert TestClient(app).get("/api/v1/me").status_code == 401


def test_migrations_match_models():
    command.check(Config(str(API_DIR / "alembic.ini")))


# ---- CSRF -----------------------------------------------------------------------------------


def test_csrf_rejections(make_employee, client_for):
    client = client_for(make_employee())
    url = "/api/auth/logout"
    assert client.post(url, headers={"X-Requested-With": ""}).status_code == 403  # no custom header
    assert client.post(url, headers={"Origin": "http://evil.test"}).status_code == 403
    assert client.post(url, headers={"Origin": "null"}).status_code == 403
    no_origin = TestClient(client.app, headers={"X-Requested-With": "portal"})
    assert no_origin.post(url).status_code == 403  # neither Origin nor Referer
    assert (
        no_origin.post(url, headers={"Referer": "http://testserver/some/page"}).status_code == 200
    )
    assert (
        client.get("/api/v1/me", headers={"Origin": "http://evil.test"}).status_code == 200
    )  # safe
    assert client.post(url).status_code == 200


# ---- authz ----------------------------------------------------------------------------------


def test_require_roles(make_employee, client_for, monkeypatch):
    import portal.main

    monkeypatch.setattr(
        portal.main, "WEB_DIST", Path("/nonexistent")
    )  # SPA catch-all would shadow the test route
    app = create_app()

    @app.get("/api/_t/sec")
    def sec(emp: Employee = Depends(authz.require_roles("security", "admin"))):
        return {"id": str(emp.id)}

    def as_(emp):
        c = client_for(emp)
        c.app = app  # reuse cookie + headers against the extended app
        return TestClient(app, headers=c.headers, cookies=c.cookies)

    assert as_(make_employee(["employee"])).get("/api/_t/sec").status_code == 403
    assert as_(make_employee(["manager", "it"])).get("/api/_t/sec").status_code == 403
    assert as_(make_employee(["security"])).get("/api/_t/sec").status_code == 200
    assert as_(make_employee(["admin"])).get("/api/_t/sec").status_code == 200
    assert TestClient(app).get("/api/_t/sec").status_code == 401
    with pytest.raises(ValueError):
        authz.require_roles()


def test_can_view_employee(make_employee, db):
    boss = make_employee(["employee", "manager"])
    report = make_employee(manager=boss)
    other_mgr = make_employee(["employee", "manager"])
    stranger = make_employee()
    admin = make_employee(["admin"])
    non_manager_boss = make_employee(["employee"])
    report2 = make_employee(manager=non_manager_boss)

    assert authz.can_view_employee(report, report)
    assert authz.can_view_employee(boss, report)
    assert not authz.can_view_employee(other_mgr, report)  # managers only see direct reports
    assert not authz.can_view_employee(stranger, report)
    assert not authz.can_view_employee(report, boss)
    assert not authz.can_view_employee(non_manager_boss, report2)  # needs the manager role
    assert not authz.can_view_employee(admin, report)  # admin is not in the management chain

    assert authz.get_visible_employee(db, boss, report.id).id == report.id
    for actor, target in ((other_mgr, report.id), (boss, uuid.uuid4())):
        with pytest.raises(Exception) as exc:
            authz.get_visible_employee(db, actor, target)
        assert exc.value.status_code == 404


def test_forbid_self(make_employee):
    emp = make_employee()
    with pytest.raises(Exception) as exc:
        authz.forbid_self(emp, emp.id)
    assert exc.value.status_code == 403
    authz.forbid_self(emp, uuid.uuid4())


# ---- audit ----------------------------------------------------------------------------------


def test_audit_record_hashes_and_is_append_only(db, make_employee):
    emp = make_employee()
    ev = audit.record(
        db,
        emp,
        "thing.update",
        "thing",
        7,
        reason="because",
        before={"a": 1},
        after={"a": 2},
        request_id="rid-1",
    )
    db.commit()
    assert ev.before_hash == audit.digest({"a": 1}) != ev.after_hash
    assert ev.target_id == "7" and ev.request_id == "rid-1" and ev.actor_id == emp.id
    assert audit.digest({"b": 1, "a": 2}) == audit.digest({"a": 2, "b": 1})  # canonical
    assert audit.record(db, None, "sys", "x", None).actor_id is None  # system actor

    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text("update audit_events set reason = 'tampered'"))
    db.rollback()
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text("delete from audit_events"))
    db.rollback()
    assert db.scalars(select(AuditEvent)).first().reason == "because"


def test_oidc_subject_and_policy_versions_immutable(db, make_employee):
    emp = make_employee()
    with pytest.raises(DBAPIError, match="immutable"):
        db.execute(text("update employees set oidc_subject = 'other'"))
    db.rollback()
    db.execute(text("update employees set display_name = 'ok'"))  # other columns still editable
    db.add(PolicyVersion(name="collection", version=1, content={}, content_hash="h"))
    db.commit()
    with pytest.raises(DBAPIError, match="append-only"):
        db.execute(text("update policy_versions set content_hash = 'x'"))
    db.rollback()
    assert emp.id


def test_db_constraints(db, make_employee):
    emp = make_employee()
    emp.status = "bogus"
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    with pytest.raises(IntegrityError):  # an employee cannot be their own manager
        db.execute(text("update employees set manager_id = id"))
    db.rollback()


# ---- jobs -----------------------------------------------------------------------------------


@pytest.fixture
def handlers():
    saved = dict(jobs.HANDLERS)
    yield jobs.HANDLERS
    jobs.HANDLERS.clear()
    jobs.HANDLERS.update(saved)


def test_enqueue_idempotent(db):
    a = jobs.enqueue(db, "k", {"x": 1}, idempotency_key="once")
    b = jobs.enqueue(db, "k", {"x": 2}, idempotency_key="once")
    db.commit()
    assert a.id == b.id and b.payload == {"x": 1}
    assert len(db.scalars(select(Job)).all()) == 1


def test_run_one_success_and_unregistered(db, handlers):
    seen = []

    @jobs.job_handler("ok")
    def ok(session, job):
        seen.append(job.payload)

    with pytest.raises(RuntimeError):
        jobs.job_handler("ok")(ok)  # duplicate registration is an error
    jobs.enqueue(db, "ok", {"n": 1})
    jobs.enqueue(db, "nobody-handles-this", max_attempts=1)
    db.commit()
    assert jobs.run_one(db) and jobs.run_one(db) and not jobs.run_one(db)
    assert seen == [{"n": 1}]
    by_kind = {j.kind: j for j in db.scalars(select(Job)).all()}
    assert by_kind["ok"].status == "succeeded" and by_kind["ok"].finished_at
    assert by_kind["nobody-handles-this"].status == "failed"
    assert "no handler" in by_kind["nobody-handles-this"].last_error


def test_retry_backoff_then_failed_state(db, handlers):
    @jobs.job_handler("boom")
    def boom(session, job):
        raise ValueError("nope")

    jobs.enqueue(db, "boom", max_attempts=3)
    db.commit()
    t0 = datetime.now(UTC)
    delays = []
    for attempt in range(1, 4):
        when = t0 + timedelta(hours=attempt * 2)
        assert jobs.run_one(db, now=when)
        job = db.scalars(select(Job)).one()
        db.refresh(job)
        assert job.attempts == attempt and "ValueError: nope" in job.last_error
        delays.append((job.run_at - when).total_seconds())
    assert delays[:2] == [5, 10]  # exponential
    assert job.status == "failed" and job.finished_at  # operator-visible, no more retries
    assert not jobs.run_one(db, now=t0 + timedelta(days=1))


def test_not_due_and_backoff_cap(db, handlers):
    @jobs.job_handler("later")
    def later(session, job):
        pass

    jobs.enqueue(db, "later", run_at=datetime.now(UTC) + timedelta(hours=1))
    db.commit()
    assert not jobs.run_one(db)
    j = Job(kind="x", attempts=30, max_attempts=99, status="running")
    db.add(j)
    db.commit()
    jobs.fail(db, j, "e", now=datetime(2030, 1, 1, tzinfo=UTC))
    assert (j.run_at - datetime(2030, 1, 1, tzinfo=UTC)).total_seconds() == jobs.BACKOFF_CAP_SECONDS


def test_claim_skips_locked_rows_and_reclaims_stale_leases(db):
    from portal.db import session_factory

    jobs.enqueue(db, "k")
    db.commit()
    with session_factory()() as holder, session_factory()() as other:
        locked = holder.scalars(select(Job).with_for_update()).one()  # hold the row lock
        assert locked.status == "queued"
        assert jobs.claim(other) is None  # SKIP LOCKED: does not block, does not double-claim
        holder.rollback()
        claimed = jobs.claim(other)
        assert claimed is not None and claimed.status == "running" and claimed.attempts == 1
        assert jobs.claim(other) is None  # running and fresh
        later = datetime.now(UTC) + timedelta(seconds=jobs.LEASE_SECONDS + 5)
        assert jobs.claim(other, now=later).attempts == 2  # crashed worker: lease expired


def test_stale_running_job_out_of_attempts_is_failed_not_rerun(db):
    j = jobs.enqueue(db, "poison", max_attempts=2)
    db.commit()
    now = datetime.now(UTC)
    assert jobs.claim(db, now=now).attempts == 1
    later = now + timedelta(seconds=jobs.LEASE_SECONDS + 5)
    assert jobs.claim(db, now=later).attempts == 2  # second (last) attempt, then the worker dies
    much_later = later + timedelta(seconds=jobs.LEASE_SECONDS + 5)
    assert jobs.claim(db, now=much_later) is None
    db.refresh(j)
    assert j.status == "failed" and j.attempts == 2 and j.last_error


def test_worker_drain(db, handlers):
    from portal.worker.__main__ import drain

    ran = []

    @jobs.job_handler("w")
    def w(session, job):
        ran.append(job.id)

    jobs.enqueue(db, "w")
    jobs.enqueue(db, "w")
    db.commit()
    assert drain() == 2 and len(ran) == 2


# ---- connector interfaces ---------------------------------------------------------------------


def test_fake_connectors(make_employee):
    now = datetime.now(UTC)
    events = [NormalizedEvent("fake", f"e{i}", "login", now) for i in range(5)]
    src = FakeEventSource(events=events, page_size=2)
    page, cursor = src.fetch(None)
    assert [e.source_event_id for e in page] == ["e0", "e1"] and cursor == "2"
    page, cursor = src.fetch(cursor)
    page, cursor = src.fetch(cursor)
    assert [e.source_event_id for e in page] == ["e4"] and src.fetch(cursor)[0] == []

    emp = make_employee()
    adapter = FakeRevocationAdapter(result=StepResult("succeeded", "ok"))
    assert not adapter.verify(emp)
    assert adapter.revoke(emp).status == "succeeded" and adapter.verify(emp)


def test_api_docs_are_not_served_in_production(monkeypatch):
    from types import SimpleNamespace

    from fastapi.testclient import TestClient

    from portal import main

    assert TestClient(main.create_app()).get("/openapi.json").status_code == 200  # dev keeps them
    monkeypatch.setattr(main, "get_settings", lambda: SimpleNamespace(is_production=True))
    c = TestClient(main.create_app())
    for path in ("/openapi.json", "/docs", "/redoc"):
        r = c.get(path)  # 404, or the SPA shell when a web build is present; never the schema
        assert r.status_code in (200, 404) and '"paths"' not in r.text and "swagger" not in r.text
