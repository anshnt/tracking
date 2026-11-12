import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from portal.models import AuditEvent, PolicyVersion
from portal.services.work import content_hash

NOBODY = "00000000-0000-0000-0000-000000000001"


def test_admin_only(make_employee, client_for):
    for roles in (["employee"], ["manager"], ["security"]):
        c = client_for(make_employee(roles=roles))
        assert c.get("/api/v1/policies").status_code == 403
        assert c.post("/api/v1/policies", json={"content": {}}).status_code == 403


def test_create_version_hash_activate_audit(db, make_employee, client_for):
    admin, emp = make_employee(roles=["admin"]), make_employee()
    c = client_for(admin)
    content = {"notice_text": "a", "contact": "x"}
    v1 = c.post("/api/v1/policies", json={"content": content}).json()
    v2 = c.post("/api/v1/policies", json={"content": {"notice_text": "b"}}).json()
    assert (v1["version"], v2["version"]) == (1, 2)
    assert v1["content_hash"] == content_hash(content)
    assert c.post(f"/api/v1/policies/{v1['id']}/activate", json={}).status_code == 201
    got = client_for(emp).get("/api/v1/me/collection-policy").json()["policy"]
    assert got["version"] == 1
    assert c.post(f"/api/v1/policies/{v2['id']}/activate", json={}).status_code == 201
    got = client_for(emp).get("/api/v1/me/collection-policy").json()["policy"]
    assert got["version"] == 2
    assert len(c.get(f"/api/v1/policies/{v2['id']}").json()["assignments"]) == 1
    actions = [a.action for a in db.scalars(select(AuditEvent))]
    assert actions.count("policy.create") == 2 and actions.count("policy.activate") == 2


def test_versions_are_immutable(db, make_employee, client_for):
    c = client_for(make_employee(roles=["admin"]))
    v = c.post("/api/v1/policies", json={"content": {"a": 1}}).json()
    row = db.get(PolicyVersion, v["id"])
    row.content = {"a": 2}
    with pytest.raises(DBAPIError):
        db.commit()
    db.rollback()


def test_activation_validation(make_employee, client_for):
    c = client_for(make_employee(roles=["admin"]))
    v = c.post("/api/v1/policies", json={"content": {}}).json()
    url = f"/api/v1/policies/{v['id']}/activate"
    assert c.post(url, json={"scope_type": "employee"}).status_code == 422
    assert c.post(url, json={"scope_type": "employee", "scope_id": NOBODY}).status_code == 422
    assert c.post(url, json={"is_exception": True}).status_code == 422  # needs expiry, reviewer
    assert c.post(f"/api/v1/policies/{NOBODY}/activate", json={}).status_code == 404


def test_naive_datetimes_are_rejected(make_employee, client_for):
    c = client_for(make_employee(roles=["admin"]))
    v = c.post("/api/v1/policies", json={"content": {"notice_text": "n"}}).json()
    url = f"/api/v1/policies/{v['id']}/activate"
    assert c.post(url, json={"activates_at": "2026-01-01T09:00:00"}).status_code == 422
    assert c.post(url, json={"activates_at": "2026-01-01T09:00:00+00:00"}).status_code == 201
