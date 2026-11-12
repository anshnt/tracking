"""Kimai read-only adapter: timesheets -> per-user duration summary.

Env: KIMAI_ENABLED, KIMAI_URL, KIMAI_TOKEN (bearer API token of a user with view_other_timesheet).
Project time is optional and employee-entered (PLAN.md section 9): this only reads and sums.
Nothing is stored; callers ask for a date range when they need it.
"""

from datetime import date

import httpx

from portal.connectors.http import AuthRejected, Cfg, SchemaError, Upstream, register_secrets

PAGE = 200
MAX_PAGES = 25


class KimaiAdapter:
    name = "kimai"

    def __init__(self, cfg: Cfg, transport: httpx.BaseTransport | None = None):
        register_secrets(cfg.secrets())
        self.up = Upstream(
            cfg.get("url"),
            headers={"Authorization": f"Bearer {cfg.get('token')}"},
            transport=transport,
        )

    def capabilities(self) -> dict:
        info = self.up.json("GET", "/api/version")
        try:  # needs view_other_timesheet; absence is a capability, not a failure
            self.up.json("GET", "/api/timesheets", params={"size": 1, "user": "all"})
            all_users = True
        except AuthRejected:
            all_users = False
        return {
            "edition": "kimai",
            "version": info.get("version", "unknown"),
            "all_users_timesheets": all_users,
        }

    def summary(self, begin: date, end: date) -> dict[str, int]:
        """Seconds per Kimai user id (as string) with entries starting in [begin, end]."""
        totals: dict[str, int] = {}
        for page in range(1, MAX_PAGES + 1):
            rows = self.up.json(
                "GET",
                "/api/timesheets",
                params={
                    "begin": f"{begin.isoformat()}T00:00:00",
                    "end": f"{end.isoformat()}T23:59:59",
                    "user": "all",
                    "size": PAGE,
                    "page": page,
                },
            )
            if not isinstance(rows, list):
                raise SchemaError("timesheets reply is not a list")
            for row in rows:
                user = row.get("user") if isinstance(row, dict) else None
                seconds = row.get("duration") if isinstance(row, dict) else None
                if user is None or not isinstance(seconds, int):
                    continue  # running timers have no duration yet; skip, do not guess
                totals[str(user)] = totals.get(str(user), 0) + seconds
            if len(rows) < PAGE:
                break
        return totals
