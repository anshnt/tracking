"""Offboarding: ordered steps, partial failure surfaced, manual steps, idempotency."""

import uuid

import pytest
from sqlalchemy import select

from portal import jobs
from portal.connectors import base
from portal.connectors.base import FakeRevocationAdapter, StepResult
from portal.flows import offboarding as flow
from portal.models import (
    AuditEvent,
    Employee,
    ExportRequest,
    OffboardingJob,
    PortalSession,
    Workspace,
)
from portal.worker.__main__ import drain

MANUAL_STEPS = [n for n, k in flow.STEPS if k == flow.MANUAL]
ADAPTER_STEPS = [n for n, k in flow.STEPS if k == flow.ADAPTER]
HEADERS = {"Idempotency-Key": "off-1"}


@pytest.fixture
def adapters(monkeypatch):
    fakes = {n: FakeRevocationAdapter(n) for n in ADAPTER_STEPS}
    monkeypatch.setattr(base, "REVOCATION_ADAPTERS", dict(fakes))
    return fakes


@pytest.fixture
def operator(make_employee):
    return make_employee(roles=["employee", "it"])


def start(client, target, key="off-1", **over):
    data = {
        "employee_id": str(target.id),
        "confirm_employee_id": str(target.id),
        "reason": "left company",
    }
    data.update(over)
    return client.post("/api/v1/offboarding-jobs", json=data, headers={"Idempotency-Key": key})


def detail(client, jid):
    return client.get(f"/api/v1/offboarding-jobs/{jid}").json()


def steps(job):
    return {s["subsystem"]: s["status"] for s in job["steps"]}


def finish_manual(client, jid):
    for name in MANUAL_STEPS:
        r = client.post(
            f"/api/v1/offboarding-jobs/{jid}/steps/{name}/complete", json={"note": "done by IT"}
        )
        assert r.status_code == 200, r.text
    drain()


def test_happy_path_ordered_steps_and_verified_complete(
    client_for, operator, make_employee, adapters, db
):
    target = make_employee()
    tclient = client_for(target)  # a live session and a pending export
    assert tclient.get("/api/v1/me").status_code == 200
    db.add(
        ExportRequest(
            requester_id=target.id,
            object_ref="a.txt",
            classification="internal",
            recipient="x",
            purpose="y",
        )
    )
    db.add(Workspace(owner_id=target.id, name="vm", role_profile="dev", lifecycle_state="active"))
    db.commit()
    c = client_for(operator)
    resp = start(c, target)
    assert resp.status_code == 201, resp.text
    job = resp.json()
    assert db.scalar(select(Workspace.lifecycle_state)) == "suspended"
    assert [s["subsystem"] for s in job["steps"]] == [n for n, _ in flow.STEPS]
    # immediate effects, before the worker runs
    assert tclient.get("/api/v1/me").status_code == 401
    assert steps(job)["terminate_portal_sessions"] == "succeeded"
    assert steps(job)["revoke_export_grants"] == "succeeded"
    db.expire_all()
    assert db.get(Employee, target.id).status == "offboarding"
    assert db.scalar(select(ExportRequest.status)) == "cancelled"
    assert not db.scalars(
        select(PortalSession).where(
            PortalSession.employee_id == target.id, PortalSession.revoked_at.is_(None)
        )
    ).all()
    drain()
    job = detail(c, job["id"])
    assert job["status"] == "incomplete"  # manual steps outstanding
    assert steps(job)["rotate_shared_credentials"] == "manual_required"
    assert steps(job)["review_assets"] == "manual_required"
    assert steps(job)["verify"] == "pending"
    assert set(job["outstanding"]) == {*MANUAL_STEPS, "verify"}
    assert {"transfer_ownership", "revoke_app_passwords"} <= set(MANUAL_STEPS)
    finish_manual(c, job["id"])
    job = detail(c, job["id"])
    assert job["status"] == "verified_complete" and job["completed_at"] and job["outstanding"] == []
    assert steps(job)["verify"] == "succeeded"
    assert all(s["verified_at"] for s in job["steps"] if s["subsystem"] in ADAPTER_STEPS)
    db.expire_all()
    assert db.get(Employee, target.id).status == "offboarded"
    acts = set(db.scalars(select(AuditEvent.action).where(AuditEvent.target_id == job["id"])))
    assert {
        "offboarding.request",
        "offboarding.step_manual_done",
        "offboarding.verified_complete",
    } <= acts


def test_partial_failure_is_surfaced_and_retried(client_for, operator, make_employee, adapters, db):
    target = make_employee()
    adapters["revoke_vpn_peers"].result = StepResult("failed", "vpn api down")
    c = client_for(operator)
    jid = start(c, target).json()["id"]
    drain()
    job = detail(c, jid)
    assert job["status"] == "incomplete" and steps(job)["revoke_vpn_peers"] == "failed"
    assert (
        steps(job)["disable_identity"] == "succeeded"
        or steps(job)["disable_identity"] == "verified"
    )
    assert "vpn api down" in next(
        s["detail"] for s in job["steps"] if s["subsystem"] == "revoke_vpn_peers"
    )
    assert "revoke_vpn_peers" in job["outstanding"] and "verify" in job["outstanding"]
    # the runner retries with backoff, then parks the job as failed after max_attempts
    queued = db.scalars(select(jobs.Job).where(jobs.Job.kind == "offboarding.run")).all()
    assert any(j.status == "queued" and j.last_error for j in queued)
    # operator fixes the VPN; retry completes the step
    adapters["revoke_vpn_peers"].result = StepResult("succeeded", "peer removed")
    assert c.post(f"/api/v1/offboarding-jobs/{jid}/retry").status_code == 202
    drain()
    assert steps(detail(c, jid))["revoke_vpn_peers"] in ("succeeded", "verified")


def test_exception_in_adapter_is_a_failed_step(client_for, operator, make_employee, adapters):
    target = make_employee()

    def boom(_emp):
        raise TimeoutError("gateway timed out")

    adapters["terminate_gateway_sessions"].revoke = boom
    c = client_for(operator)
    jid = start(c, target).json()["id"]
    drain()
    job = detail(c, jid)
    assert steps(job)["terminate_gateway_sessions"] == "failed"
    assert "gateway timed out" in next(
        s["detail"] for s in job["steps"] if s["subsystem"] == "terminate_gateway_sessions"
    )
    assert job["status"] == "incomplete"


def test_unconfigured_adapter_is_never_complete(
    client_for, operator, make_employee, adapters, monkeypatch
):
    target = make_employee()
    reg = dict(adapters)
    del reg["terminate_os_sessions"]
    monkeypatch.setattr(base, "REVOCATION_ADAPTERS", reg)
    c = client_for(operator)
    jid = start(c, target).json()["id"]
    drain()
    finish_manual(c, jid)
    job = detail(c, jid)
    assert steps(job)["terminate_os_sessions"] == "skipped_not_configured"
    assert job["status"] == "incomplete" and "terminate_os_sessions" in job["outstanding"]
    # a person runs the tested operator procedure and records it
    r = c.post(
        f"/api/v1/offboarding-jobs/{jid}/steps/terminate_os_sessions/complete",
        json={"note": "killed xrdp sessions by hand, checked with qwinsta"},
    )
    assert r.status_code == 200
    drain()
    assert detail(c, jid)["status"] == "verified_complete"


def test_verification_failure_blocks_completion(client_for, operator, make_employee, adapters):
    target = make_employee()
    adapters["revoke_repo_tokens"].verified = False  # revoke() claims success, verify disagrees
    c = client_for(operator)
    jid = start(c, target).json()["id"]
    drain()
    finish_manual(c, jid)
    job = detail(c, jid)
    assert job["status"] == "incomplete"
    assert steps(job)["revoke_repo_tokens"] == "failed" and steps(job)["verify"] == "failed"
    assert "verification failed" in next(
        s["detail"] for s in job["steps"] if s["subsystem"] == "revoke_repo_tokens"
    )


def test_manual_step_endpoint_guards(client_for, operator, make_employee, adapters):
    target = make_employee()
    c = client_for(operator)
    jid = start(c, target).json()["id"]
    base_url = f"/api/v1/offboarding-jobs/{jid}/steps"
    note = {"note": "x"}
    assert c.post(f"{base_url}/verify/complete", json=note).status_code == 409
    assert c.post(f"{base_url}/terminate_portal_sessions/complete", json=note).status_code == 409
    assert c.post(f"{base_url}/disable_identity/complete", json=note).status_code == 409  # pending
    assert c.post(f"{base_url}/nope/complete", json=note).status_code == 404
    assert c.post(f"{base_url}/review_assets/complete", json={"note": ""}).status_code == 422
    drain()
    assert c.post(f"{base_url}/review_assets/complete", json=note).status_code == 200
    assert (
        c.post(f"{base_url}/review_assets/complete", json=note).status_code == 409
    )  # already done


def test_requires_privileged_role_reason_key_and_confirmation(
    client_for, operator, make_employee, adapters
):
    target = make_employee()
    plain = client_for(make_employee())
    assert start(plain, target).status_code == 403
    assert (
        start(client_for(make_employee(roles=["employee", "manager"])), target).status_code == 403
    )
    assert (
        start(client_for(make_employee(roles=["security", "approver"])), target).status_code == 403
    )
    assert plain.get("/api/v1/offboarding-jobs").status_code == 403
    c = client_for(operator)
    no_key = c.post(
        "/api/v1/offboarding-jobs",
        json={"employee_id": str(target.id), "confirm_employee_id": str(target.id), "reason": "x"},
    )
    assert no_key.status_code == 400
    assert start(c, target, reason="").status_code == 422
    assert start(c, target, reason="   ").status_code == 422
    assert start(c, target, confirm_employee_id=str(uuid.uuid4())).status_code == 422
    ghost = str(uuid.uuid4())
    assert start(c, target, employee_id=ghost, confirm_employee_id=ghost).status_code == 404
    assert start(c, operator).status_code in (403, 422)  # never yourself
    assert target.status == "active"
    assert (
        start(
            client_for(make_employee(roles=["employee", "admin"])), target, key="k-admin"
        ).status_code
        == 201
    )


def test_idempotency(client_for, operator, make_employee, adapters, db):
    target, other = make_employee(), make_employee()
    c = client_for(operator)
    first = start(c, target)
    again = start(c, target)
    assert first.status_code == 201 and again.status_code == 200
    assert first.json()["id"] == again.json()["id"]
    assert start(c, other).status_code == 409  # same key, different employee
    assert len(db.scalars(select(OffboardingJob)).all()) == 1
    # a fresh key for an employee who is already offboarding is refused
    assert start(c, target, key="off-2").status_code == 409


def test_list_and_detail(client_for, operator, make_employee, adapters):
    c = client_for(operator)
    jid = start(c, make_employee()).json()["id"]
    assert [j["id"] for j in c.get("/api/v1/offboarding-jobs").json()] == [jid]
    assert c.get(f"/api/v1/offboarding-jobs/{uuid.uuid4()}").status_code == 404
    assert c.post(f"/api/v1/offboarding-jobs/{uuid.uuid4()}/retry").status_code == 404


def test_never_wipes_devices():
    # there is no wipe, erase or reset step in the catalogue, and none can be added by a request
    assert not any(
        w in name for name, _ in flow.STEPS for w in ("wipe", "erase", "reset", "format")
    )


def test_manual_completion_of_adapter_step_is_still_verified(
    client_for, operator, make_employee, adapters
):
    target = make_employee()
    adapters["disable_identity"].result = StepResult("failed", "keycloak unreachable")
    adapters["disable_identity"].verified = False  # the account is in fact still live
    c = client_for(operator)
    jid = start(c, target).json()["id"]
    drain()
    c.post(
        f"/api/v1/offboarding-jobs/{jid}/steps/disable_identity/complete",
        json={"note": "disabled it by hand"},
    )
    finish_manual(c, jid)
    job = detail(c, jid)
    assert job["status"] == "incomplete"
    assert steps(job)["disable_identity"] == "failed"


def test_concurrent_replay_returns_the_existing_job_not_409(make_employee, operator, adapters):
    import threading
    import time

    from sqlalchemy import select as sel

    from portal.db import session_factory

    target = make_employee()
    result: dict = {}

    def second_request():
        with session_factory()() as s2:
            try:
                result["out"] = flow.create_job(
                    s2, s2.get(Employee, operator.id), target.id, target.id, "left", "race-key"
                )
            except Exception as exc:  # noqa: BLE001
                result["err"] = exc

    with session_factory()() as s1:
        emp = s1.scalars(sel(Employee).where(Employee.id == target.id).with_for_update()).one()
        t = threading.Thread(target=second_request)
        t.start()
        time.sleep(0.7)  # the second request has passed its replay check and is waiting on the lock
        job = OffboardingJob(
            employee_id=target.id,
            requested_by=operator.id,
            reason="left",
            idempotency_key="race-key",
        )
        s1.add(job)
        emp.status = "offboarding"
        s1.commit()
        job_id = job.id
        t.join(10)
    assert "err" not in result, result.get("err")
    prior, created = result["out"]
    assert prior.id == job_id and created is False
