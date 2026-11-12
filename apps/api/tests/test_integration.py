"""Wiring between areas: the worker sees every handler, the API builds adapters, steps find them."""

from fastapi.testclient import TestClient

from portal import jobs
from portal.connectors import base, registry
from portal.flows.offboarding import STEP_ADAPTER, adapter_for
from portal.handlers import load_all
from portal.main import create_app
from portal.worker import tasks  # noqa: F401  (registers the worker task handlers)


def test_worker_registers_every_job_kind():
    load_all()
    kinds = {
        "export.stage",
        "export.expire",
        "case.from_event",
        "offboarding.run",
        "scheduler.tick",
        "connector.poll",
        "retention.apply",
    }
    assert kinds <= set(jobs.HANDLERS)


def test_api_startup_registers_adapters_that_offboarding_steps_use(monkeypatch):
    monkeypatch.setenv("XRDP_ENABLED", "1")
    monkeypatch.setitem(base.REVOCATION_ADAPTERS, "stale", object())
    assert adapter_for("terminate_os_sessions") is None
    with TestClient(create_app()):  # entering the context runs the lifespan
        assert adapter_for("terminate_os_sessions").name == "xrdp"
    assert set(STEP_ADAPTER) <= {
        "disable_identity",
        "terminate_gateway_sessions",
        "terminate_os_sessions",
        "revoke_repo_tokens",
    }
    base.REVOCATION_ADAPTERS.pop("xrdp", None)
    registry.LIVE.clear()
