"""Workspaces the caller is authorized for. Launch links carry no credentials."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from portal.authz import current_employee, get_visible_employee
from portal.db import get_db
from portal.models import Employee, Workspace
from portal.services import work

router = APIRouter(tags=["workspaces"])


@router.get("/workspaces")
def list_workspaces(
    employee_id: uuid.UUID | None = None,
    emp: Employee = Depends(current_employee),
    db: Session = Depends(get_db),
):
    """Own workspaces; a direct manager may pass employee_id for a person they can view."""
    target = get_visible_employee(db, emp, employee_id) if employee_id else emp
    rows = db.scalars(
        select(Workspace)
        .where(Workspace.owner_id == target.id, Workspace.lifecycle_state != "decommissioned")
        .order_by(Workspace.name)
    ).all()
    return {
        "workspaces": [
            {
                "id": str(w.id),
                "name": w.name,
                "role_profile": w.role_profile,
                "classification_ceiling": w.classification_ceiling,
                "lifecycle_state": w.lifecycle_state,
                "posture": work.workspace_posture(db, w),
                # only an active workspace is launchable, and only by its owner
                "launch_url": work.guacamole_launch_url(w.connection_ref)
                if w.lifecycle_state == "active" and target.id == emp.id
                else None,
            }
            for w in rows
        ]
    }
