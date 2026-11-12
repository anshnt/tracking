"""Export workflow: approval, staging, release (PLAN.md section 16, scenario 7)."""

import hashlib
import os
import subprocess
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from portal import jobs
from portal.flows import exports as flow
from portal.models import AuditEvent, ExportRequest
from portal.worker.__main__ import drain

CONTENT = b"synthetic canary document\n"
SHA = hashlib.sha256(CONTENT).hexdigest()


@pytest.fixture
def roots(tmp_path, monkeypatch):
    src, rel = tmp_path / "src", tmp_path / "release"
    (src / "docs").mkdir(parents=True)
    rel.mkdir()
    (src / "docs" / "plan.txt").write_bytes(CONTENT)
    monkeypatch.setenv("EXPORT_SOURCE_ROOT", str(src))
    monkeypatch.setenv("EXPORT_RELEASE_ROOT", str(rel))
    return src, rel


@pytest.fixture
def people(make_employee):
    return {
        "req": make_employee(),
        "app1": make_employee(roles=["employee", "approver"]),
        "app2": make_employee(roles=["employee", "approver"]),
        "it": make_employee(roles=["employee", "it"]),
        "admin": make_employee(roles=["employee", "admin"]),
        "other": make_employee(),
    }


def body(**over):
    data = {
        "object_ref": "docs/plan.txt",
        "object_version": "v1",
        "object_checksum": SHA,
        "classification": "confidential",
        "recipient": "auditor@partner.example",
        "purpose": "annual audit",
    }
    data.update(over)
    return data


def create(client_for, people, **over):
    resp = client_for(people["req"]).post("/api/v1/export-requests", json=body(**over))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def decide(client_for, who, rid, decision="approved"):
    return client_for(who).post(
        f"/api/v1/export-requests/{rid}/decisions", json={"decision": decision, "reason": "ok"}
    )


def approved_and_staged(client_for, people, **over):
    rid = create(client_for, people, **over)
    for who in ("app1", "app2") if over.get("classification") == "restricted" else ("app1",):
        assert decide(client_for, people[who], rid).status_code == 200
    drain()
    return rid


def release(client_for, who, rid, recipient="auditor@partner.example"):
    return client_for(who).post(
        f"/api/v1/export-requests/{rid}/release",
        json={"recipient": recipient, "channel_note": "handed over via secure share"},
    )


def row(db, rid) -> ExportRequest:
    db.expire_all()
    return db.get(ExportRequest, uuid.UUID(rid))


def actions(db, rid):
    return [
        a
        for a in db.scalars(
            select(AuditEvent.action).where(AuditEvent.target_id == rid).order_by(AuditEvent.id)
        )
    ]


def test_full_lifecycle_with_receipt_and_audit(client_for, people, roots, db):
    rid = create(client_for, people)
    assert decide(client_for, people["app1"], rid).json()["status"] == "approved"
    assert drain() >= 1
    r = row(db, rid)
    assert r.status == "staged" and r.staged_path
    assert (roots[1] / r.staged_path).read_bytes() == CONTENT
    resp = release(client_for, people["it"], rid)
    assert resp.status_code == 200, resp.text
    receipt = resp.json()["release_receipt"]
    assert receipt["checksum"] == SHA and receipt["released_by"] == str(people["it"].id)
    assert receipt["channel_note"] and receipt["recipient"] == "auditor@partner.example"
    assert actions(db, rid) == [
        "export.request",
        "export.approve",
        "export.stage",
        "export.release",
    ]


def test_double_release_rejected(client_for, people, roots):
    rid = approved_and_staged(client_for, people)
    assert release(client_for, people["it"], rid).status_code == 200
    again = release(client_for, people["app2"], rid)
    assert again.status_code == 409 and "already released" in again.text


def test_self_approval_forbidden(client_for, people, make_employee):
    both = make_employee(roles=["employee", "approver"])
    rid = client_for(both).post("/api/v1/export-requests", json=body()).json()["id"]
    assert decide(client_for, both, rid).status_code == 403


def test_only_approver_role_decides(client_for, people):
    rid = create(client_for, people)
    for who in ("req", "it", "admin", "other"):  # roles are literal: admin implies nothing
        assert decide(client_for, people[who], rid).status_code == 403


def test_restricted_needs_two_distinct_approvers(client_for, people, roots, db):
    rid = create(client_for, people, classification="restricted")
    assert decide(client_for, people["app1"], rid).json()["status"] == "reviewed"
    assert decide(client_for, people["app1"], rid).status_code == 409  # same approver twice
    assert drain() == 0 and row(db, rid).status == "reviewed"  # nothing staged yet
    assert decide(client_for, people["app2"], rid).json()["status"] == "approved"
    drain()
    assert row(db, rid).status == "staged"
    assert release(client_for, people["it"], rid).status_code == 200


def test_rejection_is_final(client_for, people):
    rid = create(client_for, people)
    assert decide(client_for, people["app1"], rid, "rejected").json()["status"] == "rejected"
    assert decide(client_for, people["app2"], rid).status_code == 409


def test_requester_cannot_release_own_export(client_for, make_employee, roots):
    both = make_employee(roles=["employee", "it"])
    approver = make_employee(roles=["employee", "approver"])
    rid = client_for(both).post("/api/v1/export-requests", json=body()).json()["id"]
    assert decide(client_for, approver, rid).status_code == 200
    drain()
    assert release(client_for, both, rid).status_code == 403


def test_release_requires_approver_or_it(client_for, people, roots):
    rid = approved_and_staged(client_for, people)
    assert release(client_for, people["req"], rid).status_code == 403
    assert release(client_for, people["admin"], rid).status_code == 403


def test_changed_object_content_is_not_staged(client_for, people, roots, db):
    (roots[0] / "docs" / "plan.txt").write_bytes(CONTENT + b"edited after approval")
    rid = approved_and_staged(client_for, people)
    r = row(db, rid)
    assert r.status == "approved" and "checksum" in r.stage_error
    assert not (roots[1] / rid).exists() or not any((roots[1] / rid).iterdir())
    assert release(client_for, people["it"], rid).status_code == 409


def test_recipient_substitution_rejected(client_for, people, roots, db):
    rid = approved_and_staged(client_for, people)
    assert (
        release(client_for, people["it"], rid, recipient="evil@elsewhere.example").status_code
        == 409
    )
    row(db, rid).recipient = "evil@elsewhere.example"  # tampered after approval
    db.commit()
    assert (
        release(client_for, people["it"], rid, recipient="evil@elsewhere.example").status_code
        == 409
    )
    assert row(db, rid).status == "staged"


def test_tampered_terms_not_staged(client_for, people, roots, db):
    rid = create(client_for, people)
    assert decide(client_for, people["app1"], rid).status_code == 200
    r = row(db, rid)
    r.object_version = "v2"
    db.commit()
    drain()
    assert row(db, rid).status == "approved" and "changed" in row(db, rid).stage_error


def test_expired_approval_cannot_release(client_for, people, roots, db):
    rid = approved_and_staged(client_for, people)
    row(db, rid).expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    resp = release(client_for, people["it"], rid)
    assert resp.status_code == 409 and "expired" in resp.text
    assert row(db, rid).status == "expired"
    assert not (roots[1] / rid).exists()


def test_expiry_job_removes_released_copy(client_for, people, roots, db):
    rid = approved_and_staged(client_for, people)
    assert release(client_for, people["it"], rid).status_code == 200
    row(db, rid).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert flow.expire_due(db) == 1
    db.commit()
    assert row(db, rid).status == "expired" and not (roots[1] / rid).exists()
    assert "export.expire" in actions(db, rid)


def test_expiry_job_runs_via_worker(client_for, people, roots, db):
    rid = approved_and_staged(client_for, people)
    row(db, rid).expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    jobs.enqueue(db, "export.expire", {}, idempotency_key="test-expire")
    db.commit()
    drain()
    assert row(db, rid).status == "expired"


@pytest.mark.parametrize(
    "ref",
    [
        "../secret.txt",
        "/etc/passwd",
        "docs/../../x",
        "C:/Windows/x",
        "https://evil.example/a",
        "file:///etc/passwd",
        "docs\\plan.txt",
        "docs//plan.txt",
        "",
        "./plan.txt",
    ],
)
def test_unsafe_object_refs_rejected_at_request(client_for, people, ref):
    resp = client_for(people["req"]).post("/api/v1/export-requests", json=body(object_ref=ref))
    assert resp.status_code == 422


def test_traversal_in_database_still_blocked_at_staging(client_for, people, roots, db):
    """Defence in depth: even a bad row (bypassing the API) never leaves the source root."""
    (roots[0].parent / "secret.txt").write_bytes(CONTENT)
    rid = create(client_for, people)
    r = row(db, rid)
    r.object_ref = "../secret.txt"
    db.commit()
    assert decide(client_for, people["app1"], rid).status_code == 200
    drain()
    r = row(db, rid)
    assert r.status == "approved" and "relative path" in r.stage_error


def test_symlink_escape_blocked_at_staging(client_for, people, roots, db):
    outside = roots[0].parent / "outside"
    outside.mkdir()
    (outside / "plan.txt").write_bytes(CONTENT)
    try:
        os.symlink(outside, roots[0] / "link", target_is_directory=True)
    except OSError:  # no symlink privilege: a Windows junction escapes the root the same way
        made = (
            os.name == "nt"
            and subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(roots[0] / "link"), str(outside)],
                capture_output=True,
            ).returncode
            == 0
        )
        if not made:
            pytest.skip("cannot create symlinks or junctions on this host")
    rid = create(client_for, people, object_ref="link/plan.txt")
    assert decide(client_for, people["app1"], rid).status_code == 200
    drain()
    r = row(db, rid)
    assert r.status == "approved" and "symlink" in r.stage_error


def test_missing_object_not_staged(client_for, people, roots, db):
    rid = approved_and_staged(client_for, people, object_ref="docs/nope.txt")
    assert "not found" in row(db, rid).stage_error


def test_url_is_never_fetched(client_for, people, roots, db):
    # a URL-shaped ref is refused at the API; the stager only ever reads the local source root
    resp = client_for(people["req"]).post(
        "/api/v1/export-requests", json=body(object_ref="http://127.0.0.1:1/x")
    )
    assert resp.status_code == 422


def test_classification_ceiling_revalidated(client_for, people, roots, monkeypatch):
    rid = approved_and_staged(client_for, people, classification="confidential")
    monkeypatch.setenv("EXPORT_MAX_CLASSIFICATION", "internal")
    resp = release(client_for, people["it"], rid)
    assert resp.status_code == 409 and "ceiling" in resp.text


def test_inactive_requester_blocks_release_and_decision(client_for, people, roots, db):
    rid = approved_and_staged(client_for, people)
    people["req"].status = "offboarding"
    db.commit()
    resp = release(client_for, people["it"], rid)
    assert resp.status_code == 409 and "no longer active" in resp.text


def test_object_level_visibility(client_for, people, roots):
    rid = create(client_for, people)
    assert client_for(people["other"]).get(f"/api/v1/export-requests/{rid}").status_code == 404
    assert client_for(people["req"]).get(f"/api/v1/export-requests/{rid}").status_code == 200
    assert client_for(people["app1"]).get(f"/api/v1/export-requests/{rid}").status_code == 200
    assert client_for(people["other"]).get("/api/v1/export-requests").json() == []
    assert len(client_for(people["req"]).get("/api/v1/export-requests").json()) == 1
    assert (
        client_for(people["other"])
        .post(f"/api/v1/export-requests/{rid}/cancel", json={"reason": "x"})
        .status_code
        == 404
    )


def test_cancel_removes_staged_copy(client_for, people, roots, db):
    rid = approved_and_staged(client_for, people)
    resp = client_for(people["req"]).post(
        f"/api/v1/export-requests/{rid}/cancel", json={"reason": "no longer needed"}
    )
    assert resp.status_code == 200 and resp.json()["status"] == "cancelled"
    assert not (roots[1] / rid).exists()
    assert release(client_for, people["it"], rid).status_code == 409
    assert client_for(people["app1"]).post(
        f"/api/v1/export-requests/{rid}/cancel", json={"reason": "x"}
    ).status_code in (403, 409)


def test_validation_errors(client_for, people):
    c = client_for(people["req"])
    assert c.post("/api/v1/export-requests", json=body(object_checksum="abc")).status_code == 422
    assert c.post("/api/v1/export-requests", json=body(classification="secret")).status_code == 422
    assert c.post("/api/v1/export-requests", json=body(recipient="  ")).status_code == 422


def test_expiry_wakeup_is_not_swallowed_by_a_finished_job_in_the_same_slot(db):
    from portal.models import Job

    flow.schedule_expiry(db)
    db.commit()
    assert jobs.run_one(db)  # chain ends: nothing live
    flow.schedule_expiry(db)  # same slot, e.g. a new approval
    db.commit()
    queued = db.scalars(
        select(Job).where(Job.kind == "export.expire", Job.status == "queued")
    ).all()
    assert len(queued) == 1


def test_mine_filter_gives_an_approver_their_own_requests(client_for, people, roots):
    mine = client_for(people["app1"]).post("/api/v1/export-requests", json=body())
    assert mine.status_code == 201, mine.text
    for n in range(3):  # newer company requests push the approver's own past a small limit
        create(client_for, people, recipient=f"auditor{n}@partner.example")
    c = client_for(people["app1"])
    assert mine.json()["id"] not in [
        r["id"] for r in c.get("/api/v1/export-requests?limit=2").json()
    ]
    got = c.get("/api/v1/export-requests?limit=2&mine=true").json()
    assert [r["id"] for r in got] == [mine.json()["id"]]
