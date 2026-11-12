"""Security cases: security-role-only access, action catalogue, dedup from events."""

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from portal import jobs
from portal.flows import cases as flow
from portal.models import AuditEvent, Case, SecurityEvent
from portal.worker.__main__ import drain


@pytest.fixture
def sec(make_employee):
    return make_employee(roles=["employee", "security"])


def event(db, subject=None, source="wazuh", sid=None, etype="usb.mass_storage", severity="high"):
    ev = SecurityEvent(
        source=source,
        source_event_id=sid or uuid.uuid4().hex,
        employee_id=subject.id if subject else None,
        event_type=etype,
        severity=severity,
        occurred_at=datetime.now(UTC),
    )
    db.add(ev)
    db.commit()
    return ev


def test_employees_managers_admins_never_see_cases(client_for, make_employee, db, sec):
    mgr = make_employee(roles=["employee", "manager"])
    worker = make_employee(manager=mgr)
    case = flow.create_case_from_event(db, event(db, worker))
    db.commit()
    for who in (
        worker,
        mgr,
        make_employee(roles=["employee", "admin"]),
        make_employee(roles=["it"]),
    ):
        c = client_for(who)
        assert c.get("/api/v1/cases").status_code == 403
        assert c.get(f"/api/v1/cases/{case.id}").status_code == 403
        assert (
            c.post(
                f"/api/v1/cases/{case.id}/actions", json={"action": "comment", "text": "x"}
            ).status_code
            == 403
        )
    assert client_for(sec).get("/api/v1/cases").status_code == 200


def test_list_and_detail(client_for, db, sec, make_employee):
    subject = make_employee()
    case = flow.create_case_from_event(db, event(db, subject))
    db.commit()
    c = client_for(sec)
    listing = c.get("/api/v1/cases").json()
    assert [x["id"] for x in listing] == [str(case.id)]
    assert c.get("/api/v1/cases?status=closed").json() == []
    detail = c.get(f"/api/v1/cases/{case.id}").json()
    assert detail["actions"] == [] and detail["subject_employee_id"] == str(subject.id)
    assert c.get(f"/api/v1/cases/{uuid.uuid4()}").status_code == 404


def test_action_catalogue(client_for, db, sec, make_employee):
    other_sec = make_employee(roles=["security"])
    case = flow.create_case_from_event(db, event(db, make_employee()))
    db.commit()
    c = client_for(sec)
    url = f"/api/v1/cases/{case.id}/actions"
    r = c.post(url, json={"action": "assign", "assignee_id": str(other_sec.id)})
    assert r.status_code == 200 and r.json()["owner_id"] == str(other_sec.id)
    assert r.json()["status"] == "investigating"
    assert c.post(url, json={"action": "comment", "text": "looked at logs"}).status_code == 200
    r = c.post(url, json={"action": "change_severity", "severity": "critical"})
    assert r.json()["severity"] == "critical"
    ev2 = event(db, None, sid="e2")
    r = c.post(url, json={"action": "link_event", "event_id": str(ev2.id)})
    assert str(ev2.id) in r.json()["evidence_refs"]
    r = c.post(url, json={"action": "close", "rationale": "benign: approved backup"})
    assert r.json()["status"] == "closed" and r.json()["closure_rationale"]
    assert c.post(url, json={"action": "comment", "text": "late"}).status_code == 409  # closed
    r = c.post(url, json={"action": "reopen", "reason": "new evidence"})
    assert r.json()["status"] == "open" and r.json()["closure_rationale"] is None
    assert c.post(url, json={"action": "reopen", "reason": "again"}).status_code == 409
    names = [a["action"] for a in c.get(f"/api/v1/cases/{case.id}").json()["actions"]]
    assert names == ["assign", "comment", "change_severity", "link_event", "close", "reopen"]
    audited = set(db.scalars(select(AuditEvent.action).where(AuditEvent.target_id == str(case.id))))
    assert {"case.assign", "case.close", "case.reopen"} <= audited


def test_invalid_actions_rejected(client_for, db, sec, make_employee):
    case = flow.create_case_from_event(db, event(db, make_employee()))
    db.commit()
    c = client_for(sec)
    url = f"/api/v1/cases/{case.id}/actions"
    assert c.post(url, json={"action": "delete"}).status_code == 422  # not in the catalogue
    assert c.post(url, json={"action": "close"}).status_code == 422  # rationale required
    assert c.post(url, json={"action": "close", "rationale": ""}).status_code == 422
    assert c.post(url, json={"action": "change_severity", "severity": "huge"}).status_code == 422
    plain = make_employee()
    r = c.post(url, json={"action": "assign", "assignee_id": str(plain.id)})
    assert r.status_code == 422  # assignee must be security
    r = c.post(url, json={"action": "link_event", "event_id": str(uuid.uuid4())})
    assert r.status_code == 404


def test_security_user_cannot_see_case_about_themselves(client_for, db, sec):
    case = flow.create_case_from_event(db, event(db, sec))
    db.commit()
    c = client_for(sec)
    assert c.get(f"/api/v1/cases/{case.id}").status_code == 404
    assert c.get("/api/v1/cases").json() == []


def test_replayed_event_does_not_duplicate_case(db, make_employee):
    subject = make_employee()
    ev = event(db, subject)
    first = flow.create_case_from_event(db, ev)
    db.commit()
    again = flow.create_case_from_event(db, ev)
    db.commit()
    assert first.id == again.id
    assert db.scalar(select(func.count()).select_from(Case)) == 1


def test_same_type_events_group_and_escalate(db, make_employee):
    subject = make_employee()
    a = flow.create_case_from_event(db, event(db, subject, severity="low"))
    b = flow.create_case_from_event(db, event(db, subject, severity="critical"))
    db.commit()
    assert a.id == b.id and len(b.evidence_refs) == 2 and b.severity == "critical"
    other_type = flow.create_case_from_event(db, event(db, subject, etype="login.geo"))
    other_person = flow.create_case_from_event(db, event(db, make_employee()))
    db.commit()
    assert len({a.id, other_type.id, other_person.id}) == 3


def test_closed_case_is_not_reused(db, make_employee):
    subject = make_employee()
    a = flow.create_case_from_event(db, event(db, subject))
    a.status, a.closure_rationale = "closed", "done"
    db.commit()
    b = flow.create_case_from_event(db, event(db, subject))
    db.commit()
    assert a.id != b.id


def test_unresolved_identity_stays_unresolved(db):
    case = flow.create_case_from_event(db, event(db, None))
    db.commit()
    assert case.subject_employee_id is None


def test_worker_job_creates_case(db, make_employee):
    ev = event(db, make_employee())
    jobs.enqueue(db, "case.from_event", {"event_id": str(ev.id)}, idempotency_key=f"c:{ev.id}")
    db.commit()
    assert drain() == 1
    assert db.scalar(select(func.count()).select_from(Case)) == 1
    audited = db.scalars(select(AuditEvent).where(AuditEvent.action == "case.create")).all()
    assert len(audited) == 1 and audited[0].actor_id is None  # system actor


@pytest.mark.parametrize("path", ["cases", "export-requests", "offboarding-jobs"])
def test_negative_or_huge_limit_is_a_422_not_a_500(client_for, make_employee, path):
    both = make_employee(roles=["employee", "security", "it", "admin"])
    c = client_for(both)
    for bad in ("-1", "0", "501"):
        assert c.get(f"/api/v1/{path}?limit={bad}").status_code == 422
    assert c.get(f"/api/v1/{path}?limit=5").status_code == 200


def test_case_detail_shows_source_and_evidence_metadata(client_for, db, sec, make_employee):
    ev = event(db, make_employee(), source="wazuh")
    ev.event_metadata = {"rule_id": "5712"}
    ev.resource = "usb:1234"
    case = flow.create_case_from_event(db, ev)
    db.commit()
    detail = client_for(sec).get(f"/api/v1/cases/{case.id}").json()
    assert detail["source"] == "wazuh"
    (shown,) = detail["events"]
    assert shown["id"] == str(ev.id) and shown["event_type"] == "usb.mass_storage"
    assert shown["metadata"] == {"rule_id": "5712"} and shown["resource"] == "usb:1234"


def test_detail_names_subject_owner_and_actors(client_for, db, sec, make_employee):
    subject, analyst = (
        make_employee(display_name="Elena Ruiz"),
        make_employee(roles=["security"], display_name="Ben Ito"),
    )
    case = flow.create_case_from_event(db, event(db, subject))
    db.commit()
    c = client_for(sec)
    r = c.post(
        f"/api/v1/cases/{case.id}/actions",
        json={"action": "assign", "assignee_id": str(analyst.id)},
    ).json()
    assert (r["subject_name"], r["owner_name"]) == ("Elena Ruiz", "Ben Ito")
    assert r["actions"][0]["actor_name"] == sec.display_name
