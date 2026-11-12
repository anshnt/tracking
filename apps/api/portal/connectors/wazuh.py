"""Wazuh read adapter: alerts from the Wazuh indexer (OpenSearch _search API) -> security events.

Env: WAZUH_ENABLED, WAZUH_URL, WAZUH_USERNAME, WAZUH_PASSWORD, WAZUH_INDEX (default
wazuh-alerts-*), WAZUH_CASE_MIN_SEVERITY (default high; "none" disables automatic cases).

Cursor = ISO timestamp of the newest alert fetched. The query is "timestamp >= cursor" so the
cursor minus an overlap window is re-read next time and dropped by dedup; nothing is lost to equal timestamps.
"""

from datetime import UTC, datetime, timedelta

import httpx

from portal.connectors.base import EventSource, NormalizedEvent
from portal.connectors.http import Cfg, SchemaError, Upstream

PAGE_SIZE = 500
MAX_PAGES = 10  # ponytail: >5000 alerts sharing one poll window drain over several polls


OVERLAP = timedelta(minutes=5)  # re-read this much; (source, source_event_id) dedup absorbs repeats


def _overlap(cursor: str) -> str:
    try:
        return (_parse_ts(cursor) - OVERLAP).astimezone(UTC).isoformat()
    except (SchemaError, ValueError):
        return cursor


def severity_for_level(level: int) -> str:
    """Wazuh rule levels 0-15 -> portal severities."""
    if level >= 13:
        return "critical"
    if level >= 10:
        return "high"
    if level >= 7:
        return "medium"
    if level >= 4:
        return "low"
    return "info"


def _parse_ts(raw) -> datetime:
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        raise SchemaError(f"bad timestamp {raw!r}") from None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class WazuhSource(EventSource):
    name = "wazuh"

    def __init__(self, cfg: Cfg, transport: httpx.BaseTransport | None = None):
        self.index = cfg.get("index", "wazuh-alerts-*")
        self.case_min_severity = cfg.get("case_min_severity", "high").strip().lower()
        if self.case_min_severity == "none":
            self.case_min_severity = None
        auth = httpx.BasicAuth(cfg.get("username"), cfg.get("password"))
        self.up = Upstream(cfg.get("url"), auth=auth, transport=transport)
        self.last_rejected = 0

    def capabilities(self) -> dict:
        info = self.up.json("GET", "/")
        version = info.get("version", {}) if isinstance(info, dict) else {}
        return {
            "edition": version.get("distribution", "unknown"),
            "version": version.get("number", "unknown"),
        }

    def normalize_hit(self, hit: dict) -> NormalizedEvent:
        src = hit.get("_source")
        if not isinstance(src, dict):
            raise SchemaError("hit has no _source")
        rule = src.get("rule") or {}
        alert_id = src.get("id") or hit.get("_id")
        if not alert_id or rule.get("id") is None or not src.get("timestamp"):
            raise SchemaError("alert missing id, rule.id or timestamp")
        try:
            level = int(rule.get("level", 0))
        except (TypeError, ValueError):
            raise SchemaError("rule.level is not a number") from None
        agent = src.get("agent") or {}
        data = src.get("data") or {}
        return NormalizedEvent(
            source=self.name,
            source_event_id=str(alert_id),
            event_type="wazuh.alert",
            occurred_at=_parse_ts(src["timestamp"]),
            severity=severity_for_level(level),
            actor=data.get("dstuser") or data.get("srcuser"),
            resource=agent.get("name"),
            metadata={
                "rule_id": str(rule["id"]),
                "rule_groups": rule.get("groups") or [],
                "level": level,
                "agent_id": agent.get("id"),
                "agent_name": agent.get("name"),
                "src_ip": data.get("srcip"),
            },
        )

    def fetch(self, cursor: str | None):
        self.last_rejected = 0
        events: list[NormalizedEvent] = []
        for page in range(MAX_PAGES):
            body = {
                "size": PAGE_SIZE,
                "from": page * PAGE_SIZE,
                "sort": [{"timestamp": "asc"}],
                "query": {"range": {"timestamp": {"gte": _overlap(cursor)}}}
                if cursor
                else {"match_all": {}},
            }
            data = self.up.json("POST", f"/{self.index}/_search", json=body)
            try:
                hits = data["hits"]["hits"]
            except (KeyError, TypeError):
                raise SchemaError("search reply has no hits.hits") from None
            for hit in hits:
                try:
                    events.append(self.normalize_hit(hit))
                except SchemaError:
                    self.last_rejected += 1
            if len(hits) < PAGE_SIZE:
                break
        if not events:
            return [], cursor
        newest = min(max(e.occurred_at for e in events), datetime.now(UTC))  # no future cursor
        return events, newest.astimezone(UTC).isoformat()
