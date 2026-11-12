from datetime import timedelta

from sqlalchemy import select

from portal.models import AuditEvent, WorkUpdate
from portal.services.work import local_today, utcnow

NOBODY = "00000000-0000-0000-0000-000000000001"


def _post(c, **over):
    body = {"summary": "did things", "task_refs": ["T-1"], "blocker": None, **over}
    return c.post("/api/v1/work-updates", json=body)


def test_create_and_duplicate_conflict(make_employee, client_for):
    c = client_for(make_employee())
    r = _post(c, deliverables=[{"title": "doc", "url": "https://x.example/d"}])
    assert r.status_code == 201 and r.json()["deliverables"][0]["title"] == "doc"
    assert _post(c).status_code == 409  # one per day; use a correction


def test_validation(make_employee, client_for):
    e = make_employee()
    c = client_for(e)
    tomorrow = (local_today(e) + timedelta(days=1)).isoformat()
    old = (local_today(e) - timedelta(days=40)).isoformat()
    assert _post(c, update_date=tomorrow).status_code == 422
    assert _post(c, update_date=old).status_code == 422
    assert _post(c, summary="").status_code == 422
    assert _post(c, deliverables=[{"title": "x", "url": "javascript:alert(1)"}]).status_code == 422
    assert _post(c, summary="x" * 4001).status_code == 422


def test_correction_keeps_history_and_audits(db, make_employee, client_for):
    e = make_employee()
    c = client_for(e)
    uid = _post(c, summary="v1").json()["id"]
    r = c.put(f"/api/v1/work-updates/{uid}", json={"summary": "v2", "reason": "typo"})
    assert r.status_code == 200
    body = r.json()
    assert body["summary"] == "v2" and body["correction_count"] == 1
    assert body["corrections"][0]["previous"]["summary"] == "v1"
    assert body["corrections"][0]["reason"] == "typo"
    assert c.put(f"/api/v1/work-updates/{uid}", json={"summary": "v3"}).status_code == 422  # reason
    assert db.scalar(select(AuditEvent).where(AuditEvent.action == "work_update.correct"))


def test_manager_cannot_rewrite_but_can_read(db, make_employee, client_for):
    mgr = make_employee(roles=["manager"])
    rep, stranger = make_employee(manager=mgr), make_employee()
    uid = _post(client_for(rep), summary="mine").json()["id"]
    cm = client_for(mgr)
    assert cm.get(f"/api/v1/work-updates/{uid}").status_code == 200
    assert (
        cm.put(f"/api/v1/work-updates/{uid}", json={"summary": "x", "reason": "r"}).status_code
        == 403
    )
    admin = client_for(make_employee(roles=["admin"]))  # not in the management chain: no access
    assert admin.get(f"/api/v1/work-updates/{uid}").status_code == 404
    assert (
        admin.put(f"/api/v1/work-updates/{uid}", json={"summary": "x", "reason": "r"}).status_code
        == 404
    )
    assert admin.get(f"/api/v1/work-updates?employee_id={rep.id}").status_code == 404
    assert db.get(WorkUpdate, uid).summary == "mine"
    cs = client_for(stranger)
    assert cs.get(f"/api/v1/work-updates/{uid}").status_code == 404
    assert (
        cs.put(f"/api/v1/work-updates/{uid}", json={"summary": "x", "reason": "r"}).status_code
        == 404
    )
    assert cs.get(f"/api/v1/work-updates/{NOBODY}").status_code == 404


def test_list_authorization(make_employee, client_for):
    mgr, other_mgr = make_employee(roles=["manager"]), make_employee(roles=["manager"])
    rep, stranger = make_employee(manager=mgr), make_employee()
    _post(client_for(rep), summary="rep update")
    assert [
        u["summary"] for u in client_for(rep).get("/api/v1/work-updates").json()["work_updates"]
    ] == ["rep update"]
    got = client_for(mgr).get(f"/api/v1/work-updates?employee_id={rep.id}")
    assert got.status_code == 200 and len(got.json()["work_updates"]) == 1
    assert client_for(mgr).get("/api/v1/work-updates").json()["work_updates"] == []  # own only
    for who in (other_mgr, stranger, rep):
        target = rep if who is not rep else mgr
        assert (
            client_for(who).get(f"/api/v1/work-updates?employee_id={target.id}").status_code == 404
        )


def test_timezone_default_date(make_employee, client_for):
    e = make_employee(timezone="Pacific/Kiritimati")  # UTC+14: local date can be ahead of UTC
    r = _post(client_for(e)).json()
    assert r["update_date"] == local_today(e, utcnow()).isoformat()
