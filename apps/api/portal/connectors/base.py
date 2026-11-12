"""Connector interfaces. Nothing vendor-specific lives here.

An EventSource pulls normalized events from one upstream (Wazuh, tracker, ...) page by page.
A RevocationAdapter removes one subsystem's access for an employee (Keycloak, gateway, git, ...).
Implementations register themselves with register_event_source / register_revocation_adapter.

Persisting events and advancing the cursor MUST happen in one transaction (PLAN.md section 10);
the connector job does that, the source only returns (events, next_cursor).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from portal.models import Employee


@dataclass
class NormalizedEvent:
    """The contract in packages/contracts/README.md. employee_id/asset_id stay None if unresolved."""

    source: str
    source_event_id: str
    event_type: str
    occurred_at: datetime
    schema_version: int = 1
    employee_id: Any = None
    asset_id: Any = None
    severity: str = "info"
    actor: str | None = None
    resource: str | None = None
    classification: str = "internal"
    retention_policy: str = "security-90d"
    received_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict = field(default_factory=dict)  # allowlisted keys only


class EventSource(ABC):
    name: str

    @abstractmethod
    def fetch(self, cursor: str | None) -> tuple[list[NormalizedEvent], str | None]:
        """Events after `cursor` (None = from the start) and the cursor to resume from."""


@dataclass
class StepResult:
    status: Literal["succeeded", "failed", "manual_required"]
    detail: str = ""


class RevocationAdapter(ABC):
    name: str  # becomes offboarding_steps.subsystem

    @abstractmethod
    def revoke(self, employee: Employee) -> StepResult:
        """Idempotent: safe to call again after a failure."""

    @abstractmethod
    def verify(self, employee: Employee) -> bool:
        """Independently confirm access is gone (not just that revoke() returned)."""


EVENT_SOURCES: dict[str, EventSource] = {}
REVOCATION_ADAPTERS: dict[str, RevocationAdapter] = {}


def register_event_source(source: EventSource) -> EventSource:
    EVENT_SOURCES[source.name] = source
    return source


def register_revocation_adapter(adapter: RevocationAdapter) -> RevocationAdapter:
    REVOCATION_ADAPTERS[adapter.name] = adapter
    return adapter


class FakeEventSource(EventSource):
    """Serves `events` in pages of `page_size`; the cursor is the next offset as a string."""

    def __init__(
        self,
        name: str = "fake",
        events: list[NormalizedEvent] | None = None,
        page_size: int = 100,
        fail: bool = False,
    ):
        self.name, self.events, self.page_size, self.fail = name, events or [], page_size, fail

    def fetch(self, cursor):
        if self.fail:
            raise RuntimeError("fake source failure")
        start = int(cursor or 0)
        page = self.events[start : start + self.page_size]
        return page, str(start + len(page))


class FakeRevocationAdapter(RevocationAdapter):
    def __init__(self, name: str = "fake", result: StepResult | None = None, verified: bool = True):
        self.name = name
        self.result = result or StepResult("succeeded", "revoked")
        self.verified = verified
        self.revoked: list = []

    def revoke(self, employee):
        self.revoked.append(employee.id)
        return self.result

    def verify(self, employee):
        return self.verified and employee.id in self.revoked
