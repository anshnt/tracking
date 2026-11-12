"""Security cases (PLAN.md sections 10 and 16): security role only. Mounted under /api/v1.

GET /cases, GET /cases/{id}, POST /cases/{id}/actions with a limited catalogue. Employees and
managers get 403 on every route here. Logic lives in portal.flows.cases.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from portal.authz import require_roles
from portal.db import get_db
from portal.flows import cases as flow
from portal.models import CASE_STATUS, SEVERITIES, Case, Employee

router = APIRouter(tags=["cases"])


class Assign(BaseModel):
    action: Literal["assign"]
    assignee_id: uuid.UUID


class Comment(BaseModel):
    action: Literal["comment"]
    text: str = Field(min_length=1, max_length=4000)


class ChangeSeverity(BaseModel):
    action: Literal["change_severity"]
    severity: Literal[*SEVERITIES]


class LinkEvent(BaseModel):
    action: Literal["link_event"]
    event_id: uuid.UUID


class Close(BaseModel):
    action: Literal["close"]
    rationale: str = Field(min_length=1, max_length=4000)


class Reopen(BaseModel):
    action: Literal["reopen"]
    reason: str = Field(min_length=1, max_length=4000)


CaseAction = Annotated[
    Assign | Comment | ChangeSeverity | LinkEvent | Close | Reopen, Field(discriminator="action")
]


@router.get("/cases")
def list_cases(
    status: str | None = None,
    limit: int = Query(100, ge=1, le=500),
    emp: Employee = Depends(require_roles("security")),
    db: Session = Depends(get_db),
):
    q = select(Case).order_by(Case.created_at.desc()).limit(limit)
    q = q.where(Case.subject_employee_id.is_distinct_from(emp.id))  # not your own case
    if status in CASE_STATUS:
        q = q.where(Case.status == status)
    return [flow.view(c) for c in db.scalars(q)]


@router.get("/cases/{case_id}")
def get_case(
    case_id: uuid.UUID,
    emp: Employee = Depends(require_roles("security")),
    db: Session = Depends(get_db),
):
    case = flow.get_case(db, emp, case_id)
    return flow.view(case, with_actions=True, events=flow.event_summaries(db, case))


@router.post("/cases/{case_id}/actions")
def case_action(
    case_id: uuid.UUID,
    body: Annotated[CaseAction, Body()],
    emp: Employee = Depends(require_roles("security")),
    db: Session = Depends(get_db),
):
    case = flow.get_case(db, emp, case_id, lock=True)
    flow.apply_action(db, emp, case, body.action, body.model_dump(exclude={"action"}))
    db.commit()
    return flow.view(case, with_actions=True, events=flow.event_summaries(db, case))
