# Release report

Date: 2026-11-12. Scope: the Work and Security Portal as described in `docs/plan/PLAN.md`. This is a software build plus lab-grade infrastructure code. Nothing in it has been run against real Keycloak, Guacamole, Wazuh, xrdp VMs, nftables hosts or a restic repository. It is not ready for employees.

## 1. Verification run (2026-11-12)

| Check | Result |
| --- | --- |
| `uv sync --frozen` (apps/api) | OK, 43 packages |
| `ruff check` | All checks passed |
| `alembic upgrade head`, `alembic check`, `downgrade base`, `upgrade head` (db `tracking_final`) | All succeeded; `check` reported no new operations; head is `0003` |
| `pytest -q` (TEST_DATABASE_URL on WSL Postgres 16, port 5433) | 218 passed, 0 failed (about 163 s) |
| `npm ci` (apps/web) | OK, 0 vulnerabilities reported |
| `npm test` | 1 file, 8 tests passed |
| `npm run build` (`tsc --noEmit` then vite) | OK; JS 314.79 kB (94.98 kB gzip), CSS 5.44 kB |
| `infra/tests/validate.py` (offline infra and policy checks) | OK after fixing CRLF line endings in `policies/collection-policy.yaml`; `nft` is not installed so the rendered ruleset was not syntax-checked |
| Em dash grep | Removed everywhere I may edit. One hit remains in `docs/plan/plan.html` (a protected path). The plan owner needs to fix it. |

Notes: a first full pytest run showed 15 failures and 3 errors because I accidentally ran two copies of the suite against the same database at once. Run alone, all 218 passed. Postgres 16 was used locally while infra pins 17.11. Web tests are 8 tests in one file; the UI is thinly covered.

## 2. Status definitions

- planned: nothing built or run.
- configured: code, config or documents exist; offline checks may have parsed them; not run on real infrastructure.
- tested: an automated test in this repo exercises the portal behaviour. For anything that needs real infrastructure the ceiling is "configured". Where a control has a portal half and an infrastructure half, the status is for the whole control and the portal half is noted.
- failed: a test or run failed. None at the end of this run.

## 3. Controls and backlog

| ID | Item | Status | Evidence and caveats |
| --- | --- | --- | --- |
| D01 | Applications, ownership, jurisdictions, data classes, inventory | configured | `docs/decision-log.md`, `policies/data-classification.yaml`. Many inputs are assumptions; owners are TBD. |
| D02 | Threat model and collection policy | configured | `docs/threat-model.md`, `docs/privacy/collection-policy.md`, `policies/collection-policy.yaml`. Policy versions and acknowledgement are exercised by `apps/api/tests/test_policies.py` and `test_me.py`, but no named owner has approved anything. |
| D03 | License, edition and dependency audit | configured | `docs/version-manifest.md`. No digests, no SBOM, no legal review. |
| I01 | Network zones, deny-by-default firewall | configured | Ansible nftables templates, rendered and asserted by `infra/tests/validate.py`. `nft -c` not run; no host tested. |
| I02 | Keycloak MFA and recovery | configured | Realm JSON invariants asserted offline. Portal OIDC login code is tested against fake tokens in `test_auth.py`, not against Keycloak. MFA in a real Keycloak was never run. Recovery and logout procedures are only documented. |
| I03 | Guacamole, guacd, xrdp VM | configured | Compose and Ansible roles. Not run. The `cert-fingerprints` format for 1.6.0 is unverified. |
| I04 | Transfer and egress restrictions | configured | Guacamole flags checked against `policies/guacamole-transfer-policy.yaml` offline; nftables output default-drop rendered. No clipboard, print, drive, SFTP or egress test run. |
| I05 | Wazuh and scoped telemetry | configured | Compose instructions and agent role. apt key and registration checksums are TODO placeholders. The portal-side reader is P05. |
| I06 | Encrypted independent backup and recovery | configured | restic and pg_dump scripts, `bash -n` only. No restore performed, RPO and RTO unmeasured. |
| I07 | Five-user concurrency trial | planned | Not started. |
| P01 | API/UI scaffold, migrations, authentication | tested | `test_auth.py` (login, CSRF, disabled and offboarded users refused, production refuses dev auth and placeholders), `test_core.py`, `test_contracts.py`; migration cycle run in section 1. |
| P02 | Object-level authorization and audit | tested | `test_core.py`, `test_admin.py`, `test_work_updates.py`, `test_workspaces.py` (cross-user ID substitution returns 404; privileged actions audited). |
| P03 | Employee policy and personal-record views | tested | `test_policies.py`, `test_me.py` (own records only, acknowledgement idempotent, correction history). |
| P04 | Work summary and tracker adapter | tested | `test_work_updates.py`, `test_overview.py` (no scores; managers see direct reports only), Gitea adapter in `test_connectors.py` against fakes. No real Gitea. |
| P05 | Wazuh read adapter and connector health | tested | `test_connectors.py`, `test_ingest.py`, `test_worker.py`, `test_operations.py` (dedup, pagination, cursor, stale flag, redacted errors) against fake HTTP. Not run against a real Wazuh. |
| P06 | Device/workspace inventory and posture model | tested | `test_devices.py`, `test_workspaces.py` (unknown distinct from compliant, BYOD not ingested, heartbeat-only or future-dated observation never compliant). |
| P07 | Export request, review, staged release | tested | `test_exports.py` (no self-approval, two approvers for restricted, checksum and recipient binding, expiry, double release 409). No real delivery channel. |
| P08 | Offboarding workflow and runbook | configured | Portal logic is exercised by `test_offboarding.py` and `test_integration.py` (ordered steps, idempotency key, stays incomplete until independently verified, fails closed when the upstream user is not found), but the real gateway, OS, Keycloak and VPN adapters were not run and the gateway session termination adapter is not built. Held at "configured" because the real revocation was never exercised. |
| P09 | Retention, holds, deletion, restore handling | tested | `test_retention.py` (expiry, legal holds, open-case evidence protected, tombstones reapplied after restore). No real restore. |
| Q01 | Security review and outbound-traffic verification | planned | Reviewer fixes were applied (section 6), but no outbound traffic was observed and no SBOM exists. |
| Q02 | Pilot rollout and rollback rehearsal | planned | Not started. |
| L01 | Fleet evaluation on company laptop | planned | `portal/connectors/fleet.py` exists and is unit tested with fakes; no laptop evaluated, no tamper tests. |
| L02 | Posture-aware local access gate | planned | Not built. |
| L03 | Kimai or optional work-session metrics | planned | Deliberately not built. |

## 4. The 18 validation scenarios

None has been run on real infrastructure. "Partial automated" means portal code is exercised by tests in `apps/api/tests`; that is not a pass for the real boundary.

| # | Scenario | Status | What exists |
| --- | --- | --- | --- |
| 1 | Identity | planned | Partial automated: disabled and offboarded users refused (`test_auth.py`). MFA and Keycloak not run. |
| 2 | Isolation | planned | Partial automated: object-level 404s (`test_core.py`, `test_work_updates.py`, `test_devices.py`, `test_workspaces.py`). No VM or network isolation test. |
| 3 | Clipboard | planned | Guacamole flags configured only. |
| 4 | Transfer channels | planned | Configured only. |
| 5 | Egress | planned | nftables rules rendered only. |
| 6 | Developer privileges | planned | Nothing. |
| 7 | Export | planned | Partial automated: `test_exports.py` covers self-approval, expiry, double release. Real delivery not run. |
| 8 | Offboarding | planned | Partial automated: `test_offboarding.py`, `test_integration.py`. The 5 minute target and real session termination not run. |
| 9 | Collector failure | planned | Partial automated: stale connector flag, heartbeat-only is unknown (`test_operations.py`, `test_devices.py`). No real agent stopped. |
| 10 | Tamper controls | planned | Audited maintenance exception exists (`test_devices.py`); no laptop tested. |
| 11 | Offline behavior | planned | Applies only if L02 is built. |
| 12 | Replay and ingestion | planned | Partial automated: dedup, reordered pages, cursor with events in one transaction, retry backoff (`test_ingest.py`, `test_worker.py`, `test_connectors.py`). Not against real Wazuh. |
| 13 | Privacy | planned | Partial automated: forbidden metadata dropped, URL query stripped (`test_ingest.py`, `test_me.py`). No endpoint-side or backup search. |
| 14 | Manager scope | planned | Partial automated: `test_overview.py`, `test_work_updates.py`. |
| 15 | Recovery | planned | Partial automated: `test_retention.py`. No backup restored. |
| 16 | Dependencies | planned | Inventory in `docs/version-manifest.md`; no traffic observed. |
| 17 | Concurrency | planned | Partial automated: idempotent enqueue, double release 409. No five-user session. |
| 18 | Negative evidence | planned | `docs/operations/owner-handover.md` states the limits; the photo and capture demonstration was not done. |

## 5. Residual risks

- No real enforcement boundary has been tested. Clipboard, transfer, egress and isolation claims rest on configuration only.
- A person can photograph a screen, memorise data, or use a personal account on an allowlisted multi-tenant service. These are outside what this build prevents.
- Posture and security signals depend on Wazuh and the collector heartbeat. Behaviour in a real outage is untested.
- Offboarding is only as good as its adapters. The real ones (gateway, OS sessions, VPN, application tokens) were not run, and the Guacamole session termination adapter does not exist.
- Infra code was only parsed and statically checked. Reviewers found many real bugs in it this run (backup SSH key format, backup firewall path, Guacamole schema init, realm flows, provisioning egress). Expect more on the first real run.
- Pinned image tags have no digests; the Gitea `28.3.0` tag is unverified; Wazuh and restic checksums are placeholders.
- psycopg is LGPL-3.0; review if the portal is distributed outside the company.
- Local tests ran on Postgres 16; production pins 17.11.
- Web UI test coverage is small (8 tests).
- `docs/plan/plan.html` still contains an em dash.

## 6. Fixes made by reviewers this run

- Web: manual "Mark done" no longer offered for system-only steps; export list scoping and truncation; offboarding name confirmation; team workspace posture shown; admin overview section.
- Infra: backup SSH path, key format and known_hosts; provisioning egress; Guacamole SAML redirect, guacadmin neutralisation, fingerprint format, orphan connection, schema init user; Caddy CA readability; guacd egress; Keycloak flows; compose secret rendering.
- Worker: offboarding fails closed when the upstream user is not found.
- API: OIDC identity, email and role handling; URL path injection; admin access to work data; login DoS and per-request row insertion; negative limits; retention of cancelled exports, evidence and audit events; tombstone reapplication; maintenance exceptions; Wazuh cursor and future dates; heartbeat and posture states; export expiry chain; stuck-job reclaim; concurrent correction history; naive datetimes; CSRF with bearer tokens; manual-step verification bypass; non-ASCII token errors; OpenAPI exposure; case evidence metadata; policy-driven categories; workspace owner state; double acknowledgement; idempotency replay; Gitea sync.

API fixes have tests in `apps/api/tests`. Infra and web fixes are checked only by `infra/tests/validate.py` and the 8 web tests.

## 7. Manual steps before anything real

1. Name the owners and answer the open items in `docs/decision-log.md`; approve the collection policy and employee notice.
2. Fill TODO placeholders: image digests, Wazuh apt key and registration checksums, `restic_sha256`, CHANGE_ME secrets. Set `PORTAL_ENV=production` so dev defaults refuse to start.
3. Verify the Gitea tag, the Guacamole `cert-fingerprints` format and the nft ruleset (`nft -c`).
4. Run `shellcheck` and the Ansible playbooks against lab hosts; run `docker compose config` and `docker build` somewhere Docker exists (not possible on the dev machine).
5. Fix the em dash in `docs/plan/plan.html`.

## 8. Next steps to a pilot

1. Stand up the lab: Keycloak with MFA, portal, Guacamole, one xrdp VM, firewall. Import the realm and run scenarios 1 to 6.
2. Stand up Wazuh and one agent; run scenarios 9, 12 and 13 and check posture end to end.
3. Run a restic backup and a restore on a clean host; measure RPO and RTO (I06, scenario 15).
4. Exercise offboarding with a real session and background job (scenario 8); build the gateway termination adapter.
5. Capture outbound traffic during install and use (scenario 16, Q01); produce digests and an SBOM.
6. Run a one-user pilot, then five users with real applications (I07, scenario 17); rehearse rollback and owner handover (Q02).
7. Only then consider L01 to L03.
