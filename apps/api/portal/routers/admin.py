"""Admin CRUD for employees, assets and workspaces. Admin role only; every write is audited.

Status changes (offboarding) are not here: they belong to the offboarding workflow.
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from portal import audit
from portal.authz import require_roles
from portal.db import get_db
from portal.models import Asset, Employee, Workspace
from portal.services import work

router = APIRouter(prefix="/admin", tags=["admin"])

Role = Literal["employee", "manager", "it", "security", "approver", "admin"]
Classification = Literal["public", "internal", "confidential", "restricted"]
Lifecycle = Literal["requested", "active", "suspended", "decommissioned"]
Admin = Depends(require_roles("admin"))
EMAIL_RE = r"^[A-Za-z0-9][A-Za-z0-9._%+-]*@[A-Za-z0-9.-]+$"


def _apply(db: Session, admin: Employee, obj, changes: dict, action: str, kind: str) -> None:
    """Set fields, audit before/after of exactly what changed, commit once."""
    before = {k: _plain(getattr(obj, k)) for k in changes}
    for k, v in changes.items():
        setattr(obj, k, v)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "conflicts with an existing record") from None
    audit.record(db, admin, action, kind, obj.id, before=before, after=_plain(changes))
    db.commit()


def _plain(v):
    if isinstance(v, dict):
        return {k: _plain(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_plain(x) for x in v]
    return str(v) if isinstance(v, uuid.UUID) else v


def _live_owner(db: Session, owner_id) -> None:
    """Workspaces can only be created for, handed to, or activated under an active employee:
    an offboarding/offboarded owner must not regain a working workspace (PLAN s12)."""
    owner = db.get(Employee, owner_id)
    if owner is None or owner.status != "active":
        raise HTTPException(422, "workspace owner must be an active employee")


def _need(db: Session, model, ident, label: str):
    if ident is not None and db.get(model, ident) is None:
        raise HTTPException(422, f"unknown {label}")


# ---- employees ---------------------------------------------------------------------------------


class EmployeeIn(BaseModel):
    # subject and email local part become upstream usernames/URL segments: no '/', '?', '#', '..'
    oidc_subject: str = Field(
        min_length=1, max_length=255, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@-]*$"
    )
    display_name: str = Field(min_length=1, max_length=200)
    email: str = Field(min_length=3, max_length=320, pattern=EMAIL_RE)
    manager_id: uuid.UUID | None = None
    roles: list[Role] = Field(default_factory=lambda: ["employee"], min_length=1)
    timezone: str = "UTC"


class EmployeePatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    email: str | None = Field(default=None, min_length=3, max_length=320, pattern=EMAIL_RE)
    manager_id: uuid.UUID | None = None
    roles: list[Role] | None = Field(default=None, min_length=1)
    timezone: str | None = None


def _emp_view(e: Employee) -> dict:
    return {
        "id": str(e.id),
        "oidc_subject": e.oidc_subject,
        "display_name": e.display_name,
        "email": e.email,
        "manager_id": str(e.manager_id) if e.manager_id else None,
        "roles": e.roles,
        "status": e.status,
        "timezone": e.timezone,
    }


def _check_manager(db: Session, emp_id: uuid.UUID | None, manager_id: uuid.UUID | None) -> None:
    """Manager must exist and the reporting chain must not loop back to the employee."""
    if manager_id is None:
        return
    if manager_id == emp_id:
        raise HTTPException(422, "an employee cannot manage themselves")
    cur, hops = db.get(Employee, manager_id), 0
    if cur is None:
        raise HTTPException(422, "unknown manager")
    while cur and cur.manager_id and hops < 100:
        if cur.manager_id == emp_id:
            raise HTTPException(422, "that would create a reporting loop")
        cur, hops = db.get(Employee, cur.manager_id), hops + 1


@router.get("/employees")
def list_employees(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    admin: Employee = Admin,
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(Employee).order_by(Employee.display_name).limit(limit).offset(offset))
    return {"employees": [_emp_view(e) for e in rows]}


@router.get("/employees/{emp_id}")
def get_employee(emp_id: uuid.UUID, admin: Employee = Admin, db: Session = Depends(get_db)):
    e = db.get(Employee, emp_id)
    if e is None:
        raise HTTPException(404, "not found")
    return _emp_view(e)


@router.post("/employees", status_code=201)
def create_employee(body: EmployeeIn, admin: Employee = Admin, db: Session = Depends(get_db)):
    if not work.valid_timezone(body.timezone):
        raise HTTPException(422, "unknown timezone")
    _check_manager(db, None, body.manager_id)
    e = Employee(
        oidc_subject=body.oidc_subject,
        display_name=body.display_name,
        email=body.email,
        manager_id=body.manager_id,
        roles=sorted(set(body.roles)),
        timezone=body.timezone,
    )
    db.add(e)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "oidc_subject or email already exists") from None
    audit.record(db, admin, "employee.create", "employee", e.id, after=_emp_view(e))
    db.commit()
    return _emp_view(e)


@router.patch("/employees/{emp_id}")
def update_employee(
    emp_id: uuid.UUID, body: EmployeePatch, admin: Employee = Admin, db: Session = Depends(get_db)
):
    e = db.get(Employee, emp_id)
    if e is None:
        raise HTTPException(404, "not found")
    changes = body.model_dump(exclude_unset=True)
    if "roles" in changes:
        if e.id == admin.id:
            raise HTTPException(403, "you cannot change your own roles")
        changes["roles"] = sorted(set(changes["roles"]))
    if "timezone" in changes and not work.valid_timezone(changes["timezone"] or ""):
        raise HTTPException(422, "unknown timezone")
    for required in ("display_name", "email", "roles", "timezone"):
        if required in changes and changes[required] is None:
            raise HTTPException(422, f"{required} cannot be null")
    if "manager_id" in changes:
        _check_manager(db, e.id, changes["manager_id"])
    _apply(db, admin, e, changes, "employee.update", "employee")
    return _emp_view(e)


# ---- assets ------------------------------------------------------------------------------------


class AssetIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    ownership: Literal["company", "personal"]
    assigned_employee_id: uuid.UUID | None = None
    os: str | None = Field(default=None, max_length=100)
    upstream_ids: dict = Field(default_factory=dict)
    restricted: dict = Field(default_factory=dict)


class AssetPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    ownership: Literal["company", "personal"] | None = None
    assigned_employee_id: uuid.UUID | None = None
    os: str | None = Field(default=None, max_length=100)
    upstream_ids: dict | None = None
    restricted: dict | None = None


def _asset_view(a: Asset) -> dict:
    return {
        "id": str(a.id),
        "name": a.name,
        "ownership": a.ownership,
        "assigned_employee_id": str(a.assigned_employee_id) if a.assigned_employee_id else None,
        "os": a.os,
        "upstream_ids": a.upstream_ids,
        "restricted": a.restricted,
    }


def _check_ownership(ownership: str, restricted: dict) -> None:
    # Serials and similar fields exist for company equipment only (PLAN.md section 3).
    if ownership == "personal" and restricted:
        raise HTTPException(422, "restricted fields are for company equipment only")


@router.get("/assets")
def list_assets(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    admin: Employee = Admin,
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(Asset).order_by(Asset.name).limit(limit).offset(offset))
    return {"assets": [_asset_view(a) for a in rows]}


@router.post("/assets", status_code=201)
def create_asset(body: AssetIn, admin: Employee = Admin, db: Session = Depends(get_db)):
    _check_ownership(body.ownership, body.restricted)
    _need(db, Employee, body.assigned_employee_id, "employee")
    a = Asset(**body.model_dump())
    db.add(a)
    db.flush()
    audit.record(db, admin, "asset.create", "asset", a.id, after=_plain(_asset_view(a)))
    db.commit()
    return _asset_view(a)


@router.patch("/assets/{asset_id}")
def update_asset(
    asset_id: uuid.UUID, body: AssetPatch, admin: Employee = Admin, db: Session = Depends(get_db)
):
    a = db.get(Asset, asset_id)
    if a is None:
        raise HTTPException(404, "not found")
    changes = body.model_dump(exclude_unset=True)
    for required in ("name", "ownership", "upstream_ids", "restricted"):
        if required in changes and changes[required] is None:
            raise HTTPException(422, f"{required} cannot be null")
    _check_ownership(changes.get("ownership", a.ownership), changes.get("restricted", a.restricted))
    _need(db, Employee, changes.get("assigned_employee_id"), "employee")
    _apply(db, admin, a, changes, "asset.update", "asset")
    return _asset_view(a)


# ---- workspaces --------------------------------------------------------------------------------


class WorkspaceIn(BaseModel):
    owner_id: uuid.UUID
    name: str = Field(min_length=1, max_length=200)
    role_profile: str = Field(min_length=1, max_length=100)
    classification_ceiling: Classification = "internal"
    connection_ref: str | None = Field(default=None, max_length=200)
    asset_id: uuid.UUID | None = None
    lifecycle_state: Lifecycle = "requested"


class WorkspacePatch(BaseModel):
    owner_id: uuid.UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=200)
    role_profile: str | None = Field(default=None, min_length=1, max_length=100)
    classification_ceiling: Classification | None = None
    connection_ref: str | None = Field(default=None, max_length=200)
    asset_id: uuid.UUID | None = None
    lifecycle_state: Lifecycle | None = None


def _ws_view(w: Workspace) -> dict:
    return {
        "id": str(w.id),
        "owner_id": str(w.owner_id),
        "name": w.name,
        "role_profile": w.role_profile,
        "classification_ceiling": w.classification_ceiling,
        "connection_ref": w.connection_ref,
        "asset_id": str(w.asset_id) if w.asset_id else None,
        "lifecycle_state": w.lifecycle_state,
    }


@router.get("/workspaces")
def list_workspaces(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    admin: Employee = Admin,
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(Workspace).order_by(Workspace.name).limit(limit).offset(offset))
    return {"workspaces": [_ws_view(w) for w in rows]}


@router.post("/workspaces", status_code=201)
def create_workspace(body: WorkspaceIn, admin: Employee = Admin, db: Session = Depends(get_db)):
    _need(db, Employee, body.owner_id, "owner")
    _live_owner(db, body.owner_id)
    _need(db, Asset, body.asset_id, "asset")
    w = Workspace(**body.model_dump())
    db.add(w)
    db.flush()
    audit.record(db, admin, "workspace.create", "workspace", w.id, after=_plain(_ws_view(w)))
    db.commit()
    return _ws_view(w)


@router.patch("/workspaces/{ws_id}")
def update_workspace(
    ws_id: uuid.UUID, body: WorkspacePatch, admin: Employee = Admin, db: Session = Depends(get_db)
):
    w = db.get(Workspace, ws_id)
    if w is None:
        raise HTTPException(404, "not found")
    changes = body.model_dump(exclude_unset=True)
    for required in (
        "owner_id",
        "name",
        "role_profile",
        "classification_ceiling",
        "lifecycle_state",
    ):
        if required in changes and changes[required] is None:
            raise HTTPException(422, f"{required} cannot be null")
    _need(db, Employee, changes.get("owner_id"), "owner")
    if "owner_id" in changes or changes.get("lifecycle_state") in ("requested", "active"):
        _live_owner(db, changes.get("owner_id") or w.owner_id)
    _need(db, Asset, changes.get("asset_id"), "asset")
    _apply(db, admin, w, changes, "workspace.update", "workspace")
    return _ws_view(w)
