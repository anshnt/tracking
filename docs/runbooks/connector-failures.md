# Runbook: connector failures

Applies to the connectors under `apps/api/portal/connectors` (Wazuh, tracker, gateway, optional Fleet and Kimai) and the worker that runs them. Owner: administrator owner (TBD).

## How failure shows up

- `GET /api/v1/operations/connectors` (IT only) shows each connector's cursor age, last successful sync and state. A successful call is not proof that collection is complete, so check the cursor age.
- Stale or missing data is displayed as unknown with a timestamp, never as compliant.
- A failed job has `status=failed` and a `last_error` after `max_attempts`. Jobs retry with exponential backoff from 5 seconds up to 3600. A job stuck in `running` for over 300 seconds is reclaimed.

## Triage

| Symptom | Likely cause | Action |
| --- | --- | --- |
| Cursor age grows, jobs retrying | Upstream down, network route cut, rate limit | Check the upstream service and route; the worker catches up on its own |
| Jobs failed with 401 or 403 | Revoked or expired connector credential | Issue a new least-privilege token, update the secret, re-enqueue the job. Do not reuse an admin token |
| Jobs failed with a schema error | Upstream version change | Pin the previous version or update the adapter and its compatibility test |
| Duplicate events or cases | Replay or pagination bug | Events deduplicate on source plus source event ID; confirm that and fix the adapter. Do not delete audit rows |
| Worker not running | Process or host down | `uv run python -m portal.worker`; check logs and DB connectivity |
| Device state unknown for a sensitive VM | Collector stopped or unreachable | Treat as noncompliant, restrict new sensitive access, investigate (docs/runbooks/incident-response.md) |

## Recovery

1. Fix the cause. Do not move the cursor by hand unless you accept losing the skipped range; record it if you do.
2. Re-enqueue failed jobs (handlers are idempotent).
3. Confirm the cursor advances and event counts look plausible against the upstream for the gap.
4. Note the gap window in the case or ops log so later reviews know data was missing.

## Not allowed

No writes to vendor databases as a workaround, no disabling of staleness display, and no silent fallback to a hosted service.
