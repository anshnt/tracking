"""packages/contracts must match the code: a stale openapi.json or event schema fails here."""

import json
from pathlib import Path

from portal.ingest import ALLOWED_METADATA
from portal.models import CLASSIFICATIONS, SEVERITIES
from scripts.export_openapi import TARGET, render

CONTRACTS = Path(TARGET).parent


def test_openapi_json_is_current():
    assert TARGET.read_text(encoding="utf-8") == render(), (
        "packages/contracts/openapi.json is stale: run "
        "`uv run python scripts/export_openapi.py` in apps/api and commit it"
    )


def test_event_schema_matches_the_code():
    schema = json.loads((CONTRACTS / "event.schema.json").read_text(encoding="utf-8"))
    props = schema["properties"]
    assert props["severity"]["enum"] == list(SEVERITIES)
    assert props["classification"]["enum"] == list(CLASSIFICATIONS)
    assert set(props["metadata"]["properties"]) == set(ALLOWED_METADATA)
