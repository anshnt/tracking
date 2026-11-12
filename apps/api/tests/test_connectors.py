import json
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from portal.connectors import fleet, wazuh
from portal.connectors.fleet import FleetAdapter
from portal.connectors.gitea import GiteaAdapter
from portal.connectors.guacamole import GuacamoleAdapter
from portal.connectors.http import (
    AuthRejected,
    Cfg,
    ConnectorError,
    RateLimited,
    Upstream,
    redact,
    register_secrets,
)
from portal.connectors.keycloak import KeycloakAdapter
from portal.connectors.kimai import KimaiAdapter
from portal.connectors.wazuh import WazuhSource, severity_for_level
from portal.models import Asset, PostureObservation


def transport(handler):
    return httpx.MockTransport(handler)


def cfg(name, **kv):
    env = {f"{name.upper()}_{k.upper()}": v for k, v in kv.items()}
    return Cfg(name, env)


class Emp:
    id = "00000000-0000-0000-0000-000000000001"
    oidc_subject = "kc-user-1"
    email = "amy@example.invalid"


# ---- http plumbing ------------------------------------------------------------------------


def test_status_mapping_and_retry_after():
    def handler(req):
        return {
            "/rl": httpx.Response(429, headers={"Retry-After": "42"}),
            "/rl-big": httpx.Response(429, headers={"Retry-After": "999999"}),
            "/rl-junk": httpx.Response(429, headers={"Retry-After": "soon"}),
            "/denied": httpx.Response(401),
            "/boom": httpx.Response(503),
        }[req.url.path]

    up = Upstream("http://x", transport=transport(handler))
    with pytest.raises(RateLimited) as e:
        up.request("GET", "/rl")
    assert e.value.retry_after == 42
    with pytest.raises(RateLimited) as e:
        up.request("GET", "/rl-big")
    assert e.value.retry_after == 3600
    with pytest.raises(RateLimited) as e:
        up.request("GET", "/rl-junk")
    assert e.value.retry_after == 60
    with pytest.raises(AuthRejected):
        up.request("GET", "/denied")
    with pytest.raises(ConnectorError):
        up.request("GET", "/boom")


def test_redact_strips_secrets():
    register_secrets(["s3cr3t-value"])
    text = "Authorization: Bearer abcdef123456 url?token=xyz&a=1 s3cr3t-value password=hunter2"
    out = redact(text)
    for leaked in ("abcdef123456", "xyz", "s3cr3t-value", "hunter2"):
        assert leaked not in out


def test_network_error_message_is_redacted():
    def handler(req):
        raise httpx.ConnectError("failed for https://h/?token=LEAKME")

    with pytest.raises(ConnectorError) as e:
        Upstream("http://x", transport=transport(handler)).request("GET", "/")
    assert "LEAKME" not in str(e.value)


# ---- wazuh ----------------------------------------------------------------------------------


def alert(i, ts, level=10, **extra):
    src = {
        "id": f"A{i}",
        "timestamp": ts,
        "rule": {"id": "5710", "level": level, "groups": ["authentication_failed"], "future": 1},
        "agent": {"id": "001", "name": "ws-1"},
        "data": {"srcip": "10.0.0.5", "dstuser": "amy@example.invalid", "unknown_field": "x"},
    }
    src.update(extra)
    return {"_id": f"doc{i}", "_source": src}


def test_severity_levels():
    assert [severity_for_level(n) for n in (0, 4, 7, 10, 13)] == [
        "info",
        "low",
        "medium",
        "high",
        "critical",
    ]


def test_wazuh_paginates_uses_cursor_and_skips_bad_records(monkeypatch):
    monkeypatch.setattr(wazuh, "PAGE_SIZE", 2)
    seen = []
    pages = [
        [alert(1, "2026-11-10T10:00:00.000+0000"), alert(2, "2026-11-10T10:01:00.000+0000")],
        [
            alert(3, "2026-11-10T10:02:00.000Z", level=14),
            {"_id": "bad", "_source": {"id": "B", "rule": {"id": "1"}}},  # no timestamp
        ],
    ]

    def handler(req):
        if req.url.path == "/":
            return httpx.Response(
                200, json={"version": {"number": "4.9", "distribution": "opensearch"}}
            )
        body = json.loads(req.content)
        seen.append(body)
        i = body["from"] // 2
        return httpx.Response(200, json={"hits": {"hits": pages[i] if i < len(pages) else []}})

    src = WazuhSource(cfg("wazuh", url="http://w", username="u", password="p"), transport(handler))
    assert src.capabilities() == {"edition": "opensearch", "version": "4.9"}
    events, cursor = src.fetch(None)
    assert [e.source_event_id for e in events] == ["A1", "A2", "A3"]
    assert src.last_rejected == 1
    assert events[2].severity == "critical" and events[0].actor == "amy@example.invalid"
    assert "future" not in events[0].metadata and events[0].metadata["rule_id"] == "5710"
    assert cursor == "2026-11-10T10:02:00+00:00"
    assert "range" not in json.dumps(seen[0])
    src.fetch(cursor)
    assert seen[-1]["query"] == {
        "range": {"timestamp": {"gte": "2026-11-10T09:57:00+00:00"}}
    }  # cursor minus 5 min overlap


def test_wazuh_empty_keeps_cursor_and_default_case_threshold():
    def handler(req):
        return httpx.Response(200, json={"hits": {"hits": []}})

    src = WazuhSource(cfg("wazuh", url="http://w"), transport(handler))
    assert src.fetch("c1") == ([], "c1")
    assert src.case_min_severity == "high"
    assert (
        WazuhSource(cfg("wazuh", url="http://w", case_min_severity="none")).case_min_severity
        is None
    )


def test_wazuh_unexpected_reply_shape_is_an_error():
    src = WazuhSource(
        cfg("wazuh", url="http://w"), transport(lambda r: httpx.Response(200, json={"oops": 1}))
    )
    with pytest.raises(ConnectorError):
        src.fetch(None)


def test_wazuh_credentials_revoked_is_auth_rejected():
    src = WazuhSource(cfg("wazuh", url="http://w"), transport(lambda r: httpx.Response(401)))
    with pytest.raises(AuthRejected):
        src.fetch(None)


# ---- keycloak -------------------------------------------------------------------------------


class FakeKeycloak:
    def __init__(self, user_exists=True, search=None):
        self.search = search or {}
        self.enabled, self.sessions, self.exists, self.calls = True, ["s1"], user_exists, []

    def __call__(self, req):
        path, method = req.url.path, req.method
        self.calls.append((method, path))
        if path.endswith("/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "tok-abcdef"})
        assert req.headers["authorization"] == "Bearer tok-abcdef"
        base = "/admin/realms/corp/users/kc-user-1"
        if not self.exists and path.startswith(base):
            return httpx.Response(404)
        if path == base and method == "GET":
            return httpx.Response(200, json={"id": "kc-user-1", "enabled": self.enabled})
        if path == base and method == "PUT":
            self.enabled = json.loads(req.content)["enabled"]
            return httpx.Response(204)
        if path == base + "/logout":
            self.sessions = []
            return httpx.Response(204)
        if path == base + "/sessions":
            return httpx.Response(200, json=self.sessions)
        if path.endswith("/users/count"):
            return httpx.Response(200, json=3)
        if path.endswith("/users") and "exact" in req.url.params:
            hit = [k for k in ("username", "email") if k in req.url.params][0]
            return httpx.Response(200, json=self.search.get(hit, []))
        if path.endswith("/users"):
            return httpx.Response(
                200,
                json=[
                    {"id": "1", "username": "u", "email": "e", "enabled": True, "credentials": "x"}
                ],
            )
        return httpx.Response(500)


def keycloak(fake):
    return KeycloakAdapter(
        cfg(
            "keycloak",
            url="http://kc",
            realm="corp",
            client_id="portal",
            client_secret="shh-secret",
        ),
        transport(fake),
    )


def test_keycloak_revoke_disables_logs_out_and_verifies():
    fake = FakeKeycloak()
    adapter = keycloak(fake)
    assert adapter.verify(Emp) is False  # still enabled with a live session
    res = adapter.revoke(Emp)
    assert res.status == "succeeded"
    assert fake.enabled is False and fake.sessions == []
    assert adapter.verify(Emp) is True
    assert adapter.revoke(Emp).status == "succeeded"  # idempotent


def test_keycloak_verify_false_while_session_remains():
    fake = FakeKeycloak()
    adapter = keycloak(fake)
    adapter.revoke(Emp)
    fake.sessions = ["stuck"]
    assert adapter.verify(Emp) is False


def test_keycloak_missing_user_fails_closed_and_errors():
    # a 404 on the id must never read as revoked: the account may live under another key
    assert keycloak(FakeKeycloak(user_exists=False)).revoke(Emp).status == "manual_required"
    assert keycloak(FakeKeycloak(user_exists=False)).verify(Emp) is False
    down = KeycloakAdapter(
        cfg("keycloak", url="http://kc"), transport(lambda r: httpx.Response(503))
    )
    assert down.revoke(Emp).status == "failed" and down.verify(Emp) is False


def test_keycloak_finds_account_by_email_when_subject_is_not_a_keycloak_id():
    class Alice(Emp):
        oidc_subject = "alice"  # admin-created, not the Keycloak uuid

    fake = FakeKeycloak()

    def routed(req):
        if req.url.path.endswith("/users/alice"):
            return httpx.Response(404)
        if req.url.path.endswith("/users") and req.url.params.get("email"):
            return httpx.Response(200, json=[{"id": "kc-user-1", "enabled": fake.enabled}])
        if req.url.path.endswith("/users") and "exact" in req.url.params:
            return httpx.Response(200, json=[])  # username search misses
        return fake(req)

    adapter = keycloak(routed)
    assert adapter.verify(Alice) is False
    assert adapter.revoke(Alice).status == "succeeded" and fake.enabled is False
    assert adapter.verify(Alice) is True


def test_keycloak_list_users_and_capabilities():
    adapter = keycloak(FakeKeycloak())
    assert adapter.list_users() == [{"id": "1", "username": "u", "email": "e", "enabled": True}]
    assert adapter.capabilities()["users"] == 3


# ---- guacamole ------------------------------------------------------------------------------


class FakeGuac:
    def __init__(self, supported=True, user_exists=True):
        self.user_exists = user_exists
        self.active = {
            "c1": {"username": "AMY@example.invalid"},
            "c2": {"username": "bob@example.invalid"},
            "c3": {"username": "amy@example.invalid"},
        }
        self.supported, self.patches = supported, []

    def __call__(self, req):
        if req.url.path.endswith("/api/tokens"):
            return httpx.Response(200, json={"authToken": "gt-123456", "dataSource": "postgresql"})
        assert req.headers["guacamole-token"] == "gt-123456"
        if "/users/" in req.url.path:
            return httpx.Response(200 if self.user_exists else 404, json={})
        if not self.supported:
            return httpx.Response(404)
        if req.method == "GET":
            return httpx.Response(200, json=self.active)
        ops = json.loads(req.content)
        self.patches.append(ops)
        for op in ops:
            self.active.pop(op["path"].lstrip("/"))
        return httpx.Response(204)


def guac(fake):
    return GuacamoleAdapter(
        cfg("guacamole", url="http://g/guacamole", username="a", password="b"), transport(fake)
    )


def test_guacamole_kills_only_the_employees_connections():
    fake = FakeGuac()
    adapter = guac(fake)
    assert adapter.verify(Emp) is False
    res = adapter.revoke(Emp)
    assert res.status == "succeeded" and "2" in res.detail
    assert set(fake.active) == {"c2"}
    assert adapter.verify(Emp) is True
    assert adapter.revoke(Emp).status == "succeeded" and len(fake.patches) == 1


def test_guacamole_unknown_user_is_manual_required_and_not_verified():
    adapter = guac(FakeGuac(user_exists=False))
    assert adapter.revoke(Emp).status == "manual_required"
    assert adapter.verify(Emp) is False


def test_guacamole_unsupported_version_is_manual_required():
    adapter = guac(FakeGuac(supported=False))
    assert adapter.revoke(Emp).status == "manual_required"
    assert adapter.capabilities()["active_connections_api"] is False
    assert adapter.verify(Emp) is False  # offboarding stays incomplete until an operator acts


# ---- gitea ----------------------------------------------------------------------------------


class FakeGitea:
    def __init__(self, tokens_listable=True):
        self.suspended, self.tokens, self.listable = (
            False,
            [{"name": "ci"}, {"name": "ide"}],
            tokens_listable,
        )

    def __call__(self, req):
        path, q = req.url.path, dict(req.url.params)
        assert req.headers["authorization"] == "token admin-token"
        if path == "/api/v1/version":
            return httpx.Response(200, json={"version": "1.22.0"})
        if path == "/api/v1/repos/issues/search":
            assert req.headers["sudo"] == "amy"
            label = {"name": "blocked"}
            if q["type"] == "issues":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "number": 1,
                            "title": "Fix",
                            "repository": {"full_name": "o/r"},
                            "labels": [label],
                        },
                        {
                            "number": 2,
                            "title": "Other",
                            "repository": {"full_name": "o/r"},
                            "labels": [],
                        },
                    ],
                )
            if q.get("review_requested"):
                return httpx.Response(200, json=[{"number": 9, "repository": {"full_name": "o/r"}}])
            return httpx.Response(
                200,
                json=[
                    {"number": 5, "title": "PR", "repository": {"full_name": "o/r"}, "labels": []}
                ],
            )
        if path == "/api/v1/users/amy":
            return httpx.Response(200, json={"login": "amy", "prohibit_login": self.suspended})
        if path == "/api/v1/users/amy/tokens":
            return httpx.Response(200, json=self.tokens) if self.listable else httpx.Response(401)
        if path.startswith("/api/v1/users/amy/tokens/"):
            self.tokens = [t for t in self.tokens if t["name"] != path.rsplit("/", 1)[1]]
            return httpx.Response(204)
        if path == "/api/v1/admin/users/amy":
            assert json.loads(req.content)["prohibit_login"] is True
            self.suspended = True
            return httpx.Response(200, json={})
        return httpx.Response(500)


def gitea(fake):
    return GiteaAdapter(cfg("gitea", url="http://git", token="admin-token"), transport(fake))


def test_gitea_snapshot_counts_and_blockers_and_cache():
    adapter = gitea(FakeGitea())
    snap = adapter.snapshot_for(Emp)
    assert (
        snap["issues_assigned"] == 2
        and snap["prs_assigned"] == 1
        and snap["reviews_requested"] == 1
    )
    assert snap["blocked"] == [
        {"ref": "o/r#1", "title": "Fix", "labels": ["blocked"], "updated_at": None}
    ]
    adapter.up.client = None  # a second call must come from the cache, not the network
    assert adapter.snapshot("amy") is snap
    assert gitea(FakeGitea()).capabilities()["version"] == "1.22.0"


def test_gitea_revoke_deletes_tokens_suspends_and_verifies():
    fake = FakeGitea()
    adapter = gitea(fake)
    assert adapter.verify(Emp) is False
    res = adapter.revoke(Emp)
    assert res.status == "succeeded" and fake.tokens == [] and fake.suspended
    assert adapter.verify(Emp) is True


def test_gitea_unknown_user_is_manual_required_and_not_verified():
    adapter = gitea(lambda req: httpx.Response(404))
    assert adapter.revoke(Emp).status == "manual_required"
    assert adapter.verify(Emp) is False


def test_gitea_unlistable_tokens_is_manual_and_not_verified():
    fake = FakeGitea(tokens_listable=False)
    adapter = gitea(fake)
    assert adapter.revoke(Emp).status == "manual_required" and fake.suspended
    assert adapter.verify(Emp) is False


# ---- fleet ----------------------------------------------------------------------------------


def fleet_handler(hosts):
    def handler(req):
        if req.url.path == "/api/v1/fleet/version":
            return httpx.Response(200, json={"version": "4.50"})
        if req.url.path == "/api/v1/fleet/config":
            return httpx.Response(200, json={"license": {"tier": "free"}})
        page = int(req.url.params["page"])
        return httpx.Response(200, json={"hosts": hosts[page * 2 : page * 2 + 2]})

    return handler


def test_fleet_sync_creates_assets_and_observations_idempotently(db, monkeypatch):
    monkeypatch.setattr(fleet, "PER_PAGE", 2)
    seen = datetime.now(UTC).isoformat()
    hosts = [
        {
            "id": 1,
            "hostname": "lap-1",
            "platform": "windows",
            "seen_time": seen,
            "disk_encryption_enabled": True,
            "extra": 1,
        },
        {
            "id": 2,
            "hostname": "lap-2",
            "platform": "darwin",
            "seen_time": seen,
            "disk_encryption_enabled": False,
        },
        {"id": 3, "hostname": "lap-3", "platform": "ubuntu", "seen_time": seen},
        {"hostname": "no-id"},
    ]
    adapter = FleetAdapter(cfg("fleet", url="http://f", token="t"), transport(fleet_handler(hosts)))
    assert adapter.capabilities() == {"edition": "free", "version": "4.50"}
    stats = adapter.sync(db)
    assert stats == {"hosts": 3, "created": 3, "observations": 3, "rejected": 1}
    states = {
        a.name: o.state
        for a, o in db.execute(
            select(Asset, PostureObservation).join(
                PostureObservation, PostureObservation.asset_id == Asset.id
            )
        )
    }
    assert states == {"lap-1": "compliant", "lap-2": "noncompliant", "lap-3": "unknown"}
    obs = db.scalars(select(PostureObservation)).first()
    assert obs.expires_at - obs.observed_at == timedelta(minutes=15)
    again = adapter.sync(db)
    assert again["created"] == 0 and again["observations"] == 0  # same seen_time: nothing new


# ---- kimai ----------------------------------------------------------------------------------


def test_kimai_summary_and_capability_discovery():
    def handler(req):
        if req.url.path == "/api/version":
            return httpx.Response(200, json={"version": "2.1"})
        if req.url.params.get("size") == "1":
            return httpx.Response(403)
        return httpx.Response(
            200,
            json=[
                {"user": 7, "duration": 3600},
                {"user": 7, "duration": 1800},
                {"user": 8, "duration": None},  # running timer
                {"user": 9, "duration": 60, "extra": "ignored"},
            ],
        )

    adapter = KimaiAdapter(cfg("kimai", url="http://k", token="t"), transport(handler))
    caps = adapter.capabilities()
    assert caps["version"] == "2.1" and caps["all_users_timesheets"] is False
    assert adapter.summary(date(2026, 11, 1), date(2026, 11, 7)) == {"7": 5400, "9": 60}


def test_gitea_poll_fills_task_snapshots_for_the_overview(db, make_employee):
    from portal.models import TaskSnapshot

    amy = make_employee(email="amy@example.invalid")

    def handler(req):
        q = dict(req.url.params)
        if q.get("type") == "issues":
            return httpx.Response(
                200,
                json=[
                    {
                        "number": 1,
                        "title": "Fix",
                        "repository": {"full_name": "o/r"},
                        "labels": [{"name": "blocked"}],
                        "due_date": "2026-11-20T00:00:00Z",
                    }
                ],
            )
        return httpx.Response(
            200, json=[{"number": 5, "title": "PR", "repository": {"full_name": "o/r"}}]
        )

    adapter = GiteaAdapter(cfg("gitea", url="http://git", token="t"), transport(handler))
    assert adapter.poll(db) == {"tasks_synced": 2, "employees_failed": 0}
    rows = {r.source_ref: r for r in db.scalars(select(TaskSnapshot))}
    assert rows["o/r#1"].state == "blocked" and rows["o/r#1"].assignee_id == amy.id
    assert rows["o/r#1"].due_date == date(2026, 11, 20)
    assert rows["o/r#5"].state == "in_review" and rows["o/r#5"].review_requested_at
    adapter.poll(db)  # idempotent: upsert, not duplicate
    assert len(db.scalars(select(TaskSnapshot)).all()) == 2


def test_gitea_empty_email_fails_the_step():
    class NoMail:
        email, oidc_subject = "", "sub"

    assert gitea(FakeGitea()).revoke(NoMail).status == "failed"
    assert gitea(FakeGitea()).verify(NoMail) is False


def test_wazuh_cursor_never_runs_ahead_of_now():
    def handler(req):
        hits = [alert(1, "2999-01-01T00:00:00.000Z")]
        return httpx.Response(200, json={"hits": {"hits": hits}})

    src = WazuhSource(cfg("wazuh", url="http://w", username="u", password="p"), transport(handler))
    _, cursor = src.fetch(None)
    assert cursor <= datetime.now(UTC).isoformat()


def test_fleet_future_seen_time_is_not_recorded(db):
    future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    hosts = [{"id": 1, "hostname": "lap-1", "platform": "windows", "seen_time": future}]
    adapter = FleetAdapter(cfg("fleet", url="http://f", token="t"), transport(fleet_handler(hosts)))
    assert adapter.sync(db)["observations"] == 0
    hosts[0]["seen_time"] = datetime.now(UTC).isoformat()
    assert adapter.sync(db)["observations"] == 1  # a later honest row is not blocked
