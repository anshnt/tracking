from sqlalchemy import select

from portal.models import Asset, AuditEvent, Employee

NOBODY = "00000000-0000-0000-0000-000000000001"
EMP = {"oidc_subject": "kc-1", "display_name": "New Person", "email": "new@example.invalid"}


def _actions(db):
    return [a.action for a in db.scalars(select(AuditEvent).order_by(AuditEvent.id))]


def test_admin_required_everywhere(make_employee, client_for):
    c = client_for(make_employee(roles=["manager", "it", "security", "approver"]))
    for path in ("employees", "assets", "workspaces"):
        assert c.get(f"/api/v1/admin/{path}").status_code == 403
    assert c.post("/api/v1/admin/employees", json=EMP).status_code == 403
    assert (
        c.patch(f"/api/v1/admin/employees/{NOBODY}", json={"display_name": "x"}).status_code == 403
    )


def test_employee_crud_audited(db, make_employee, client_for):
    admin, mgr = make_employee(roles=["admin"]), make_employee(roles=["manager"])
    c = client_for(admin)
    r = c.post(
        "/api/v1/admin/employees",
        json={**EMP, "manager_id": str(mgr.id), "roles": ["employee", "employee"]},
    )
    assert r.status_code == 201 and r.json()["roles"] == ["employee"]
    eid = r.json()["id"]
    assert c.post("/api/v1/admin/employees", json=EMP).status_code == 409  # same oidc_subject
    p = c.patch(
        f"/api/v1/admin/employees/{eid}",
        json={"roles": ["employee", "approver"], "manager_id": None},
    )
    assert p.status_code == 200 and p.json()["manager_id"] is None
    assert c.get(f"/api/v1/admin/employees/{eid}").json()["roles"] == ["approver", "employee"]
    assert _actions(db) == ["employee.create", "employee.update"]
    assert len(c.get("/api/v1/admin/employees").json()["employees"]) == 3


def test_employee_validation(db, make_employee, client_for):
    admin = make_employee(roles=["admin"])
    c = client_for(admin)
    assert c.post("/api/v1/admin/employees", json={**EMP, "roles": ["root"]}).status_code == 422
    assert (
        c.post("/api/v1/admin/employees", json={**EMP, "timezone": "Mars/Base"}).status_code == 422
    )
    assert c.post("/api/v1/admin/employees", json={**EMP, "manager_id": NOBODY}).status_code == 422
    assert (
        c.patch(f"/api/v1/admin/employees/{admin.id}", json={"roles": ["employee"]}).status_code
        == 403
    )
    assert (
        c.patch(
            f"/api/v1/admin/employees/{admin.id}", json={"manager_id": str(admin.id)}
        ).status_code
        == 422
    )
    a, b = make_employee(), make_employee()
    assert (
        c.patch(f"/api/v1/admin/employees/{a.id}", json={"manager_id": str(b.id)}).status_code
        == 200
    )
    assert (
        c.patch(f"/api/v1/admin/employees/{b.id}", json={"manager_id": str(a.id)}).status_code
        == 422
    )  # loop
    assert (
        c.patch(f"/api/v1/admin/employees/{a.id}", json={"display_name": None}).status_code == 422
    )
    assert (
        c.patch(f"/api/v1/admin/employees/{NOBODY}", json={"display_name": "x"}).status_code == 404
    )
    # status and subject are not patchable
    c.patch(f"/api/v1/admin/employees/{a.id}", json={"status": "offboarded", "oidc_subject": "x"})
    db.refresh(a)
    assert a.status == "active" and a.oidc_subject != "x"


def test_asset_crud_and_ownership_rule(db, make_employee, client_for):
    admin, emp = make_employee(roles=["admin"]), make_employee()
    c = client_for(admin)
    body = {
        "name": "laptop",
        "ownership": "company",
        "assigned_employee_id": str(emp.id),
        "restricted": {"serial": "S1"},
    }
    r = c.post("/api/v1/admin/assets", json=body)
    assert r.status_code == 201
    aid = r.json()["id"]
    byod = {"name": "mine", "ownership": "personal", "restricted": {"serial": "S2"}}
    assert c.post("/api/v1/admin/assets", json=byod).status_code == 422
    assert c.patch(f"/api/v1/admin/assets/{aid}", json={"ownership": "personal"}).status_code == 422
    assert (
        c.patch(
            f"/api/v1/admin/assets/{aid}", json={"ownership": "personal", "restricted": {}}
        ).status_code
        == 200
    )
    assert (
        c.patch(f"/api/v1/admin/assets/{aid}", json={"assigned_employee_id": NOBODY}).status_code
        == 422
    )
    assert db.get(Asset, aid).ownership == "personal"
    assert _actions(db) == ["asset.create", "asset.update"]


def test_workspace_crud(db, make_employee, client_for):
    admin, emp = make_employee(roles=["admin"]), make_employee()
    c = client_for(admin)
    body = {"owner_id": str(emp.id), "name": "dev box", "role_profile": "dev"}
    r = c.post("/api/v1/admin/workspaces", json=body)
    assert r.status_code == 201 and r.json()["lifecycle_state"] == "requested"
    wid = r.json()["id"]
    assert (
        c.patch(
            f"/api/v1/admin/workspaces/{wid}",
            json={"lifecycle_state": "active", "connection_ref": "7"},
        ).json()["lifecycle_state"]
        == "active"
    )
    assert (
        c.patch(f"/api/v1/admin/workspaces/{wid}", json={"lifecycle_state": "bogus"}).status_code
        == 422
    )
    assert c.post("/api/v1/admin/workspaces", json={**body, "owner_id": NOBODY}).status_code == 422
    assert c.patch(f"/api/v1/admin/workspaces/{NOBODY}", json={"name": "x"}).status_code == 404
    assert [w["name"] for w in c.get("/api/v1/admin/workspaces").json()["workspaces"]] == [
        "dev box"
    ]
    assert _actions(db) == ["workspace.create", "workspace.update"]
    assert db.scalar(select(Employee).where(Employee.id == emp.id))


def test_workspace_needs_an_active_owner(db, make_employee, client_for):
    admin = make_employee(roles=["admin"])
    gone = make_employee(status="offboarded")
    live = make_employee()
    c = client_for(admin)
    body = {"owner_id": str(gone.id), "name": "box", "role_profile": "dev"}
    assert c.post("/api/v1/admin/workspaces", json=body).status_code == 422
    wid = c.post("/api/v1/admin/workspaces", json={**body, "owner_id": str(live.id)}).json()["id"]
    live.status = "offboarding"
    db.commit()
    url = f"/api/v1/admin/workspaces/{wid}"
    assert c.patch(url, json={"lifecycle_state": "active"}).status_code == 422
    assert c.patch(url, json={"owner_id": str(gone.id)}).status_code == 422
    assert c.patch(url, json={"lifecycle_state": "suspended"}).status_code == 200
