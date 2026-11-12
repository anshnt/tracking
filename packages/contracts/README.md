# contracts

API schemas and event definitions shared by the API, worker, connectors and web app.

## openapi.json

`openapi.json` is exported from the API by `apps/api/scripts/export_openapi.py` (run `uv run python scripts/export_openapi.py` in `apps/api`).
It is generated, not hand-edited, and a test (`tests/test_contracts.py`) fails if it is stale.
The web client types in `apps/web/src/api/types.ts` are written by hand to match it.

`event.schema.json` is the JSON Schema of the normalized event below; the same test keeps its enums
and metadata allowlist in step with the code.

## Normalized event contract

Every connector (Wazuh, tracker, gateway, ...) converts upstream records into this shape before
anything is stored. In code it is `portal.connectors.base.NormalizedEvent`; it is persisted in
`security_events`.

| Field | Notes |
| --- | --- |
| `schema_version` | Integer, starts at 1. Bump on any breaking change to this contract. |
| `event_id` | Portal-assigned UUID (`security_events.id`). |
| `source` | Connector name, for example `wazuh`. |
| `source_event_id` | The upstream's own id. `(source, source_event_id)` is unique: this is the dedup key. |
| `employee_id` | Set only if identity resolved. Leave null when unresolved; never guess. |
| `asset_id` | Set only if the asset resolved; otherwise null. |
| `event_type` | Short dotted type, for example `auth.login_failed`. |
| `occurred_at` | When it happened upstream. UTC. |
| `received_at` | When the portal ingested it. UTC. |
| `classification` | `public`, `internal`, `confidential` or `restricted`. |
| `retention_policy` | Name of a `retention_rules.data_class`, for example `security-90d`. |
| `metadata` | Allowlisted keys only, redacted. No window titles, full URLs, clipboard text or secrets. |

Also stored with each event: `severity` (`info`, `low`, `medium`, `high`, `critical`), `actor`
and `resource`.

Correctness rules for implementers:

- Timestamps are UTC in storage; convert to the employee's timezone only for display.
- Deduplicate on source plus source event id. Handle pagination, replay, reordered events, clock
  skew, rate limits, schema changes and identity reassignment.
- Persisting events and advancing the connector cursor (`connector_checkpoints`) happen in one
  transaction.
- Use bounded exponential retry and leave failures visible in the failed-job queue.
- A successful API call is not proof that collection is complete: surface stale or unknown data
  with timestamps.
