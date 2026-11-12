"""Fleet (osquery) read-only adapter: hosts -> assets and posture observations.

Env: FLEET_ENABLED, FLEET_URL, FLEET_TOKEN (read-only API-only user).
Observations are evidence with a 15 minute expiry (PLAN.md section 11); a host that is missing a
signal is reported "unknown", never "compliant". Fleet hosts are company equipment by definition.
"""

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from portal.connectors.http import AuthRejected, Cfg, SchemaError, Upstream, register_secrets
from portal.models import Asset, PostureObservation
from portal.services.work import MAX_SKEW

PER_PAGE = 100
MAX_PAGES = 50  # ponytail: 5000 hosts; raise or cursor when the fleet grows
OBSERVATION_TTL = timedelta(minutes=15)


def _ts(raw) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


class FleetAdapter:
    name = "fleet"

    def __init__(self, cfg: Cfg, transport: httpx.BaseTransport | None = None):
        register_secrets(cfg.secrets())
        self.up = Upstream(
            cfg.get("url"),
            headers={"Authorization": f"Bearer {cfg.get('token')}"},
            transport=transport,
        )

    def capabilities(self) -> dict:
        version = self.up.json("GET", "/api/v1/fleet/version").get("version", "unknown")
        try:
            tier = self.up.json("GET", "/api/v1/fleet/config").get("license", {}).get("tier")
        except AuthRejected:  # token may not be allowed to read config: edition just unknown
            tier = None
        return {"edition": tier or "unknown", "version": version}

    def hosts(self) -> list[dict]:
        out: list[dict] = []
        for page in range(MAX_PAGES):
            data = self.up.json(
                "GET",
                "/api/v1/fleet/hosts",
                params={"page": page, "per_page": PER_PAGE, "order_key": "id"},
            )
            rows = data.get("hosts") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise SchemaError("hosts reply has no hosts list")
            out.extend(rows)
            if len(rows) < PER_PAGE:
                break
        return out

    def sync(self, db: Session, now: datetime | None = None) -> dict:
        """Upsert assets and add one observation per host seen since the last one. Commits."""
        now = now or datetime.now(UTC)
        stats = {"hosts": 0, "created": 0, "observations": 0, "rejected": 0}
        for host in self.hosts():
            if not isinstance(host, dict) or host.get("id") is None:
                stats["rejected"] += 1  # failed record: no id to key on
                continue
            stats["hosts"] += 1
            fid = str(host["id"])
            asset = db.scalars(
                select(Asset).where(Asset.upstream_ids["fleet"].astext == fid)
            ).first()
            if asset is None:
                asset = Asset(
                    name=str(host.get("hostname") or f"fleet-{fid}")[:200],
                    ownership="company",
                    os=host.get("platform"),
                    upstream_ids={"fleet": fid},
                    restricted={"hardware_serial": host.get("hardware_serial")},
                )
                db.add(asset)
                db.flush()
                stats["created"] += 1
            else:
                asset.os = host.get("platform") or asset.os
            seen = _ts(host.get("seen_time"))
            if seen is None or seen - now > MAX_SKEW:
                continue  # unparseable or host clock in the future: not evidence, and never stored
            last = db.scalars(
                select(PostureObservation.observed_at)
                .where(
                    PostureObservation.asset_id == asset.id, PostureObservation.source == "fleet"
                )
                .order_by(PostureObservation.observed_at.desc())
                .limit(1)
            ).first()
            if last is not None and last >= seen:
                continue
            enc = host.get("disk_encryption_enabled")
            state = "unknown" if enc is None else "compliant" if enc else "noncompliant"
            db.add(
                PostureObservation(
                    asset_id=asset.id,
                    source="fleet",
                    observed_at=seen,
                    received_at=now,
                    expires_at=seen + OBSERVATION_TTL,
                    state=state,
                    checks={"disk_encryption": enc, "status": host.get("status")},
                )
            )
            stats["observations"] += 1
        db.commit()
        return stats

    poll = sync
