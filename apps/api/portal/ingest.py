"""Event ingest (PLAN.md section 10, "Event contract and correctness").

normalize()  validates one NormalizedEvent and drops every metadata key that is not allowlisted.
persist()    stores a page of events, opens cases for high severity, and advances the connector
             cursor, all in ONE transaction: a crash re-delivers the page, dedup absorbs it.

Dedup key is (source, source_event_id), so replays and reordered pages never duplicate events
or cases (a case is only opened for an event this call actually inserted).
"""

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from portal import audit
from portal.connectors.base import NormalizedEvent
from portal.connectors.http import redact
from portal.flows.cases import create_case_from_event
from portal.models import (
    CLASSIFICATIONS,
    SEVERITIES,
    Asset,
    ConnectorCheckpoint,
    Employee,
    SecurityEvent,
)

ALLOWED_METADATA = frozenset(
    {
        "rule_id",
        "rule_groups",
        "level",
        "agent_id",
        "agent_name",
        "src_ip",
        "dst_ip",
        "action",
        "outcome",
        "category",
        "reason",
        "status",
        "count",
        "decoder",
        "process_name",
        "host",
        "repo",
        "ref",
        "labels",
        "version",
        "disk_encryption",
        "clock_skew_s",
    }
)
# Never stored even if someone allowlists them by mistake: content PLAN.md section 9 excludes.
FORBIDDEN_KEY_PARTS = ("title", "clipboard", "password", "passwd", "secret", "token", "keystroke")
MAX_STR = 256
MAX_ITEMS = 20
CLOCK_SKEW = timedelta(minutes=5)
_URL = re.compile(r"(https?://[^\s?#]+)[?#]\S*", re.I)


class RejectedEvent(ValueError):
    """The event cannot be stored (missing/invalid required field). Counted, never fatal."""


def _clean_value(value):
    if isinstance(value, bool) or value is None or isinstance(value, int | float):
        return value
    if isinstance(value, str):
        return _URL.sub(r"\1", value)[:MAX_STR]  # strip URL query strings and fragments
    if isinstance(value, list | tuple):
        items = [_clean_value(v) for v in value[:MAX_ITEMS]]
        return [v for v in items if isinstance(v, str | int | float | bool)]
    return None  # nested objects are dropped: the allowlist is flat scalars


def sanitize_metadata(meta: dict | None) -> dict:
    out = {}
    for key, value in (meta or {}).items():
        k = str(key).lower()
        if k not in ALLOWED_METADATA or any(p in k for p in FORBIDDEN_KEY_PARTS):
            continue
        cleaned = _clean_value(value)
        if cleaned is not None:
            out[k] = cleaned
    return out


def normalize(ev: NormalizedEvent, now: datetime | None = None) -> NormalizedEvent:
    """Return a validated copy. Raises RejectedEvent. Identity fields pass through as given."""
    now = now or datetime.now(UTC)
    if not ev.source or not str(ev.source_event_id).strip() or not ev.event_type:
        raise RejectedEvent("missing source, source_event_id or event_type")
    if not isinstance(ev.occurred_at, datetime):
        raise RejectedEvent("occurred_at is not a datetime")
    if ev.severity not in SEVERITIES:
        raise RejectedEvent(f"unknown severity {ev.severity!r}")
    if ev.classification not in CLASSIFICATIONS:
        raise RejectedEvent(f"unknown classification {ev.classification!r}")
    occurred = ev.occurred_at if ev.occurred_at.tzinfo else ev.occurred_at.replace(tzinfo=UTC)
    occurred = occurred.astimezone(UTC)
    meta = sanitize_metadata(ev.metadata)
    if occurred > now + CLOCK_SKEW:  # source clock ahead: keep the event, clamp, say so
        meta["clock_skew_s"] = int((occurred - now).total_seconds())
        occurred = now
    return NormalizedEvent(
        source=ev.source,
        source_event_id=str(ev.source_event_id)[:200],
        event_type=ev.event_type[:100],
        occurred_at=occurred,
        schema_version=ev.schema_version,
        employee_id=ev.employee_id,
        asset_id=ev.asset_id,
        severity=ev.severity,
        actor=(ev.actor or None) and ev.actor[:200],
        resource=(ev.resource or None) and ev.resource[:200],
        classification=ev.classification,
        retention_policy=ev.retention_policy,
        received_at=now,
        metadata=meta,
    )


class _Resolver:
    """Exact-match identity resolution, cached per batch. Ambiguous or unknown stays None."""

    def __init__(self, db: Session):
        self.db, self.emp_cache, self.asset_cache = db, {}, {}

    def employee(self, actor: str | None):
        if not actor:
            return None
        key = actor.strip().lower()
        if key not in self.emp_cache:
            rows = set(
                self.db.scalars(
                    select(Employee.id).where(
                        (func.lower(Employee.email) == key)
                        | (Employee.oidc_subject == actor.strip())
                    )
                ).all()
            )
            self.emp_cache[key] = rows.pop() if len(rows) == 1 else None
        return self.emp_cache[key]

    def asset(self, source: str, agent_id):
        if not agent_id:
            return None
        key = (source, str(agent_id))
        if key not in self.asset_cache:
            rows = self.db.scalars(
                select(Asset.id).where(Asset.upstream_ids[source].astext == str(agent_id))
            ).all()
            self.asset_cache[key] = rows[0] if len(rows) == 1 else None
        return self.asset_cache[key]


@dataclass
class IngestResult:
    inserted: int = 0
    duplicates: int = 0
    rejected: int = 0
    cases: int = 0


def persist(
    db: Session,
    connector: str,
    events: list[NormalizedEvent],
    next_cursor: str | None,
    case_min_severity: str | None = None,
    now: datetime | None = None,
) -> IngestResult:
    """Store events, open cases, move the cursor, commit once. On any error nothing is kept."""
    now = now or datetime.now(UTC)
    result, resolver = IngestResult(), _Resolver(db)
    min_rank = SEVERITIES.index(case_min_severity) if case_min_severity else None
    try:
        for raw in events:
            try:
                ev = normalize(raw, now)
            except RejectedEvent:
                result.rejected += 1
                continue
            employee_id = ev.employee_id or resolver.employee(ev.actor)
            asset_id = ev.asset_id or resolver.asset(ev.source, ev.metadata.get("agent_id"))
            new_id = db.execute(
                insert(SecurityEvent)
                .values(
                    schema_version=ev.schema_version,
                    source=ev.source,
                    source_event_id=ev.source_event_id,
                    employee_id=employee_id,
                    asset_id=asset_id,
                    event_type=ev.event_type,
                    severity=ev.severity,
                    actor=ev.actor,
                    resource=ev.resource,
                    occurred_at=ev.occurred_at,
                    received_at=ev.received_at,
                    classification=ev.classification,
                    retention_policy=ev.retention_policy,
                    metadata=ev.metadata,
                )
                .on_conflict_do_nothing(index_elements=["source", "source_event_id"])
                .returning(SecurityEvent.id)
            ).scalar()
            if new_id is None:
                result.duplicates += 1
                continue
            result.inserted += 1
            if min_rank is not None and SEVERITIES.index(ev.severity) >= min_rank:
                create_case_from_event(db, db.get(SecurityEvent, new_id))
                result.cases += 1
        stats = {
            "inserted": result.inserted,
            "duplicates": result.duplicates,
            "rejected": result.rejected,
        }
        _advance(db, connector, next_cursor, now, stats)
        if result.cases:
            audit.record(db, None, "ingest.cases_opened", "connector", connector, after=stats)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


def _checkpoint(db: Session, name: str) -> ConnectorCheckpoint:
    cp = db.get(ConnectorCheckpoint, name)
    if cp is None:
        cp = ConnectorCheckpoint(name=name, capabilities={})
        db.add(cp)
    return cp


def _advance(db: Session, connector: str, cursor: str | None, now: datetime, stats: dict) -> None:
    cp = _checkpoint(db, connector)
    if cursor is not None:
        cp.cursor = cursor
    cp.last_attempt_at = cp.last_success_at = now
    cp.last_error = None
    cp.capabilities = {**(cp.capabilities or {}), "stats": stats}
    db.flush()


def record_probe(db: Session, name: str, capabilities: dict | None, now: datetime | None = None):
    """Mark a successful non-event poll (revocation-only or snapshot connectors). Commits."""
    now = now or datetime.now(UTC)
    cp = _checkpoint(db, name)
    cp.last_attempt_at = cp.last_success_at = now
    cp.last_error = None
    if capabilities is not None:
        cp.capabilities = {**(cp.capabilities or {}), **capabilities}
    db.commit()


def record_error(db: Session, name: str, error: str, now: datetime | None = None) -> None:
    """Make a failure visible on the connector health page. Keeps cursor and last success."""
    db.rollback()
    cp = _checkpoint(db, name)
    cp.last_attempt_at = now or datetime.now(UTC)
    cp.last_error = redact(error)[:1000]
    db.commit()
