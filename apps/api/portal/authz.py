"""Authorization. Deny by default: nothing is allowed unless a check below says so.

Route-level:   `emp: Employee = Depends(require_roles("security", "admin"))`  (any listed role)
               `emp: Employee = Depends(current_employee)`                    (any logged-in user)
Object-level:  call a check helper in the handler for every object you load/return:
               target = get_visible_employee(db, emp, employee_id)  # 404 if not allowed
               or `if not can_view_employee(emp, target): raise HTTPException(404)`
Roles are matched literally: `admin` does NOT imply any other role.
"""

import uuid

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from portal import auth
from portal.config import Settings, get_settings
from portal.db import get_db
from portal.models import Employee


def current_employee(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Employee:
    sess = auth.load_session(db, request.cookies.get(settings.session_cookie_name), settings)
    emp = db.get(Employee, sess.employee_id) if sess else None
    if emp is None or emp.status != "active":
        raise HTTPException(401, "not authenticated")
    return emp


def has_role(emp: Employee, *roles: str) -> bool:
    return any(r in emp.roles for r in roles)


def require_roles(*roles: str):
    """Dependency factory: the caller must hold at least one of `roles`."""
    if not roles:
        raise ValueError("require_roles needs at least one role (deny by default)")

    def dep(emp: Employee = Depends(current_employee)) -> Employee:
        if not has_role(emp, *roles):
            raise HTTPException(403, "forbidden")
        return emp

    return dep


def is_direct_manager(actor: Employee, target: Employee) -> bool:
    return has_role(actor, "manager") and target.manager_id == actor.id


def can_view_employee(actor: Employee, target: Employee) -> bool:
    """Self or the direct manager (manager role). Nobody else: not other managers, not admins
    (admin is for the admin CRUD endpoints; work content is disclosed to employee + manager only)."""
    return actor.id == target.id or is_direct_manager(actor, target)


def get_visible_employee(db: Session, actor: Employee, employee_id: uuid.UUID) -> Employee:
    """Load a target employee or 404 (same answer for missing and not-allowed: no existence leak)."""
    target = db.get(Employee, employee_id)
    if target is None or not can_view_employee(actor, target):
        raise HTTPException(404, "not found")
    return target


def forbid_self(actor: Employee, owner_id: uuid.UUID, what: str = "action") -> None:
    """Use for self-approval rules (e.g. export decisions): 403 if actor owns the request."""
    if actor.id == owner_id:
        raise HTTPException(403, f"cannot perform this {what} on your own request")
