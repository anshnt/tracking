from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from portal.models import Asset, AuditEvent, PostureObservation
from portal.services.work import compute_posture
from tests.conftest import CSRF_HEADERS

NOW = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
NOBODY = "00000000-0000-0000-0000-000000000001"


def _asset(db, owner, ownership="company"):
    a = Asset(name="laptop", ownership=ownership, assigned_employee_id=owner.id)
    db.add(a)
    db.commit()
    return a


def _obs(asset, age_s=60, checks=None, state="compliant"):
    t = NOW - timedelta(seconds=age_s)
    return PostureObservation(
        asset_id=asset.id,
        source="t",
        observed_at=t,
        expires_at=t + timedelta(minutes=15),
        state=state,
        checks=checks or {},
    )


def test_compute_states():
    co = Asset(name="a", ownership="company")
    byod = Asset(name="b", ownership="personal")
    ok = {"disk_encrypted": {"passed": True}, "agent_heartbeat_at": NOW.isoformat()}
    assert compute_posture(co, None, NOW)["state"] == "unknown"
    assert compute_posture(co, _obs(co, 60, ok), NOW)["state"] == "compliant"
    stale = compute_posture(co, _obs(co, 901, ok), NOW)
    assert stale["state"] == "unknown" and stale["reason"] == "stale_observation"
    failing = {"disk_encrypted": {"passed": False, "detail": "off"}, "fw": True}
    bad = compute_posture(co, _obs(co, 60, failing, "noncompliant"), NOW)
    assert bad["state"] == "noncompliant"
    assert bad["failing_checks"] == [{"check": "disk_encrypted", "detail": "off"}]
    assert compute_posture(co, _obs(co, 901, {"x": False}), NOW)["state"] == "unknown"
    assert compute_posture(byod, _obs(byod), NOW)["state"] == "not_applicable"


def test_heartbeat_stale_is_unknown():
    co = Asset(name="a", ownership="company")
    old = (NOW - timedelta(seconds=301)).isoformat()
    fresh = (NOW - timedelta(seconds=30)).isoformat()
    r = compute_posture(co, _obs(co, 60, {"agent_heartbeat_at": old}), NOW)
    assert r["state"] == "unknown" and r["reason"] == "stale_heartbeat"
    assert (
        compute_posture(co, _obs(co, 60, {"agent_heartbeat_at": fresh}), NOW)["state"]
        == "compliant"
    )


def test_get_posture_authorization(db, make_employee, client_for):
    owner, stranger = make_employee(), make_employee()
    it, sec = make_employee(roles=["it"]), make_employee(roles=["security"])
    a = _asset(db, owner)
    for who, code in ((owner, 200), (it, 200), (sec, 200), (stranger, 404)):
        assert client_for(who).get(f"/api/v1/devices/{a.id}/posture").status_code == code
    assert client_for(stranger).get(f"/api/v1/devices/{NOBODY}/posture").status_code == 404


def test_device_list_scoped(db, make_employee, client_for):
    a, b, it = make_employee(), make_employee(), make_employee(roles=["it"])
    _asset(db, a)
    _asset(db, b)
    assert len(client_for(a).get("/api/v1/devices").json()["devices"]) == 1
    assert len(client_for(it).get("/api/v1/devices").json()["devices"]) == 2


def test_byod_posture_not_applicable_and_not_ingested(db, make_employee, client_for):
    owner, it = make_employee(), make_employee(roles=["it"])
    a = _asset(db, owner, "personal")
    p = client_for(owner).get(f"/api/v1/devices/{a.id}/posture").json()
    assert p["state"] == "not_applicable" and p["observed_at"] is None
    r = client_for(it).post(
        f"/api/v1/devices/{a.id}/posture-observations",
        json={"source": "w", "checks": {"x": True}},
    )
    assert r.status_code == 409


def test_ingest_by_it_then_read(db, make_employee, client_for):
    owner, it = make_employee(), make_employee(roles=["it"])
    a = _asset(db, owner)
    url = f"/api/v1/devices/{a.id}/posture-observations"
    checks = {"disk_encrypted": True, "patched": {"passed": False, "detail": "3 missing"}}
    r = client_for(it).post(url, json={"source": "wazuh", "checks": checks})
    assert r.status_code == 201 and r.json()["state"] == "noncompliant"
    p = client_for(owner).get(f"/api/v1/devices/{a.id}/posture").json()
    assert p["state"] == "noncompliant"
    assert p["failing_checks"] == [{"check": "patched", "detail": "3 missing"}]
    assert p["observed_at"]
    assert db.scalar(select(AuditEvent).where(AuditEvent.action == "posture.ingest"))
    good = {
        "disk_encrypted": True,
        "patched": True,
        "agent_heartbeat_at": datetime.now(UTC).isoformat(),
    }
    client_for(it).post(url, json={"source": "wazuh", "checks": good})
    assert client_for(owner).get(f"/api/v1/devices/{a.id}/posture").json()["state"] == "compliant"


def test_ingest_authorization_and_validation(db, make_employee, client_for):
    owner = make_employee()
    other_roles = make_employee(roles=["manager", "security", "admin"])
    a = _asset(db, owner)
    url = f"/api/v1/devices/{a.id}/posture-observations"
    body = {"source": "s", "checks": {"x": True}}
    assert client_for(owner).post(url, json=body).status_code == 403  # own device is read-only
    assert client_for(other_roles).post(url, json=body).status_code == 403  # only it ingests
    it = client_for(make_employee(roles=["it"]))
    assert it.post(url, json={"source": "s", "checks": {"x": "yes"}}).status_code == 422
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    assert it.post(url, json={**body, "observed_at": future}).status_code == 422
    assert it.post(url, json={"source": "s", "checks": {}}).json()["state"] == "unknown"


def test_service_token(db, make_employee, app, monkeypatch):
    a = _asset(db, make_employee())
    url = f"/api/v1/devices/{a.id}/posture-observations"
    body = {"source": "agent", "checks": {"x": True}}
    c = TestClient(app, headers=CSRF_HEADERS)
    monkeypatch.delenv("PORTAL_SERVICE_TOKEN", raising=False)
    assert c.post(url, json=body, headers={"Authorization": "Bearer anything"}).status_code == 401
    monkeypatch.setenv("PORTAL_SERVICE_TOKEN", "s3cret-token")
    assert c.post(url, json=body, headers={"Authorization": "Bearer wrong"}).status_code == 401
    ok = c.post(url, json=body, headers={"Authorization": "Bearer s3cret-token"})
    assert ok.status_code == 201
    assert c.post(url, json=body).status_code == 401  # no cookie, no token


def test_heartbeat_only_observation_is_unknown_not_compliant(db, make_employee, client_for):
    it = make_employee(roles=["employee", "it"])
    owner = make_employee()
    asset = _asset(db, owner)
    c = client_for(it)
    body = {"source": "t", "checks": {"agent_heartbeat_at": datetime.now(UTC).isoformat()}}
    r = c.post(f"/api/v1/devices/{asset.id}/posture-observations", json=body)
    assert r.status_code == 201 and r.json()["state"] == "unknown"
    assert c.get(f"/api/v1/devices/{asset.id}/posture").json()["state"] == "unknown"


def test_maintenance_exception_rules_and_audit(db, make_employee, client_for):
    it = make_employee(roles=["employee", "it"])
    owner = make_employee()
    approver = make_employee(roles=["employee", "approver"])
    asset = _asset(db, owner)
    c = client_for(it)
    url = f"/api/v1/devices/{asset.id}/maintenance-exceptions"
    soon = (datetime.now(UTC) + timedelta(hours=4)).isoformat()
    body = {
        "reason": "reimage after disk swap",
        "approver_id": str(approver.id),
        "expires_at": soon,
    }
    assert client_for(owner).post(url, json=body).status_code == 403
    for bad in (
        {**body, "approver_id": str(it.id)},  # self-approval
        {**body, "approver_id": str(owner.id)},  # the device's own user
        {**body, "approver_id": str(make_employee().id)},  # no approver role
        {**body, "expires_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat()},
        {**body, "expires_at": (datetime.now(UTC) + timedelta(days=30)).isoformat()},
        {**body, "expires_at": "2030-01-01T00:00:00"},  # naive
    ):
        assert c.post(url, json=bad).status_code == 422
    assert c.post(url, json=body).status_code == 201
    listed = c.get(url).json()["exceptions"]
    assert len(listed) == 1 and listed[0]["active"] is True
    assert "maintenance_exception.create" in db.scalars(select(AuditEvent.action)).all()


def test_bearer_collector_ingest_needs_no_csrf_headers(db, make_employee, app, monkeypatch):
    monkeypatch.setenv("PORTAL_SERVICE_TOKEN", "s3cret-token")
    a = _asset(db, make_employee())
    c = TestClient(app)  # no Origin, no X-Requested-With, no cookie: what a collector sends
    r = c.post(
        f"/api/v1/devices/{a.id}/posture-observations",
        json={"source": "agent", "checks": {"x": True}},
        headers={"Authorization": "Bearer s3cret-token"},
    )
    assert r.status_code == 201, r.text
    # non-ASCII token bytes are a 401, not a TypeError 500
    r = c.post(
        f"/api/v1/devices/{a.id}/posture-observations",
        json={"source": "agent", "checks": {"x": True}},
        headers={"Authorization": b"Bearer t\xe9k"},
    )
    assert r.status_code == 401


def test_missing_heartbeat_is_unknown_for_company_device():
    co = Asset(name="a", ownership="company")
    r = compute_posture(co, _obs(co, 60, {"disk": True}), NOW)
    assert r["state"] == "unknown" and r["reason"] == "no_heartbeat"


def test_future_dated_observation_is_never_compliant():
    co = Asset(name="a", ownership="company")
    beat = {"disk": True, "agent_heartbeat_at": NOW.isoformat()}
    future = _obs(co, -86400, beat)  # host clock a day ahead
    r = compute_posture(co, future, NOW)
    assert r["state"] == "unknown" and r["reason"] == "future_observation"


def test_sources_are_combined_not_newest_wins(db, make_employee, client_for):
    owner = make_employee()
    a = _asset(db, owner)
    now = datetime.now(UTC)
    beat = now.isoformat()

    def add(source, age, checks, state):
        t = now - timedelta(seconds=age)
        db.add(
            PostureObservation(
                asset_id=a.id,
                source=source,
                observed_at=t,
                expires_at=t + timedelta(minutes=15),
                state=state,
                checks=checks,
            )
        )

    add("collector", 120, {"patched": False, "agent_heartbeat_at": beat}, "noncompliant")
    add("fleet", 10, {"disk_encryption": True}, "compliant")  # newer, partial, green
    add("fleet", -86400, {"disk_encryption": True}, "compliant")  # future clock: ignored
    db.commit()
    p = client_for(owner).get(f"/api/v1/devices/{a.id}/posture").json()
    assert p["state"] == "noncompliant"
    assert p["failing_checks"] == [{"check": "patched", "detail": None}]
