"""Manager overview (PLAN.md section 8). Facts per person; no score, percentage or ranking."""

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from portal.authz import require_roles
from portal.db import get_db
from portal.models import Employee
from portal.services import work

router = APIRouter(tags=["overview"])


@router.get("/overview")
def overview(mgr: Employee = Depends(require_roles("manager")), db: Session = Depends(get_db)):
    """Managers see their direct reports only (admins get no work-content access)."""
    q = select(Employee).where(Employee.status == "active", Employee.manager_id == mgr.id)
    # ponytail: no paging; a handful of reports per manager. Add limit/offset past ~100 people.
    people = db.scalars(q).all()
    return {"people": work.overview_for(db, people)}
