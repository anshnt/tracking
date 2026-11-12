"""Retention (PLAN.md section 9, "Proposed retention defaults").

apply_retention()    deletes expired rows per retention_rules, skips anything under a legal hold,
                     and writes a deletion_tombstone (identifiers only) for every deleted row.
reapply_tombstones() after a backup restore: delete again whatever the tombstones say is gone.
seed_default_rules() inserts the section 9 defaults if a rule is missing (never overwrites).

Data class -> what it covers:
  raw-activity-30d   security_events with retention_policy 'raw-activity-30d' (optional raw work activity)
  security-90d       security_events with retention_policy 'security-90d'; posture_observations
  approvals-180d     export_requests in a final state (rejected, released, expired) and their decisions
  work-summary-365d  work_updates (and their corrections), by update_date

Legal holds: a hold is active while released_at IS NULL. A hold with an employee_id protects that
employee's rows (events by employee_id, work updates by employee, exports by requester). A hold
without an employee_id is global and pauses ALL deletion (conservative: a scope string is not parsed).
Posture observations are not employee-keyed, so they are protected only by a global hold.

AUDIT EVENTS ARE NOT DELETED HERE (see scripts/expire_audit_events.sql, run by the owner role). audit_events is append-only (trigger rejects DELETE) and the
app role must not be able to remove it. Expiry of audit rows (default 180 days, approvals and
privileged actions) is a manual maintenance step run by the database owner role, outside the app:
disable the trigger for one transaction, delete rows older than the rule, re-enable, and record
the run in the change log. Do not grant the app role that privilege.
"""

import sys
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from portal import audit
from portal.models import (
    Case,
    DeletionTombstone,
    ExportDecision,
    ExportRequest,
    LegalHold,
    PostureObservation,
    RetentionRule,
    SecurityEvent,
    WorkUpdate,
    WorkUpdateCorrection,
)

DEFAULT_RULES = {
    "raw-activity-30d": (30, "Optional raw work-activity events"),
    "security-90d": (90, "Security and session metadata"),
    "approvals-180d": (180, "Approval and privileged-action records"),
    "work-summary-365d": (365, "Work summaries"),
}
BATCH = 1000
FINAL_EXPORT_STATES = ("rejected", "released", "expired", "cancelled")


@dataclass
class RetentionResult:
    deleted: dict[str, int] = field(default_factory=dict)
    paused_by_hold: bool = False

    def add(self, subject_type: str, n: int) -> None:
        if n:
            self.deleted[subject_type] = self.deleted.get(subject_type, 0) + n


def seed_default_rules(db: Session) -> None:
    for data_class, (days, description) in DEFAULT_RULES.items():
        db.execute(
            insert(RetentionRule)
            .values(data_class=data_class, retention_days=days, description=description)
            .on_conflict_do_nothing(index_elements=["data_class"])
        )
    db.flush()


def _holds(db: Session) -> tuple[bool, set]:
    rows = db.execute(select(LegalHold.employee_id).where(LegalHold.released_at.is_(None))).all()
    return any(r[0] is None for r in rows), {r[0] for r in rows if r[0] is not None}


def _purge(db, model, id_col, where, subject_type, rule, result, extra_delete=None) -> None:
    """Delete matching rows in batches, tombstoning each id first (same transaction)."""
    while True:
        ids = db.scalars(select(id_col).where(*where).limit(BATCH)).all()
        if not ids:
            return
        db.execute(
            insert(DeletionTombstone)
            .values(
                [{"subject_type": subject_type, "subject_id": str(i), "rule": rule} for i in ids]
            )
            .on_conflict_do_nothing(index_elements=["subject_type", "subject_id"])
        )
        if extra_delete:
            extra_delete(ids)
        db.execute(delete(model).where(id_col.in_(ids)))
        result.add(subject_type, len(ids))


def _open_case_evidence(db: Session) -> list[uuid.UUID]:
    refs: set[uuid.UUID] = set()
    for lst in db.scalars(select(Case.evidence_refs).where(Case.status != "closed")):
        for r in lst or []:
            try:
                refs.add(uuid.UUID(str(r)))
            except ValueError:
                continue
    return list(refs)


def _drop_export_children(db: Session, ids) -> None:
    from portal.flows.exports import _remove_staged  # lazy: flows import the db layer

    for req in db.scalars(select(ExportRequest).where(ExportRequest.id.in_(ids))):
        _remove_staged(req)  # a released row may still have a copy in the release area
    db.execute(delete(ExportDecision).where(ExportDecision.export_request_id.in_(ids)))


def apply_retention(db: Session, now: datetime | None = None) -> RetentionResult:
    """Run every rule. Commits once at the end (or rolls back on error) and audits the run."""
    now = now or datetime.now(UTC)
    result = RetentionResult()
    seed_default_rules(db)
    global_hold, held = _holds(db)
    if global_hold:
        result.paused_by_hold = True
        audit.record(db, None, "retention.skipped", "retention", None, reason="global legal hold")
        db.commit()
        return result
    rules = {r.data_class: r.retention_days for r in db.scalars(select(RetentionRule))}
    try:
        for data_class, days in rules.items():
            cutoff = now - timedelta(days=days)
            if data_class in ("raw-activity-30d", "security-90d"):
                where = [
                    SecurityEvent.retention_policy == data_class,
                    SecurityEvent.occurred_at < cutoff,
                ]
                if held:
                    where.append(
                        SecurityEvent.employee_id.is_(None)
                        | SecurityEvent.employee_id.not_in(list(held))
                    )
                if data_class == "security-90d":
                    # evidence of a case that is still open must outlive the 90-day window
                    open_refs = _open_case_evidence(db)
                    if open_refs:
                        where.append(SecurityEvent.id.not_in(open_refs))
                _purge(
                    db, SecurityEvent, SecurityEvent.id, where, "security_event", data_class, result
                )
            if data_class == "security-90d":
                _purge(
                    db,
                    PostureObservation,
                    PostureObservation.id,
                    [PostureObservation.observed_at < cutoff],
                    "posture_observation",
                    data_class,
                    result,
                )
            if data_class == "approvals-180d":
                where = [
                    ExportRequest.status.in_(FINAL_EXPORT_STATES),
                    ExportRequest.updated_at < cutoff,
                ]
                if held:
                    where.append(ExportRequest.requester_id.not_in(list(held)))
                _purge(
                    db,
                    ExportRequest,
                    ExportRequest.id,
                    where,
                    "export_request",
                    data_class,
                    result,
                    extra_delete=lambda ids: _drop_export_children(db, ids),
                )
            if data_class == "work-summary-365d":
                where = [WorkUpdate.update_date < cutoff.date()]
                if held:
                    where.append(WorkUpdate.employee_id.not_in(list(held)))
                _purge(
                    db,
                    WorkUpdate,
                    WorkUpdate.id,
                    where,
                    "work_update",
                    data_class,
                    result,
                    extra_delete=lambda ids: db.execute(
                        delete(WorkUpdateCorrection).where(
                            WorkUpdateCorrection.work_update_id.in_(ids)
                        )
                    ),
                )
        audit.record(db, None, "retention.applied", "retention", None, after=result.deleted)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


# subject_type -> (model, child rows to delete first, employee column for legal holds)
_REAPPLY = {
    "security_event": (SecurityEvent, None, SecurityEvent.employee_id),
    "posture_observation": (PostureObservation, None, None),
    "export_request": (
        ExportRequest,
        (ExportDecision, "export_request_id"),
        ExportRequest.requester_id,
    ),
    "work_update": (WorkUpdate, (WorkUpdateCorrection, "work_update_id"), WorkUpdate.employee_id),
}


def reapply_tombstones(db: Session) -> dict[str, int]:
    """Post-restore: delete rows a backup brought back that were already expired. Commits.

    Current legal holds win: a global hold pauses this, an employee hold keeps that employee's rows.
    """
    global_hold, held = _holds(db)
    if global_hold:
        return {}
    counts: dict[str, int] = {}
    try:
        for subject_type, (model, child, owner_col) in _REAPPLY.items():
            ids = [
                uuid.UUID(s)
                for s in db.scalars(
                    select(DeletionTombstone.subject_id).where(
                        DeletionTombstone.subject_type == subject_type
                    )
                )
            ]
            if not ids:
                continue
            keep = [model.id.in_(ids)]
            if held and owner_col is not None:
                keep.append(owner_col.is_(None) | owner_col.not_in(list(held)))
            doomed = db.scalars(select(model.id).where(*keep)).all()
            if not doomed:
                continue
            if child:
                child_model, fk = child
                db.execute(delete(child_model).where(getattr(child_model, fk).in_(doomed)))
            counts[subject_type] = db.execute(delete(model).where(model.id.in_(doomed))).rowcount
        if counts:
            audit.record(
                db, None, "retention.tombstones_reapplied", "retention", None, after=counts
            )
        db.commit()
    except Exception:
        db.rollback()
        raise
    return counts


if __name__ == "__main__":
    # python -m portal.retention --reapply : after a restore, delete what tombstones say is gone
    if "--reapply" not in sys.argv[1:]:
        sys.exit("usage: python -m portal.retention --reapply")
    from portal.db import session_factory

    with session_factory()() as _db:
        print(reapply_tombstones(_db))
