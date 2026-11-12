"""Gitea adapter.

Tracker: open issues/PRs assigned, review requests and blockers (by label) -> a small task
snapshot the overview shows. Primary progress evidence per PLAN.md section 9, so it is
read-only and cached for 60 seconds per login.
Revocation: delete the user's access tokens, then suspend the account.

Env: GITEA_ENABLED, GITEA_URL, GITEA_TOKEN (admin token; per-user reads use the Sudo header),
GITEA_USER_FIELD (default email_local), GITEA_BLOCKER_LABELS (default "blocked,blocker").
"""

import time
from urllib.parse import quote

import httpx

from portal.connectors.base import RevocationAdapter, StepResult
from portal.connectors.http import (
    AuthRejected,
    Cfg,
    ConnectorError,
    Upstream,
    login_for,
    register_secrets,
)

CACHE_SECONDS = 60
MAX_LISTED = 20
PAGE_SIZE = 50
MAX_PAGES = 10


class GiteaAdapter(RevocationAdapter):
    name = "gitea"

    def __init__(self, cfg: Cfg, transport: httpx.BaseTransport | None = None):
        self.user_field = cfg.get("user_field", "email_local")
        self.blocker_labels = {
            s.strip().lower() for s in cfg.get("blocker_labels", "blocked,blocker").split(",")
        }
        register_secrets(cfg.secrets())
        self.up = Upstream(
            cfg.get("url"),
            headers={"Authorization": f"token {cfg.get('token')}"},
            transport=transport,
        )
        self._cache: dict[str, tuple[float, dict]] = {}

    def capabilities(self) -> dict:
        data = self.up.json("GET", "/api/v1/version")
        return {"edition": "gitea", "version": data.get("version", "unknown")}

    # tracker -----------------------------------------------------------------------------
    def _search(self, login: str, **params) -> list[dict]:
        out: list[dict] = []
        for page in range(1, MAX_PAGES + 1):  # ponytail: 500 items per query, then truncated
            rows = self.up.json(
                "GET",
                "/api/v1/repos/issues/search",
                headers={"Sudo": login},
                params={"state": "open", "limit": PAGE_SIZE, "page": page, **params},
            )
            if not isinstance(rows, list):
                break
            out.extend(rows)
            if len(rows) < PAGE_SIZE:
                break
        return out

    @staticmethod
    def _brief(issue: dict) -> dict:
        repo = (issue.get("repository") or {}).get("full_name", "")
        return {
            "ref": f"{repo}#{issue.get('number')}",
            "title": str(issue.get("title", ""))[:120],
            "labels": [str(lb.get("name", "")) for lb in issue.get("labels") or []],
            "updated_at": issue.get("updated_at"),
        }

    def snapshot(self, login: str) -> dict:
        """Task snapshot for one Gitea login. Unknown fields in the reply are ignored."""
        hit = self._cache.get(login)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
        issues = self._search(login, type="issues", assigned="true")
        prs = self._search(login, type="pulls", assigned="true")
        reviews = self._search(login, type="pulls", review_requested="true")
        blocked = [
            self._brief(i)
            for i in issues + prs
            if self.blocker_labels
            & {str(lb.get("name", "")).lower() for lb in i.get("labels") or []}
        ]
        snap = {
            "issues_assigned": len(issues),
            "prs_assigned": len(prs),
            "reviews_requested": len(reviews),
            "blocked": blocked[:MAX_LISTED],
            "items": [self._brief(i) for i in (issues + prs)[:MAX_LISTED]],
        }
        self._cache[login] = (time.monotonic(), snap)
        return snap

    def snapshot_for(self, employee) -> dict:
        return self.snapshot(login_for(employee, self.user_field))

    def poll(self, db) -> dict:
        """Upsert task_snapshots (what the manager overview reads) for every active employee.

        ponytail: one search pair per employee per poll; fine for tens of people, batch or use
        webhooks beyond that. Issues that left the open search are marked done.
        """
        from datetime import UTC, date, datetime

        from sqlalchemy import select

        from portal.models import Employee, TaskSnapshot

        now, seen, failed = datetime.now(UTC), 0, 0
        for emp in db.scalars(select(Employee).where(Employee.status == "active")):
            try:
                login = login_for(emp, self.user_field)
            except ConnectorError:
                continue  # no email, nothing to map; leave its snapshots alone
            keep: set[str] = set()
            try:
                found = {
                    k: self._search(login, type=k, assigned="true") for k in ("issues", "pulls")
                }
            except ConnectorError:
                failed += 1  # leave this person's snapshots alone: no 'not in keep -> done'
                continue
            for kind in ("issues", "pulls"):
                for i in found[kind]:
                    ref = f"{(i.get('repository') or {}).get('full_name', '')}#{i.get('number')}"
                    labels = {str(lb.get("name", "")).lower() for lb in i.get("labels") or []}
                    hit = sorted(labels & self.blocker_labels)
                    state = (
                        "blocked" if hit else ("in_review" if kind == "pulls" else "in_progress")
                    )
                    due = (i.get("due_date") or "")[:10]
                    row = db.scalars(
                        select(TaskSnapshot).where(
                            TaskSnapshot.source == "gitea", TaskSnapshot.source_ref == ref
                        )
                    ).first() or TaskSnapshot(source="gitea", source_ref=ref)
                    row.assignee_id = emp.id
                    row.title = str(i.get("title", ""))[:200]
                    row.url = i.get("html_url")
                    row.state = state
                    row.blocker = hit[0] if hit else None
                    row.due_date = date.fromisoformat(due) if due else None
                    if kind == "pulls":
                        row.review_requested_at = row.review_requested_at or now
                        row.deliverables = [{"title": row.title, "url": row.url}]
                    row.synced_at = now
                    db.add(row)
                    keep.add(ref)
                    seen += 1
            for row in db.scalars(
                select(TaskSnapshot).where(
                    TaskSnapshot.source == "gitea",
                    TaskSnapshot.assignee_id == emp.id,
                    TaskSnapshot.state != "done",
                )
            ):
                if row.source_ref not in keep:
                    row.state = "done"
        db.commit()
        return {"tasks_synced": seen, "employees_failed": failed}

    # revocation --------------------------------------------------------------------------
    def _tokens(self, login: str) -> list[dict] | None:
        """None = this Gitea will not list another user's tokens (token auth, not basic auth)."""
        try:
            resp = self.up.request(
                "GET",
                f"/api/v1/users/{quote(login, safe='')}/tokens",
                headers={"Sudo": login},
                ok=(404, 405),
            )
        except AuthRejected:
            return None
        return None if resp.status_code in (404, 405) else resp.json()

    def _user(self, login: str) -> dict | None:
        resp = self.up.request("GET", f"/api/v1/users/{quote(login, safe='')}", ok=(404,))
        return None if resp.status_code == 404 else resp.json()

    def revoke(self, employee) -> StepResult:
        try:
            login = login_for(employee, self.user_field)
            q = quote(login, safe="")
            if self._user(login) is None:
                return StepResult(
                    "manual_required", f"no Gitea user '{login}'; confirm the account by operator"
                )
            tokens = self._tokens(login)
            for tok in tokens or []:
                self.up.request(
                    "DELETE",
                    f"/api/v1/users/{q}/tokens/{quote(str(tok['name']), safe='')}",
                    headers={"Sudo": login},
                )
            self.up.request(
                "PATCH",
                f"/api/v1/admin/users/{q}",
                json={"login_name": login, "source_id": 0, "prohibit_login": True, "active": False},
            )
            if tokens is None:
                return StepResult(
                    "manual_required",
                    "user suspended; this Gitea cannot list user tokens, rotate them by operator",
                )
            return StepResult("succeeded", f"deleted {len(tokens)} token(s) and suspended user")
        except ConnectorError as exc:
            return StepResult("failed", str(exc))

    def verify(self, employee) -> bool:
        try:
            login = login_for(employee, self.user_field)
            user = self._user(login)
            if user is None:
                return False  # unresolved is not revoked
            return user.get("prohibit_login") is True and self._tokens(login) == []
        except ConnectorError:
            return False
