from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from portal import jobs
from portal.connectors.xrdp import XrdpAdapter
from portal.models import AuditEvent, ConnectorCheckpoint, Job


def by_name(rows):
    return {r["name"]: r for r in rows}


def test_it_and_admin_only(client_for, make_employee):
    for roles in (["employee"], ["manager"], ["security"]):
        c = client_for(make_employee(roles=roles))
        assert c.get("/api/v1/operations/connectors").status_code == 403
        assert c.get("/api/v1/operations/jobs/failed").status_code == 403
    for roles in (["it"], ["admin"]):
        assert (
            client_for(make_employee(roles=roles)).get("/api/v1/operations/connectors").status_code
            == 200
        )


def test_connector_health_fields_and_stale_flag(db, client_for, make_employee, monkeypatch):
    monkeypatch.setenv("WAZUH_ENABLED", "1")
    monkeypatch.setenv("GITEA_ENABLED", "1")
    monkeypatch.setenv("XRDP_ENABLED", "1")
    now = datetime.now(UTC)
    db.add_all(
        [
            ConnectorCheckpoint(
                name="wazuh",
                cursor="c",
                last_success_at=now - timedelta(seconds=30),
                last_attempt_at=now,
                capabilities={"edition": "opensearch"},
            ),
            ConnectorCheckpoint(
                name="gitea",
                last_success_at=now - timedelta(hours=1),
                last_error="GET /: credentials rejected (401) token=SHOULDNOTLEAK",
            ),
        ]
    )
    db.commit()
    rows = by_name(
        client_for(make_employee(roles=["it"])).get("/api/v1/operations/connectors").json()
    )
    assert set(rows) == {"wazuh", "keycloak", "guacamole", "gitea", "fleet", "kimai", "xrdp"}
    w = rows["wazuh"]
    assert w["enabled"] and not w["stale"] and w["capabilities"] == {"edition": "opensearch"}
    assert 25 < w["cursor_age_seconds"] < 120 and w["last_error"] is None
    g = rows["gitea"]
    assert (
        g["stale"]
        and "credentials rejected" in g["last_error"]
        and "SHOULDNOTLEAK" not in g["last_error"]
    )
    assert not rows["xrdp"]["stale"] and not rows["xrdp"]["polled"]
    assert not rows["fleet"]["enabled"] and not rows["fleet"]["stale"]


def test_enabled_connector_never_polled_is_stale(client_for, make_employee, monkeypatch):
    monkeypatch.setenv("FLEET_ENABLED", "1")
    rows = by_name(
        client_for(make_employee(roles=["admin"])).get("/api/v1/operations/connectors").json()
    )
    assert rows["fleet"]["stale"] and rows["fleet"]["last_success_at"] is None


def failed_job(db, kind="connector.poll", error="boom"):
    job = jobs.enqueue(db, kind, {"name": "x"}, max_attempts=1)
    job.status, job.attempts, job.last_error = "failed", 1, error
    job.finished_at = datetime.now(UTC)
    db.commit()
    return job


def test_failed_queue_and_retry(db, client_for, make_employee):
    job = failed_job(db, error="HTTP 503 Bearer abcdef123456")
    ok = db.scalars(select(Job).where(Job.id == jobs.enqueue(db, "k", {}).id)).one()
    db.commit()
    c = client_for(make_employee(roles=["it"]))
    listed = c.get("/api/v1/operations/jobs/failed").json()
    assert [j["id"] for j in listed] == [str(job.id)] and "abcdef123456" not in listed[0][
        "last_error"
    ]
    assert c.post(f"/api/v1/operations/jobs/{ok.id}/retry").status_code == 409  # not failed
    r = c.post(f"/api/v1/operations/jobs/{job.id}/retry")
    assert r.status_code == 200 and r.json()["status"] == "queued"
    db.expire_all()
    job = db.get(Job, job.id)
    assert job.status == "queued" and job.attempts == 0
    assert c.get("/api/v1/operations/jobs/failed").json() == []
    assert db.scalars(select(AuditEvent).where(AuditEvent.action == "job.retry")).one()
    assert (
        c.post("/api/v1/operations/jobs/00000000-0000-0000-0000-000000000000/retry").status_code
        == 404
    )


def test_retry_needs_csrf_headers_and_role(db, app, make_employee, client_for):
    job = failed_job(db)
    c = client_for(make_employee(roles=["employee"]))
    assert c.post(f"/api/v1/operations/jobs/{job.id}/retry").status_code == 403
    it = client_for(make_employee(roles=["it"]))
    assert (
        it.post(
            f"/api/v1/operations/jobs/{job.id}/retry", headers={"Origin": "http://evil"}
        ).status_code
        == 403
    )


def test_xrdp_operator_task_flow(db, client_for, make_employee):
    target, it = make_employee(), make_employee(roles=["it"])
    adapter = XrdpAdapter()
    res = adapter.revoke(target)
    db.commit()
    assert res.status == "manual_required"
    assert adapter.verify(target) is False
    adapter.revoke(target)  # idempotent: still one task
    db.commit()
    task = db.scalars(select(Job).where(Job.kind == "operator.task")).one()
    assert task.status == "failed"  # parked: visible in the queue, never run by the worker
    assert not jobs.run_one(db)

    c = client_for(it)
    assert str(task.id) in [j["id"] for j in c.get("/api/v1/operations/jobs/failed").json()]
    assert c.post(f"/api/v1/operations/jobs/{task.id}/retry").status_code == 409
    assert (
        c.post(
            f"/api/v1/operations/operator-tasks/{task.id}/confirm", json={"note": " "}
        ).status_code
        == 422
    )
    assert (
        c.post(
            f"/api/v1/operations/operator-tasks/{task.id}/confirm",
            json={"note": "killed 2 sessions on vm-3"},
        ).status_code
        == 200
    )
    db.expire_all()
    assert adapter.verify(target) is True
    assert db.get(Job, task.id).payload["confirmed_by"] == str(it.id)
    assert db.scalars(select(AuditEvent).where(AuditEvent.action == "operator_task.confirm")).one()
    assert c.get("/api/v1/operations/jobs/failed").json() == []


def test_confirm_rejects_non_operator_jobs(db, client_for, make_employee):
    job = failed_job(db)
    c = client_for(make_employee(roles=["it"]))
    assert (
        c.post(
            f"/api/v1/operations/operator-tasks/{job.id}/confirm", json={"note": "x"}
        ).status_code
        == 404
    )
