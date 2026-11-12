"""Policy version admin (admin role only). Versions are immutable; activation is an assignment."""

import json
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from portal import audit
from portal.authz import require_roles
from portal.db import get_db
from portal.models import Employee, PolicyAssignment, PolicyVersion
from portal.services import work

router = APIRouter(tags=["policies"])
MAX_CONTENT_BYTES = 64 * 1024


class PolicyIn(BaseModel):
    name: str = Field(default=work.COLLECTION_POLICY, min_length=1, max_length=100)
    content: dict  # notice_text, contact, ...


class ActivateIn(BaseModel):
    scope_type: Literal["all", "employee"] = "all"
    scope_id: uuid.UUID | None = None
    activates_at: AwareDatetime | None = None
    is_exception: bool = False
    expires_at: AwareDatetime | None = None
    reviewer_id: uuid.UUID | None = None


def _version(v: PolicyVersion) -> dict:
    return {
        "id": str(v.id),
        "name": v.name,
        "version": v.version,
        "content": v.content,
        "content_hash": v.content_hash,
        "created_at": v.created_at.isoformat(),
    }


def _assignment(a: PolicyAssignment) -> dict:
    return {
        "id": str(a.id),
        "policy_version_id": str(a.policy_version_id),
        "scope_type": a.scope_type,
        "scope_id": str(a.scope_id) if a.scope_id else None,
        "activates_at": a.activates_at.isoformat(),
        "is_exception": a.is_exception,
        "expires_at": a.expires_at.isoformat() if a.expires_at else None,
        "reviewer_id": str(a.reviewer_id) if a.reviewer_id else None,
    }


@router.get("/policies")
def list_policies(admin: Employee = Depends(require_roles("admin")), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(PolicyVersion).order_by(PolicyVersion.name, PolicyVersion.version.desc())
    ).all()
    return {"policies": [_version(v) for v in rows]}


@router.post("/policies", status_code=201)
def create_policy(
    body: PolicyIn, admin: Employee = Depends(require_roles("admin")), db: Session = Depends(get_db)
):
    cats = body.content.get("categories")
    if cats is not None and not (
        isinstance(cats, list)
        and cats
        and all(
            isinstance(c, dict)
            and all(isinstance(c.get(k), str) and c[k] for k in ("signal", "default", "visible_to"))
            for c in cats
        )
    ):
        raise HTTPException(422, "categories must be a non-empty list of signal/default/visible_to")
    if len(json.dumps(body.content)) > MAX_CONTENT_BYTES:
        raise HTTPException(413, "policy content too large")
    # ponytail: max+1 can race on concurrent creates; unique(name, version) makes the loser fail.
    nxt = (
        db.scalar(select(func.max(PolicyVersion.version)).where(PolicyVersion.name == body.name))
        or 0
    ) + 1
    version = PolicyVersion(
        name=body.name,
        version=nxt,
        content=body.content,
        content_hash=work.content_hash(body.content),
    )
    db.add(version)
    db.flush()
    audit.record(
        db,
        admin,
        "policy.create",
        "policy_version",
        version.id,
        after={"name": body.name, "version": nxt, "hash": version.content_hash},
    )
    db.commit()
    return _version(version)


def _load_version(db: Session, version_id: uuid.UUID) -> PolicyVersion:
    v = db.get(PolicyVersion, version_id)
    if v is None:
        raise HTTPException(404, "not found")
    return v


@router.get("/policies/{version_id}")
def get_policy(
    version_id: uuid.UUID,
    admin: Employee = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    v = _load_version(db, version_id)
    assignments = db.scalars(
        select(PolicyAssignment)
        .where(PolicyAssignment.policy_version_id == v.id)
        .order_by(PolicyAssignment.activates_at.desc())
    ).all()
    return {**_version(v), "assignments": [_assignment(a) for a in assignments]}


@router.post("/policies/{version_id}/activate", status_code=201)
def activate_policy(
    version_id: uuid.UUID,
    body: ActivateIn,
    admin: Employee = Depends(require_roles("admin")),
    db: Session = Depends(get_db),
):
    v = _load_version(db, version_id)
    if (body.scope_type == "all") != (body.scope_id is None):
        raise HTTPException(422, "scope_id is required for employee scope and forbidden for all")
    if body.scope_type == "employee" and db.get(Employee, body.scope_id) is None:
        raise HTTPException(422, "unknown employee")
    if body.is_exception and (body.expires_at is None or body.reviewer_id is None):
        raise HTTPException(422, "an exception needs expires_at and a reviewer")
    if body.reviewer_id and db.get(Employee, body.reviewer_id) is None:
        raise HTTPException(422, "unknown reviewer")
    a = PolicyAssignment(
        policy_version_id=v.id,
        scope_type=body.scope_type,
        scope_id=body.scope_id,
        is_exception=body.is_exception,
        expires_at=body.expires_at,
        reviewer_id=body.reviewer_id,
        **({"activates_at": body.activates_at} if body.activates_at else {}),
    )
    db.add(a)
    db.flush()
    audit.record(
        db,
        admin,
        "policy.activate",
        "policy_version",
        v.id,
        after={
            "scope": body.scope_type,
            "scope_id": str(body.scope_id),
            "exception": body.is_exception,
        },
    )
    db.commit()
    return _assignment(a)
