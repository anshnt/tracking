from datetime import timedelta

from portal.models import TaskSnapshot, WorkUpdate
from portal.services.work import local_today, previous_weekday

FORBIDDEN_KEYS = {"score", "rank", "ranking", "productivity", "percent", "percentage", "rating"}


def _keys(obj, acc=None):
    acc = set() if acc is None else acc
    if isinstance(obj, dict):
        for k, v in obj.items():
            acc.add(k.lower())
            _keys(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _keys(v, acc)
    return acc


def _task(db, emp, ref, **kw):
    db.add(
        TaskSnapshot(
            source="g", source_ref=ref, assignee_id=emp.id, title=kw.pop("title", ref), **kw
        )
    )
    db.commit()


def test_roles_required(make_employee, client_for):
    for roles in (["employee"], ["it"], ["security"], ["approver"]):
        assert client_for(make_employee(roles=roles)).get("/api/v1/overview").status_code == 403


def test_manager_sees_only_direct_reports(db, make_employee, client_for):
    mgr, other_mgr = make_employee(roles=["manager"]), make_employee(roles=["manager"])
    mine = make_employee(manager=mgr, display_name="Mine")
    theirs = make_employee(manager=other_mgr, display_name="Theirs")
    _task(db, mine, "1")
    _task(db, theirs, "2", title="secret")
    r = client_for(mgr).get("/api/v1/overview")
    people = r.json()["people"]
    assert [p["employee_id"] for p in people] == [str(mine.id)]
    assert "secret" not in r.text
    assert client_for(other_mgr).get("/api/v1/overview").json()["people"][0]["employee_id"] == str(
        theirs.id
    )


def test_admin_without_manager_role_gets_no_overview(db, make_employee, client_for):
    admin = make_employee(roles=["admin"])
    make_employee(manager=admin)
    assert client_for(admin).get("/api/v1/overview").status_code == 403
    both = make_employee(roles=["admin", "manager"])
    make_employee(), make_employee()  # not their reports
    assert client_for(both).get("/api/v1/overview").json()["people"] == []


def test_facts_per_person_and_no_scores(db, make_employee, client_for):
    mgr = make_employee(roles=["manager"])
    zed = make_employee(manager=mgr, display_name="Zed")
    amy = make_employee(manager=mgr, display_name="Amy")
    today = local_today(amy)
    _task(db, amy, "1", state="in_review", title="review me")
    _task(db, amy, "2", state="blocked", blocker="waiting on vendor", title="blocked one")
    _task(db, amy, "3", due_date=today - timedelta(days=2), title="late")
    _task(db, amy, "4", state="done", due_date=today - timedelta(days=9), title="finished")
    _task(db, zed, "5", title="zed task")
    db.add(
        WorkUpdate(
            employee_id=amy.id, update_date=previous_weekday(today), summary="y", blocker="stuck"
        )
    )
    db.commit()
    body = client_for(mgr).get("/api/v1/overview").json()
    assert [p["display_name"] for p in body["people"]] == [
        "Amy",
        "Zed",
    ]  # alphabetical, never ranked
    a, z = body["people"]
    assert {t["title"] for t in a["assignments"]} == {"review me", "blocked one", "late"}
    assert [t["title"] for t in a["awaiting_review"]] == ["review me"]
    assert [t["title"] for t in a["blockers"]] == ["blocked one"]
    assert [t["title"] for t in a["overdue"]] == ["late"]
    assert a["latest_update"]["blocker"] == "stuck" and a["missing_update_for"] is None
    assert z["missing_update_for"] == previous_weekday(local_today(zed)).isoformat()
    assert not (_keys(body) & FORBIDDEN_KEYS)
