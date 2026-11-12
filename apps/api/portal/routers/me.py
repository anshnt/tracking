"""Current user: profile, collection notice, own records, own tasks (PLAN.md sections 8-9)."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from portal import audit
from portal.authz import current_employee
from portal.db import get_db
from portal.models import (
    Asset,
    Employee,
    ExportRequest,
    NoticeAcknowledgement,
    PolicyVersion,
    PostureObservation,
    SecurityEvent,
    TaskSnapshot,
    WorkUpdate,
)
from portal.services import work

router = APIRouter(tags=["me"])


@router.get("/me")
def me(emp: Employee = Depends(current_employee)):
    return {
        "id": str(emp.id),
        "display_name": emp.display_name,
        "email": emp.email,
        "roles": emp.roles,
        "status": emp.status,
        "timezone": emp.timezone,
        "manager_id": str(emp.manager_id) if emp.manager_id else None,
    }


def _ack_for(db: Session, emp: Employee, version_id: uuid.UUID) -> NoticeAcknowledgement | None:
    return db.scalars(
        select(NoticeAcknowledgement)
        .where(
            NoticeAcknowledgement.employee_id == emp.id,
            NoticeAcknowledgement.policy_version_id == version_id,
        )
        .limit(1)
    ).first()


@router.get("/me/collection-policy")
def collection_policy(emp: Employee = Depends(current_employee), db: Session = Depends(get_db)):
    found = work.active_policy(db, emp)
    policy = None
    categories = work.COLLECTION_CATEGORIES
    if found:
        version, assignment = found
        # what is collected comes from the version in force, so a new version or an
        # employee-scoped exception that changes categories reaches the employee
        categories = version.content.get("categories") or categories
        ack = _ack_for(db, emp, version.id)
        policy = {
            "id": str(version.id),
            "name": version.name,
            "version": version.version,
            "content_hash": version.content_hash,
            "notice_text": version.content.get("notice_text"),
            "contact": version.content.get("contact"),
            "activates_at": assignment.activates_at.isoformat(),
            "is_exception": assignment.is_exception,
            "expires_at": assignment.expires_at.isoformat() if assignment.expires_at else None,
            "acknowledged_at": ack.acknowledged_at.isoformat() if ack else None,
        }
    return {"policy": policy, "categories": categories}


class AckIn(BaseModel):
    policy_version_id: uuid.UUID


@router.post("/me/notice-acknowledgements", status_code=201)
def acknowledge(
    body: AckIn, emp: Employee = Depends(current_employee), db: Session = Depends(get_db)
):
    found = work.active_policy(db, emp)
    # Only the notice that currently applies to you can be acknowledged.
    if not found or found[0].id != body.policy_version_id:
        raise HTTPException(409, "that is not the notice currently in force for you")
    # idempotent under double submits: the unique (employee, version) row decides, not a read
    inserted = db.scalar(
        pg_insert(NoticeAcknowledgement)
        .values(employee_id=emp.id, policy_version_id=body.policy_version_id)
        .on_conflict_do_nothing()
        .returning(NoticeAcknowledgement.id)
    )
    if inserted:
        audit.record(db, emp, "notice.acknowledge", "policy_version", body.policy_version_id)
    db.commit()
    ack = _ack_for(db, emp, body.policy_version_id)
    return {
        "policy_version_id": str(ack.policy_version_id),
        "acknowledged_at": ack.acknowledged_at.isoformat(),
    }


@router.get("/me/records")
def my_records(
    limit: int = Query(100, ge=1, le=200),
    emp: Employee = Depends(current_employee),
    db: Session = Depends(get_db),
):
    """Everything the portal holds about the caller, and nothing about anyone else."""
    updates = db.scalars(
        select(WorkUpdate)
        .where(WorkUpdate.employee_id == emp.id)
        .order_by(WorkUpdate.update_date.desc())
        .limit(limit)
    ).all()
    # Posture exists only for company devices; personal devices are never observed.
    posture = db.scalars(
        select(PostureObservation)
        .join(Asset, Asset.id == PostureObservation.asset_id)
        .where(Asset.assigned_employee_id == emp.id, Asset.ownership == "company")
        .order_by(PostureObservation.observed_at.desc())
        .limit(limit)
    ).all()
    events = db.scalars(
        select(SecurityEvent)
        .where(SecurityEvent.employee_id == emp.id)
        .order_by(SecurityEvent.occurred_at.desc())
        .limit(limit)
    ).all()
    exports = db.scalars(
        select(ExportRequest)
        .where(ExportRequest.requester_id == emp.id)
        .order_by(ExportRequest.created_at.desc())
        .limit(limit)
    ).all()
    acks = db.execute(
        select(NoticeAcknowledgement, PolicyVersion)
        .join(PolicyVersion, PolicyVersion.id == NoticeAcknowledgement.policy_version_id)
        .where(NoticeAcknowledgement.employee_id == emp.id)
        .order_by(NoticeAcknowledgement.acknowledged_at.desc())
    ).all()
    return {
        "work_updates": [
            {
                "id": str(u.id),
                "update_date": u.update_date.isoformat(),
                "summary": u.summary,
                "blocker": u.blocker,
                "corrections": len(u.corrections),
                "updated_at": u.updated_at.isoformat(),
            }
            for u in updates
        ],
        "posture_observations": [
            {
                "asset_id": str(o.asset_id),
                "source": o.source,
                "observed_at": o.observed_at.isoformat(),
                "state": o.state,
                "failing_checks": work.failing_checks(o.checks),
            }
            for o in posture
        ],
        "security_event_summaries": [
            {
                "id": str(e.id),
                "source": e.source,
                "event_type": e.event_type,
                "severity": e.severity,
                "occurred_at": e.occurred_at.isoformat(),
                "classification": e.classification,
            }
            for e in events
        ],
        "export_requests": [
            {
                "id": str(x.id),
                "object_ref": x.object_ref,
                "recipient": x.recipient,
                "purpose": x.purpose,
                "classification": x.classification,
                "status": x.status,
                "expires_at": x.expires_at.isoformat() if x.expires_at else None,
                "created_at": x.created_at.isoformat(),
            }
            for x in exports
        ],
        "notice_acknowledgements": [
            {
                "policy": v.name,
                "version": v.version,
                "acknowledged_at": a.acknowledged_at.isoformat(),
            }
            for a, v in acks
        ],
    }


@router.get("/me/tasks")
def my_tasks(emp: Employee = Depends(current_employee), db: Session = Depends(get_db)):
    tasks = db.scalars(
        select(TaskSnapshot)
        .where(TaskSnapshot.assignee_id == emp.id, TaskSnapshot.state != "done")
        .order_by(TaskSnapshot.due_date.asc().nulls_last(), TaskSnapshot.title)
    ).all()
    return {"tasks": [work.task_view(t) for t in tasks]}
