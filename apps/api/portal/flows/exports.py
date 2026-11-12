"""Export approval workflow (PLAN.md sections 10 and 12).

requested -> reviewed -> approved | rejected -> staged -> released -> expired (or cancelled).

Approval is not a transfer. The worker stages only the approved object version into a release
area, release is a separate audited step, and nothing here fetches URLs or caller-supplied paths.
Config comes from the environment (read per call so tests can monkeypatch):

    EXPORT_SOURCE_ROOT          internal directory approved objects live in (required to stage)
    EXPORT_RELEASE_ROOT         directory the staged copies are written to (required to stage)
    EXPORT_MAX_CLASSIFICATION   release ceiling, default "restricted"
    EXPORT_APPROVAL_HOURS       how long an approval stays usable, default 72
    EXPORT_RELEASE_HOURS        how long a released copy stays in the release area, default 24
"""

import hashlib
import os
import re
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from portal import audit, jobs
from portal.authz import forbid_self
from portal.jobs import job_handler
from portal.models import CLASSIFICATIONS, Employee, ExportDecision, ExportRequest

OPEN_STATUSES = ("requested", "reviewed", "approved", "staged")
LIVE_STATUSES = ("approved", "staged", "released")  # hold a grant or a copy in the release area
EXPIRY_SLOT_SECONDS = 300
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_DECISION_ACTION = {"approved": "export.approve", "rejected": "export.reject"}


class ExportSafetyError(Exception):
    """Permanent failure (bad path, checksum mismatch, tampered terms): do not retry."""


def _now() -> datetime:
    return datetime.now(UTC)


def _env_int(name: str, default: int) -> int:
    return int(os.environ.get(name) or default)


def _root(name: str) -> Path:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not configured")  # transient: retried, operator-visible
    return Path(os.path.realpath(value))


def max_classification() -> str:
    value = os.environ.get("EXPORT_MAX_CLASSIFICATION") or "restricted"
    return value if value in CLASSIFICATIONS else "public"  # unknown value fails closed


def _rank(classification: str) -> int:
    return CLASSIFICATIONS.index(classification)


# ---------------------------------------------------------------- object references


def check_ref(ref: str) -> None:
    """Syntactic gate: a relative POSIX path with no traversal, drive letter or URL scheme."""
    parts = ref.split("/") if ref else []
    if (
        not ref
        or len(ref) > 512
        or ref.startswith("/")
        or "\\" in ref
        or ":" in ref
        or "\x00" in ref
        or any(p in ("", ".", "..") for p in parts)
    ):
        raise ValueError("object_ref must be a relative path inside the export source root")


def resolve_source(root: Path, ref: str) -> Path:
    """Existing regular file under root, with no symlink or junction on the way."""
    try:
        check_ref(ref)
    except ValueError as exc:
        raise ExportSafetyError(str(exc)) from exc
    candidate = root / PurePosixPath(ref)
    real = Path(os.path.realpath(candidate))
    if os.path.normcase(real) != os.path.normcase(os.path.normpath(candidate)):
        raise ExportSafetyError("object path leaves the source root or crosses a symlink")
    if not real.is_file():
        raise ExportSafetyError("object not found in the source root")
    return real


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def binding_digest(req: ExportRequest) -> str:
    """Fingerprint of everything the approver approved. Recomputed at stage and release."""
    return audit.digest(
        {
            "id": str(req.id),
            "requester_id": str(req.requester_id),
            "object_ref": req.object_ref,
            "object_version": req.object_version,
            "object_checksum": req.object_checksum,
            "classification": req.classification,
            "recipient": req.recipient,
        }
    )


def _staged_file(req: ExportRequest) -> Path | None:
    if not req.staged_path:
        return None
    root = _root("EXPORT_RELEASE_ROOT")
    path = Path(os.path.realpath(root / req.staged_path))
    return path if path.is_relative_to(root) else None


def _remove_staged(req: ExportRequest) -> None:
    """Delete the release-area copy. Never touches anything outside <release root>/<request id>."""
    if os.environ.get("EXPORT_RELEASE_ROOT"):
        root = _root("EXPORT_RELEASE_ROOT")
        target = Path(os.path.realpath(root / str(req.id)))
        if target.parent == root:
            shutil.rmtree(target, ignore_errors=True)
    req.staged_path = None


# ---------------------------------------------------------------- views


def lock_export(db: Session, export_id: uuid.UUID) -> ExportRequest:
    req = db.scalars(
        select(ExportRequest).where(ExportRequest.id == export_id).with_for_update()
    ).first()
    if req is None:
        raise HTTPException(404, "not found")
    return req


def view(req: ExportRequest) -> dict:
    return {
        "id": str(req.id),
        "requester_id": str(req.requester_id),
        "object_ref": req.object_ref,
        "object_version": req.object_version,
        "object_checksum": req.object_checksum,
        "classification": req.classification,
        "recipient": req.recipient,
        "purpose": req.purpose,
        "status": req.status,
        "reviewer_id": str(req.reviewer_id) if req.reviewer_id else None,
        "expires_at": req.expires_at,
        "stage_error": req.stage_error,
        "release_checksum": req.release_checksum,
        "release_receipt": req.release_receipt,
        "released_by": str(req.released_by) if req.released_by else None,
        "released_at": req.released_at,
        "created_at": req.created_at,
        "decisions": [
            {
                "reviewer_id": str(d.reviewer_id),
                "decision": d.decision,
                "reason": d.reason,
                "created_at": d.created_at,
            }
            for d in req.decisions
        ],
    }


# ---------------------------------------------------------------- transitions


def create(
    db: Session,
    actor: Employee,
    *,
    object_ref: str,
    object_version: str | None,
    object_checksum: str,
    classification: str,
    recipient: str,
    purpose: str,
) -> ExportRequest:
    try:
        check_ref(object_ref)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if classification not in CLASSIFICATIONS:
        raise HTTPException(422, "unknown classification")
    object_checksum = object_checksum.lower()
    if not _SHA256.match(object_checksum):
        raise HTTPException(422, "object_checksum must be a sha256 hex digest")
    if not recipient.strip() or not purpose.strip():
        raise HTTPException(422, "recipient and purpose are required")
    req = ExportRequest(
        requester_id=actor.id,
        object_ref=object_ref,
        object_version=object_version,
        object_checksum=object_checksum,
        classification=classification,
        recipient=recipient.strip(),
        purpose=purpose.strip(),
    )
    db.add(req)
    db.flush()
    audit.record(
        db,
        actor,
        "export.request",
        "export_request",
        req.id,
        reason=req.purpose,
        after={"status": "requested", "classification": classification},
    )
    return req


def decide(
    db: Session, actor: Employee, req: ExportRequest, decision: str, reason: str | None
) -> ExportRequest:
    """The caller holds the `approver` role and has locked `req`."""
    forbid_self(actor, req.requester_id, "decision")
    if req.status not in ("requested", "reviewed"):
        raise HTTPException(409, f"request is {req.status}, no decision possible")
    if db.get(Employee, req.requester_id).status != "active":
        raise HTTPException(409, "requester is no longer active")
    if any(d.reviewer_id == actor.id for d in req.decisions):
        raise HTTPException(409, "you already decided on this request")
    before = req.status
    db.add(
        ExportDecision(
            export_request_id=req.id, reviewer_id=actor.id, decision=decision, reason=reason
        )
    )
    db.flush()
    db.refresh(req)
    req.reviewer_id = req.reviewer_id or actor.id
    if decision == "rejected":
        req.status = "rejected"
    else:
        needed = 2 if req.classification == "restricted" else 1  # two distinct approvers
        approvals = sum(1 for d in req.decisions if d.decision == "approved")
        if approvals >= needed:
            req.status = "approved"
            req.approval_digest = binding_digest(req)
            req.expires_at = _now() + timedelta(hours=_env_int("EXPORT_APPROVAL_HOURS", 72))
            jobs.enqueue(
                db,
                "export.stage",
                {"export_id": str(req.id)},
                idempotency_key=f"export.stage:{req.id}",
            )
            schedule_expiry(db)
        else:
            req.status = "reviewed"
    audit.record(
        db,
        actor,
        _DECISION_ACTION[decision],
        "export_request",
        req.id,
        reason=reason,
        before={"status": before},
        after={"status": req.status},
    )
    return req


def cancel(db: Session, actor: Employee | None, req: ExportRequest, reason: str) -> None:
    if req.status not in OPEN_STATUSES:
        raise HTTPException(409, f"request is {req.status}, cannot cancel")
    before = req.status
    _remove_staged(req)
    req.status = "cancelled"
    audit.record(
        db,
        actor,
        "export.cancel",
        "export_request",
        req.id,
        reason=reason,
        before={"status": before},
        after={"status": "cancelled"},
    )


def revoke_for_employee(
    db: Session, actor: Employee | None, employee_id: uuid.UUID, reason: str
) -> int:
    """Offboarding: cancel every open export of this requester, expire released copies."""
    rows = db.scalars(
        select(ExportRequest)
        .where(
            ExportRequest.requester_id == employee_id,
            ExportRequest.status.in_(OPEN_STATUSES + ("released",)),
        )
        .with_for_update()
    ).all()
    for req in rows:
        if req.status == "released":
            _expire(db, req, actor)
        else:
            cancel(db, actor, req, reason)
    return len(rows)


def release(
    db: Session, actor: Employee, req: ExportRequest, recipient: str, channel_note: str
) -> ExportRequest:
    """The caller holds approver or it and has locked `req`. Revalidates everything."""
    forbid_self(actor, req.requester_id, "release")
    if req.status == "released":
        raise HTTPException(409, "already released")
    if req.status != "staged":
        raise HTTPException(409, f"request is {req.status}, not staged")
    if req.expires_at is None or req.expires_at <= _now():
        _expire(db, req, None)
        db.commit()  # keep the expiry even though this request fails
        raise HTTPException(409, "approval expired")
    if recipient != req.recipient:
        raise HTTPException(409, "recipient does not match the approved recipient")
    if req.approval_digest != binding_digest(req):
        raise HTTPException(409, "approved terms changed after approval")
    if _rank(req.classification) > _rank(max_classification()):
        raise HTTPException(409, "classification exceeds the release ceiling")
    if db.get(Employee, req.requester_id).status != "active":
        raise HTTPException(409, "requester is no longer active")
    staged = _staged_file(req)
    if staged is None or not staged.is_file():
        raise HTTPException(409, "staged copy is missing")
    checksum = sha256_file(staged)
    if checksum != req.object_checksum:
        raise HTTPException(409, "staged copy does not match the approved checksum")
    now = _now()
    req.status = "released"
    req.released_by, req.released_at, req.release_checksum = actor.id, now, checksum
    req.expires_at = now + timedelta(hours=_env_int("EXPORT_RELEASE_HOURS", 24))
    req.release_receipt = {
        "released_by": str(actor.id),
        "released_at": now.isoformat(),
        "checksum": checksum,
        "recipient": req.recipient,
        "channel_note": channel_note,
    }
    audit.record(
        db,
        actor,
        "export.release",
        "export_request",
        req.id,
        reason=channel_note,
        before={"status": "staged"},
        after={"status": "released", "checksum": checksum},
    )
    schedule_expiry(db)
    return req


def _expire(db: Session, req: ExportRequest, actor: Employee | None) -> None:
    before = req.status
    _remove_staged(req)
    req.status = "expired"
    audit.record(
        db,
        actor,
        "export.expire",
        "export_request",
        req.id,
        before={"status": before},
        after={"status": "expired"},
    )


# ---------------------------------------------------------------- worker jobs


def stage(db: Session, export_id: uuid.UUID) -> None:
    """Copy exactly the approved object version into the release area. Idempotent."""
    req = db.scalars(
        select(ExportRequest).where(ExportRequest.id == export_id).with_for_update()
    ).first()
    if req is None or req.status != "approved":
        return  # already staged, or cancelled/expired meanwhile
    if req.expires_at is None or req.expires_at <= _now():
        return  # the expiry job retires it
    source_root, release_root = _root("EXPORT_SOURCE_ROOT"), _root("EXPORT_RELEASE_ROOT")
    try:
        if req.approval_digest != binding_digest(req):
            raise ExportSafetyError("approved terms changed after approval")
        src = resolve_source(source_root, req.object_ref)
        dest = release_root / str(req.id) / PurePosixPath(req.object_ref).name
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        h = hashlib.sha256()
        try:
            with src.open("rb") as fin, tmp.open("wb") as fout:
                for chunk in iter(lambda: fin.read(1 << 20), b""):
                    h.update(chunk)
                    fout.write(chunk)
            if h.hexdigest() != req.object_checksum:
                raise ExportSafetyError("object checksum differs from the approved version")
            os.replace(tmp, dest)
        finally:
            tmp.unlink(missing_ok=True)
    except ExportSafetyError as exc:
        req.stage_error = str(exc)[:500]
        audit.record(
            db, None, "export.stage_failed", "export_request", req.id, reason=req.stage_error
        )
        return
    req.status, req.stage_error = "staged", None
    req.staged_path = f"{req.id}/{dest.name}"
    audit.record(
        db,
        None,
        "export.stage",
        "export_request",
        req.id,
        before={"status": "approved"},
        after={"status": "staged", "checksum": h.hexdigest()},
    )


def expire_due(db: Session, now: datetime | None = None) -> int:
    now = now or _now()
    rows = db.scalars(
        select(ExportRequest)
        .where(ExportRequest.status.in_(LIVE_STATUSES), ExportRequest.expires_at <= now)
        .with_for_update(skip_locked=True)
    ).all()
    for req in rows:
        _expire(db, req, None)
    return len(rows)


def schedule_expiry(db: Session, now: datetime | None = None) -> None:
    # ponytail: no scheduler exists, so the expiry job re-enqueues itself one slot later and
    # approvals/releases wake it; release() also checks expiry directly, so this only cleans up.
    slot = int((now or _now()).timestamp() // EXPIRY_SLOT_SECONDS)
    job = jobs.enqueue(db, "export.expire", {}, idempotency_key=f"export.expire:{slot}")
    if job.status != "queued":
        # The slot's job already ran (chain ended) or is mid-run and may have missed this row:
        # the idempotent key would swallow the wake-up, so queue a distinct one.
        jobs.enqueue(
            db, "export.expire", {}, idempotency_key=f"export.expire:{slot}:{uuid.uuid4().hex}"
        )


@job_handler("export.stage")
def _stage_job(db: Session, job) -> None:
    stage(db, uuid.UUID(job.payload["export_id"]))


@job_handler("export.expire")
def _expire_job(db: Session, job) -> None:
    expire_due(db)
    has_live = db.scalars(
        select(ExportRequest.id).where(ExportRequest.status.in_(LIVE_STATUSES)).limit(1)
    ).first()
    if has_live:
        nxt = _now() + timedelta(seconds=EXPIRY_SLOT_SECONDS)
        slot = int(nxt.timestamp() // EXPIRY_SLOT_SECONDS)
        jobs.enqueue(db, "export.expire", {}, run_at=nxt, idempotency_key=f"export.expire:{slot}")
