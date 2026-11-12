"""Security cases: creation from events (worker) and the limited action catalogue.

Visibility: the `security` role only. Employees and managers never see cases. A security user
who is the subject of a case is treated as not allowed (404) to avoid self-investigation.
"""

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from portal import audit
from portal.jobs import job_handler
from portal.models import SEVERITIES, Case, CaseAction, Employee, SecurityEvent

ACTIONS = ("assign", "comment", "change_severity", "link_event", "close", "reopen")


def create_case_from_event(db: Session, event: SecurityEvent) -> Case:
    """Idempotent. A replayed event returns its case; a same-type event for the same subject
    joins the still-open case instead of duplicating it. Does not commit."""
    eid = str(event.id)
    existing = db.scalars(select(Case).where(Case.evidence_refs.contains([eid]))).first()
    if existing:
        return existing
    title = f"{event.event_type} ({event.source})"
    # unattributed events (no subject) are never grouped: unrelated sources must not merge
    open_case = (
        db.scalars(
            select(Case)
            .where(
                Case.title == title,
                Case.subject_employee_id == event.employee_id,
                Case.status != "closed",
            )
            .order_by(Case.created_at)
            .limit(1)
            .with_for_update()
        ).first()
        if event.employee_id is not None
        else None
    )
    # ponytail: two workers racing on a brand-new subject can still make two cases;
    # add a partial unique index on (subject, title) where open if that ever shows up.
    if open_case:
        open_case.evidence_refs = [*open_case.evidence_refs, eid]
        if SEVERITIES.index(event.severity) > SEVERITIES.index(open_case.severity):
            open_case.severity = event.severity
        audit.record(
            db,
            None,
            "case.link_event",
            "case",
            open_case.id,
            reason="auto-grouped",
            after={"event_id": eid},
        )
        return open_case
    case = Case(
        subject_employee_id=event.employee_id,
        title=title,
        reason=f"Opened from security event {eid}",
        severity=event.severity if event.severity != "info" else "low",
        evidence_refs=[eid],
    )
    db.add(case)
    db.flush()
    audit.record(
        db,
        None,
        "case.create",
        "case",
        case.id,
        reason=case.reason,
        after={"severity": case.severity, "event_id": eid},
    )
    return case


@job_handler("case.from_event")
def _case_job(db: Session, job) -> None:
    event = db.get(SecurityEvent, uuid.UUID(job.payload["event_id"]))
    if event is not None:
        create_case_from_event(db, event)


def case_visible(actor: Employee, case: Case) -> bool:
    return case.subject_employee_id != actor.id


def get_case(db: Session, actor: Employee, case_id: uuid.UUID, lock: bool = False) -> Case:
    q = select(Case).where(Case.id == case_id)
    case = db.scalars(q.with_for_update() if lock else q).first()
    if case is None or not case_visible(actor, case):
        raise HTTPException(404, "not found")
    return case


def event_summaries(db: Session, case: Case) -> list[dict]:
    """The evidence behind a case, oldest first. Metadata is already allowlisted at ingest."""
    ids = []
    for ref in case.evidence_refs:
        try:
            ids.append(uuid.UUID(ref))
        except ValueError:
            continue
    rows = db.scalars(
        select(SecurityEvent).where(SecurityEvent.id.in_(ids)).order_by(SecurityEvent.occurred_at)
    )
    return [
        {
            "id": str(e.id),
            "source": e.source,
            "event_type": e.event_type,
            "severity": e.severity,
            "occurred_at": e.occurred_at,
            "actor": e.actor,
            "resource": e.resource,
            "classification": e.classification,
            "metadata": e.event_metadata,
        }
        for e in rows
    ]


def _names(case: Case, with_actions: bool) -> dict:
    ids = {case.owner_id, case.subject_employee_id}
    if with_actions:
        ids |= {a.actor_id for a in case.actions}
    ids.discard(None)
    db = object_session(case)
    if not ids or db is None:
        return {}
    rows = db.execute(select(Employee.id, Employee.display_name).where(Employee.id.in_(ids)))
    return {i: n for i, n in rows}


def view(case: Case, with_actions: bool = False, events: list[dict] | None = None) -> dict:
    names = _names(case, with_actions)
    out = {
        "id": str(case.id),
        "title": case.title,
        "reason": case.reason,
        "severity": case.severity,
        "status": case.status,
        "owner_id": str(case.owner_id) if case.owner_id else None,
        "owner_name": names.get(case.owner_id),
        "subject_employee_id": str(case.subject_employee_id) if case.subject_employee_id else None,
        "subject_name": names.get(case.subject_employee_id),
        "evidence_refs": case.evidence_refs,
        "closure_rationale": case.closure_rationale,
        "created_at": case.created_at,
        "updated_at": case.updated_at,
        "closed_at": case.closed_at,
    }
    if events is not None:
        out["events"] = events
        out["source"] = events[0]["source"] if events else None
    if with_actions:
        out["actions"] = [
            {
                "id": str(a.id),
                "actor_id": str(a.actor_id),
                "actor_name": names.get(a.actor_id),
                "action": a.action,
                "detail": a.detail,
                "created_at": a.created_at,
            }
            for a in case.actions
        ]
    return out


def apply_action(db: Session, actor: Employee, case: Case, action: str, data: dict) -> Case:
    """`data` is already shape-validated by the router. Does not commit."""
    before = {"status": case.status, "severity": case.severity, "owner_id": str(case.owner_id)}
    if action == "reopen":
        if case.status != "closed":
            raise HTTPException(409, "only a closed case can be reopened")
        case.status, case.closure_rationale, case.closed_at = "open", None, None
    elif case.status == "closed":
        raise HTTPException(409, "case is closed; reopen it first")
    elif action == "assign":
        assignee = db.get(Employee, data["assignee_id"])
        if assignee is None or assignee.status != "active" or "security" not in assignee.roles:
            raise HTTPException(422, "assignee must be an active security user")
        case.owner_id = assignee.id
        if case.status == "open":
            case.status = "investigating"
    elif action == "change_severity":
        case.severity = data["severity"]
    elif action == "link_event":
        event = db.get(SecurityEvent, data["event_id"])
        if event is None:
            raise HTTPException(404, "event not found")
        if str(event.id) not in case.evidence_refs:
            case.evidence_refs = [*case.evidence_refs, str(event.id)]
    elif action == "close":
        case.status, case.closure_rationale, case.closed_at = (
            "closed",
            data["rationale"],
            datetime.now(UTC),
        )
    # comment: no state change
    detail = {k: str(v) for k, v in data.items()}
    db.add(CaseAction(case_id=case.id, actor_id=actor.id, action=action, detail=detail))
    db.flush()
    db.refresh(case)
    audit.record(
        db,
        actor,
        f"case.{action}",
        "case",
        case.id,
        reason=detail.get("rationale") or detail.get("reason"),
        before=before,
        after={"status": case.status, "severity": case.severity, "owner_id": str(case.owner_id)},
    )
    return case
