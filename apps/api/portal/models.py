"""All core records (PLAN.md section 10). UTC timestamptz everywhere, enums via CHECK."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


TS = DateTime(timezone=True)
NOW = func.now()
EMPTY_OBJ = text("'{}'::jsonb")
EMPTY_ARR = text("'[]'::jsonb")


def uuid_pk():
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


ROLES = ("employee", "manager", "it", "security", "approver", "admin")
EMPLOYEE_STATUS = ("active", "offboarding", "offboarded")
CLASSIFICATIONS = ("public", "internal", "confidential", "restricted")
SEVERITIES = ("info", "low", "medium", "high", "critical")
CASE_STATUS = ("open", "investigating", "resolved", "closed")
EXPORT_STATUS = (
    "requested",
    "reviewed",
    "approved",
    "rejected",
    "staged",
    "released",
    "expired",
    "cancelled",
)
JOB_STATUS = ("queued", "running", "succeeded", "failed")
OFFBOARDING_STATUS = ("requested", "in_progress", "incomplete", "verified_complete")
STEP_STATUS = (
    "pending",
    "running",
    "succeeded",
    "failed",
    "manual_required",
    "verified",
    "skipped_not_configured",
)
_ROLES_SQL = "ARRAY[" + ",".join(repr(r) for r in ROLES) + "]::text[]"


class Employee(Base):
    __tablename__ = "employees"
    __table_args__ = (
        CheckConstraint(_in("status", EMPLOYEE_STATUS), name="status"),
        CheckConstraint(f"roles <@ {_ROLES_SQL}", name="roles"),
        CheckConstraint("manager_id IS NULL OR manager_id <> id", name="not_own_manager"),
        Index("ix_employees_manager_id", "manager_id"),
        # one login identity per address; '' means "no verified email yet" and may repeat
        Index(
            "uq_employees_email_lower",
            text("lower(email)"),
            unique=True,
            postgresql_where=text("email <> ''"),
        ),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    # Immutable (DB trigger). Identity key; never match on email.
    oidc_subject: Mapped[str] = mapped_column(Text, unique=True)
    display_name: Mapped[str] = mapped_column(Text)
    email: Mapped[str] = mapped_column(Text)
    manager_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    roles: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("ARRAY['employee']::text[]")
    )
    status: Mapped[str] = mapped_column(Text, server_default="active")
    timezone: Mapped[str] = mapped_column(Text, server_default="UTC")
    created_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=NOW, onupdate=NOW)
    offboarded_at: Mapped[datetime | None] = mapped_column(TS)


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (
        CheckConstraint(_in("ownership", ("company", "personal")), name="ownership"),
        Index("ix_assets_assigned_employee_id", "assigned_employee_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text)
    ownership: Mapped[str] = mapped_column(Text)
    assigned_employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    os: Mapped[str | None] = mapped_column(Text)
    upstream_ids: Mapped[dict] = mapped_column(JSONB, server_default=EMPTY_OBJ)  # fleet/wazuh ids
    # Restricted fields (serial, etc.) are company equipment only; enforced in routers.
    restricted: Mapped[dict] = mapped_column(JSONB, server_default=EMPTY_OBJ)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (
        CheckConstraint(_in("classification_ceiling", CLASSIFICATIONS), name="classification"),
        CheckConstraint(
            _in("lifecycle_state", ("requested", "active", "suspended", "decommissioned")),
            name="lifecycle_state",
        ),
        Index("ix_workspaces_owner_id", "owner_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"))
    name: Mapped[str] = mapped_column(Text)
    role_profile: Mapped[str] = mapped_column(Text)
    classification_ceiling: Mapped[str] = mapped_column(Text, server_default="internal")
    connection_ref: Mapped[str | None] = mapped_column(Text)  # guacamole connection id
    # Device or server VM behind the workspace; its posture is the workspace's posture.
    asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assets.id"))
    lifecycle_state: Mapped[str] = mapped_column(Text, server_default="requested")
    created_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)


class PolicyVersion(Base):
    """Immutable (DB trigger): new content means a new version row."""

    __tablename__ = "policy_versions"
    __table_args__ = (UniqueConstraint("name", "version"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(Text)  # e.g. collection-policy
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[dict] = mapped_column(JSONB)
    content_hash: Mapped[str] = mapped_column(Text)  # sha256 of canonical content
    created_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)


class PolicyAssignment(Base):
    __tablename__ = "policy_assignments"
    __table_args__ = (
        CheckConstraint(_in("scope_type", ("all", "employee", "workspace", "asset")), name="scope"),
        CheckConstraint("(scope_type = 'all') = (scope_id IS NULL)", name="scope_id_matches_type"),
        Index("ix_policy_assignments_policy_version_id", "policy_version_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    policy_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("policy_versions.id"))
    scope_type: Mapped[str] = mapped_column(Text)
    scope_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    activates_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)
    is_exception: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    expires_at: Mapped[datetime | None] = mapped_column(TS)  # exceptions expire
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    created_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)


class MaintenanceException(Base):
    """Audited, expiring IT maintenance exception for one device (PLAN.md section 11)."""

    __tablename__ = "maintenance_exceptions"
    __table_args__ = (
        CheckConstraint("approver_id <> requested_by", name="approver_not_requester"),
        Index("ix_maintenance_exceptions_asset_expires", "asset_id", "expires_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"))
    reason: Mapped[str] = mapped_column(Text)
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"))
    approver_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"))
    expires_at: Mapped[datetime] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)


class PostureObservation(Base):
    """Evidence, not a command. Readers must treat stale or expired rows as unknown."""

    __tablename__ = "posture_observations"
    __table_args__ = (
        CheckConstraint(_in("state", ("compliant", "noncompliant", "unknown")), name="state"),
        Index("ix_posture_observations_asset_observed", "asset_id", "observed_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id"))
    source: Mapped[str] = mapped_column(Text)
    observed_at: Mapped[datetime] = mapped_column(TS)
    received_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)
    expires_at: Mapped[datetime] = mapped_column(TS)
    state: Mapped[str] = mapped_column(Text, server_default="unknown")
    checks: Mapped[dict] = mapped_column(JSONB, server_default=EMPTY_OBJ)


class WorkUpdate(Base):
    __tablename__ = "work_updates"
    __table_args__ = (UniqueConstraint("employee_id", "update_date"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"))
    update_date: Mapped[date] = mapped_column(Date)
    summary: Mapped[str] = mapped_column(Text)
    task_refs: Mapped[list] = mapped_column(JSONB, server_default=EMPTY_ARR)
    deliverables: Mapped[list] = mapped_column(JSONB, server_default=EMPTY_ARR)
    blocker: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=NOW, onupdate=NOW)

    corrections: Mapped[list["WorkUpdateCorrection"]] = relationship(
        back_populates="work_update", order_by="WorkUpdateCorrection.created_at"
    )


class WorkUpdateCorrection(Base):
    __tablename__ = "work_update_corrections"
    __table_args__ = (Index("ix_work_update_corrections_work_update_id", "work_update_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    work_update_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("work_updates.id"))
    corrected_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"))
    previous: Mapped[dict] = mapped_column(JSONB)  # snapshot before the correction
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)

    work_update: Mapped[WorkUpdate] = relationship(back_populates="corrections")


class SecurityEvent(Base):
    __tablename__ = "security_events"
    __table_args__ = (
        UniqueConstraint("source", "source_event_id"),
        CheckConstraint(_in("severity", SEVERITIES), name="severity"),
        CheckConstraint(_in("classification", CLASSIFICATIONS), name="classification"),
        Index("ix_security_events_employee_occurred", "employee_id", "occurred_at"),
        Index("ix_security_events_occurred_at", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()  # the contract's event_id
    schema_version: Mapped[int] = mapped_column(Integer, server_default="1")
    source: Mapped[str] = mapped_column(Text)
    source_event_id: Mapped[str] = mapped_column(Text)
    # NULL = unresolved identity; never guess.
    employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    asset_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("assets.id"))
    event_type: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text, server_default="info")
    actor: Mapped[str | None] = mapped_column(Text)
    resource: Mapped[str | None] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(TS)
    received_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)
    classification: Mapped[str] = mapped_column(Text, server_default="internal")
    retention_policy: Mapped[str] = mapped_column(Text, server_default="security-90d")
    event_metadata: Mapped[dict] = mapped_column("metadata", JSONB, server_default=EMPTY_OBJ)


class Case(Base):
    __tablename__ = "cases"
    __table_args__ = (
        CheckConstraint(_in("status", CASE_STATUS), name="status"),
        CheckConstraint(_in("severity", SEVERITIES), name="severity"),
        CheckConstraint(
            "status <> 'closed' OR closure_rationale IS NOT NULL", name="closed_has_rationale"
        ),
        Index("ix_cases_status", "status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    owner_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    subject_employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    title: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(Text, server_default="medium")
    status: Mapped[str] = mapped_column(Text, server_default="open")
    evidence_refs: Mapped[list] = mapped_column(JSONB, server_default=EMPTY_ARR)  # event ids
    closure_rationale: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=NOW, onupdate=NOW)
    closed_at: Mapped[datetime | None] = mapped_column(TS)

    actions: Mapped[list["CaseAction"]] = relationship(
        back_populates="case", order_by="CaseAction.created_at"
    )


class CaseAction(Base):
    __tablename__ = "case_actions"
    __table_args__ = (Index("ix_case_actions_case_id", "case_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    case_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("cases.id"))
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"))
    action: Mapped[str] = mapped_column(Text)  # from the limited action catalogue
    detail: Mapped[dict] = mapped_column(JSONB, server_default=EMPTY_OBJ)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)

    case: Mapped[Case] = relationship(back_populates="actions")


class ExportRequest(Base):
    __tablename__ = "export_requests"
    __table_args__ = (
        CheckConstraint(_in("status", EXPORT_STATUS), name="status"),
        CheckConstraint(_in("classification", CLASSIFICATIONS), name="classification"),
        CheckConstraint(
            "reviewer_id IS NULL OR reviewer_id <> requester_id", name="no_self_review"
        ),
        Index("ix_export_requests_status", "status"),
        Index("ix_export_requests_requester_id", "requester_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    requester_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"))
    object_ref: Mapped[str] = mapped_column(Text)
    object_version: Mapped[str | None] = mapped_column(Text)
    object_checksum: Mapped[str | None] = mapped_column(Text)  # sha256 hex the approver bound
    classification: Mapped[str] = mapped_column(Text)
    recipient: Mapped[str] = mapped_column(Text)
    purpose: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="requested")
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    expires_at: Mapped[datetime | None] = mapped_column(TS)
    approval_digest: Mapped[str | None] = mapped_column(Text)  # hash of the bound terms
    staged_path: Mapped[str | None] = mapped_column(Text)  # relative to the release root
    stage_error: Mapped[str | None] = mapped_column(Text)
    release_checksum: Mapped[str | None] = mapped_column(Text)
    release_receipt: Mapped[dict | None] = mapped_column(JSONB)
    released_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    released_at: Mapped[datetime | None] = mapped_column(TS)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=NOW, onupdate=NOW)

    decisions: Mapped[list["ExportDecision"]] = relationship(
        back_populates="export_request", order_by="ExportDecision.created_at"
    )


class ExportDecision(Base):
    __tablename__ = "export_decisions"
    __table_args__ = (
        CheckConstraint(_in("decision", ("approved", "rejected")), name="decision"),
        Index("ix_export_decisions_export_request_id", "export_request_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    export_request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("export_requests.id"))
    reviewer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"))
    decision: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)

    export_request: Mapped[ExportRequest] = relationship(back_populates="decisions")


class AuditEvent(Base):
    """Append-only: a DB trigger rejects UPDATE and DELETE. No FKs so history outlives rows."""

    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_target", "target_type", "target_id"),
        Index("ix_audit_events_actor_id", "actor_id"),
        Index("ix_audit_events_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))  # NULL = system
    action: Mapped[str] = mapped_column(Text)
    target_type: Mapped[str] = mapped_column(Text)
    target_id: Mapped[str | None] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    before_hash: Mapped[str | None] = mapped_column(Text)
    after_hash: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(_in("status", JOB_STATUS), name="status"),
        Index("ix_jobs_status_run_at", "status", "run_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    kind: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, server_default=EMPTY_OBJ)
    idempotency_key: Mapped[str | None] = mapped_column(Text, unique=True)
    status: Mapped[str] = mapped_column(Text, server_default="queued")
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, server_default="5")
    run_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)
    locked_at: Mapped[datetime | None] = mapped_column(TS)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)
    finished_at: Mapped[datetime | None] = mapped_column(TS)


class ConnectorCheckpoint(Base):
    __tablename__ = "connector_checkpoints"

    name: Mapped[str] = mapped_column(Text, primary_key=True)  # connector name
    cursor: Mapped[str | None] = mapped_column(Text)
    last_attempt_at: Mapped[datetime | None] = mapped_column(TS)
    last_success_at: Mapped[datetime | None] = mapped_column(TS)
    last_error: Mapped[str | None] = mapped_column(Text)
    capabilities: Mapped[dict] = mapped_column(JSONB, server_default=EMPTY_OBJ)  # edition/features
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=NOW, onupdate=NOW)


class RetentionRule(Base):
    __tablename__ = "retention_rules"
    __table_args__ = (CheckConstraint("retention_days > 0", name="positive_days"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    data_class: Mapped[str] = mapped_column(Text, unique=True)  # e.g. security-90d
    retention_days: Mapped[int] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)


class LegalHold(Base):
    __tablename__ = "legal_holds"
    __table_args__ = (Index("ix_legal_holds_employee_id", "employee_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    scope: Mapped[str] = mapped_column(Text)
    reason: Mapped[str] = mapped_column(Text)
    placed_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"))
    placed_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)
    released_at: Mapped[datetime | None] = mapped_column(TS)


class DeletionTombstone(Base):
    """Restore jobs must reapply these. Holds identifiers only, never the deleted content."""

    __tablename__ = "deletion_tombstones"
    __table_args__ = (UniqueConstraint("subject_type", "subject_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    subject_type: Mapped[str] = mapped_column(Text)
    subject_id: Mapped[str] = mapped_column(Text)
    rule: Mapped[str | None] = mapped_column(Text)
    deleted_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)


class OffboardingJob(Base):
    __tablename__ = "offboarding_jobs"
    __table_args__ = (
        CheckConstraint(_in("status", OFFBOARDING_STATUS), name="status"),
        Index("ix_offboarding_jobs_employee_id", "employee_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"))
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"))
    reason: Mapped[str] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(Text, unique=True)
    status: Mapped[str] = mapped_column(Text, server_default="requested")
    requested_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)
    completed_at: Mapped[datetime | None] = mapped_column(TS)

    steps: Mapped[list["OffboardingStep"]] = relationship(
        back_populates="job", order_by="OffboardingStep.seq"
    )


class OffboardingStep(Base):
    """One row per subsystem (keycloak, guacamole, git, vpn, ...): separate, retryable status."""

    __tablename__ = "offboarding_steps"
    __table_args__ = (
        UniqueConstraint("job_id", "subsystem"),
        CheckConstraint(_in("status", STEP_STATUS), name="status"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("offboarding_jobs.id"))
    seq: Mapped[int] = mapped_column(Integer, server_default="0")
    subsystem: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, server_default="pending")
    detail: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    verified_at: Mapped[datetime | None] = mapped_column(TS)
    updated_at: Mapped[datetime] = mapped_column(TS, server_default=NOW, onupdate=NOW)

    job: Mapped[OffboardingJob] = relationship(back_populates="steps")


class NoticeAcknowledgement(Base):
    __tablename__ = "notice_acknowledgements"
    __table_args__ = (UniqueConstraint("employee_id", "policy_version_id"),)

    id: Mapped[uuid.UUID] = uuid_pk()
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id"))
    policy_version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("policy_versions.id"))
    acknowledged_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)


class PortalSession(Base):
    """Server-side portal session. The cookie holds a random token; only its sha256 is stored.

    employee_id NULL with pending_login set is a pre-login row holding OIDC state/nonce/verifier.
    """

    __tablename__ = "sessions"
    __table_args__ = (
        CheckConstraint(
            "employee_id IS NOT NULL OR pending_login IS NOT NULL", name="has_employee_or_pending"
        ),
        Index("ix_sessions_employee_id", "employee_id"),
        Index("ix_sessions_expires_at", "expires_at"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    employee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    pending_login: Mapped[dict | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)
    expires_at: Mapped[datetime] = mapped_column(TS)
    last_seen_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)
    revoked_at: Mapped[datetime | None] = mapped_column(TS)


class TaskSnapshot(Base):
    """Read-only copy of one tracker task, filled by the worker's tracker adapter.

    Portal handlers only read it. assignee_id NULL = unresolved identity; never shown to anyone.
    """

    __tablename__ = "task_snapshots"
    __table_args__ = (
        UniqueConstraint("source", "source_ref"),
        CheckConstraint(
            _in("state", ("open", "in_progress", "in_review", "blocked", "done")), name="state"
        ),
        Index("ix_task_snapshots_assignee_id", "assignee_id"),
    )

    id: Mapped[uuid.UUID] = uuid_pk()
    source: Mapped[str] = mapped_column(Text)  # e.g. gitea
    source_ref: Mapped[str] = mapped_column(Text)  # id in the tracker
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employees.id"))
    title: Mapped[str] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(Text, server_default="open")
    due_date: Mapped[date | None] = mapped_column(Date)
    blocker: Mapped[str | None] = mapped_column(Text)
    deliverables: Mapped[list] = mapped_column(JSONB, server_default=EMPTY_ARR)  # [{title, url}]
    review_requested_at: Mapped[datetime | None] = mapped_column(TS)
    synced_at: Mapped[datetime] = mapped_column(TS, server_default=NOW)
