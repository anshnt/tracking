# Validation test plan

The 18 required scenarios from PLAN.md section 16. Use synthetic canary documents and test credentials only, never real customer secrets. Record exact versions, configuration, timestamps, observed result and an evidence reference (internal storage) for every run. Label each control planned, configured, tested or failed.

Status values: `planned` means nothing has been run. `automated (unit/integration, not real infrastructure)` means repository tests exercise the portal code against a real PostgreSQL but not Keycloak, Guacamole, Wazuh, VMs or a firewall. That is not a pass for the real boundary; the real-boundary run is still needed. Where only part of a scenario has automated coverage, the status stays `planned` and the Automated coverage column says what exists.

No release on happy-path UI screenshots. Tests must exercise the real enforcement points and supported OS builds.

## Summary

| # | Scenario | Status | Automated coverage (apps/api/tests) |
| --- | --- | --- | --- |
| 1 | Identity | planned | Partial: disabled and offboarded employees refused at login and 401 (test_auth.py). MFA and Keycloak not tested |
| 2 | Isolation | planned | Partial: object-level checks, strangers get 404 (test_core.py, test_work_updates.py, test_devices.py). VM and network isolation not tested |
| 3 | Clipboard | planned | None |
| 4 | Transfer channels | planned | None |
| 5 | Egress | planned | None |
| 6 | Developer privileges | planned | None |
| 7 | Export | automated (unit/integration, not real infrastructure) | Software only: approval flow, no self-approval, two approvers for restricted, checksum and digest binding, expiry, double release 409 (test_exports.py). Real delivery not tested |
| 8 | Offboarding | automated (unit/integration, not real infrastructure) | Software only: ordered steps, idempotency key, retries, manual steps, stays incomplete until verified (test_offboarding.py, test_integration.py). Real adapters not run |
| 9 | Collector failure | planned | Partial: stale connector flag, redacted errors, failed-job queue, rate limit and credential rejection handling (test_operations.py, test_worker.py, test_connectors.py). Real collector outage not tested |
| 10 | Tamper controls | planned | None |
| 11 | Offline behavior | planned | None |
| 12 | Replay and ingestion | automated (unit/integration, not real infrastructure) | Software only: dedup, replay, reordered pages, clock skew clamp, cursor and events in one transaction, retry backoff (test_ingest.py, test_worker.py, test_core.py) |
| 13 | Privacy | planned | Partial: forbidden metadata keys dropped, URL query strings stripped, own-records view without metadata (test_ingest.py, test_me.py). Endpoint-side non-collection not tested |
| 14 | Manager scope | automated (unit/integration, not real infrastructure) | Software only: managers see direct reports only, no scores, admin cannot edit others' updates (test_overview.py, test_work_updates.py, test_core.py) |
| 15 | Recovery | planned | Partial: retention tombstones, legal holds, reapply after restore (test_retention.py). No real backup restored |
| 16 | Dependencies | planned | None |
| 17 | Concurrency | planned | Partial: idempotent job enqueue, double release 409, offboarding replay (test_core.py, test_exports.py, test_offboarding.py) |
| 18 | Negative evidence | planned | None |

## Scenarios

### 1. Identity

- Steps: (a) Try to sign in as an enrolled test user without completing MFA. (b) Complete MFA and sign in. (c) Disable the user in Keycloak, then attempt a new login and a new Guacamole connection. (d) List Keycloak and OS accounts and look for shared or generic accounts.
- Expected: MFA is required every login; the disabled user cannot start a new session; no shared accounts exist.
- Evidence: Keycloak authentication log, screenshot of the MFA prompt, account listing, failed-login entries with timestamps.
- Status: planned.

### 2. Isolation

- Steps: Sign in as employee A. Using A's session, request B's workspace, work updates, export request and security case by changing the object ID in the API and UI. From A's VM, try to reach B's VM by IP and RDP port.
- Expected: portal returns 404 or 403 with no existence leak; B's VM is unreachable; Guacamole shows A only A's connection.
- Evidence: HTTP transcripts with status codes, firewall deny counters, Guacamole connection list for A.
- Status: planned.

### 3. Clipboard

- Steps: In an A session, copy text, an image and a file from the remote desktop and paste locally, through every enabled client and protocol (browser Guacamole, any direct RDP path left open).
- Expected: every remote-to-local path is blocked; settings match policy.
- Evidence: Guacamole connection parameters export, screen recordings of the test (tester's own, synthetic data), local paste result.
- Status: planned.

### 4. Transfer channels

- Steps: Attempt printing and print-to-PDF, RDP drive redirection, SFTP, gateway file upload and download, session sharing, and direct SSH and RDP to the VM from the client network.
- Expected: each is disabled or unreachable; no path bypasses the policy.
- Evidence: connection parameters, port scan from the client network, denied attempts in gateway and firewall logs.
- Status: planned.

### 5. Egress

- Steps: From a sensitive VM, try personal cloud drive upload, webmail, external Git push, alternate DNS resolver, an HTTP redirect from an allowed domain, a raw outbound socket, and a personal account on an allowed domain.
- Expected: all denied except approved internal destinations.
- Evidence: firewall and proxy deny logs, packet capture at the egress firewall, tool output from each attempt.
- Status: planned. Note the known residual: an allowlisted multi-tenant service may still reach a personal tenant.

### 6. Developer privileges

- Steps: As an employee in the VM, look for the container runtime socket, host filesystem mounts, CI secrets, hypervisor management reachability and another workspace's credentials.
- Expected: none reachable or readable.
- Evidence: command output, mount table, network reachability results.
- Status: planned.

### 7. Export

- Steps: Run each as a request: self-approval; change the object version after approval; use an expired approval; change the recipient; path traversal in the object reference; an arbitrary URL as the source; release the same request twice.
- Expected: all rejected; each rejection audited; the legitimate flow releases once with a receipt.
- Evidence: API transcripts, audit events, receipt record.
- Status: planned.

### 8. Offboarding

- Steps: Start an interactive session and a long-running background job on a test VM. Offboard the test user. Independently check gateway, OS (`loginctl`, `ps`), application tokens, VPN peer and pending exports.
- Expected: new logins denied and sessions terminated within 5 minutes; the job shows incomplete until each step is verified; partial failure is visible.
- Evidence: timestamps from action to each verified step, command output, token rejection responses.
- Status: planned.

### 9. Collector failure

- Steps: Stop the Wazuh agent on a lab VM, then separately block its route. Watch the portal.
- Expected: state becomes unknown or stale, never compliant; alert is raised; recovery restores state.
- Evidence: portal screenshots with timestamps, alert record, collector logs.
- Status: planned.

### 10. Tamper controls

- Steps: As a standard company-laptop user, try to stop, disable or uninstall required services through ordinary supported actions. As IT, perform the maintenance through the audited exception workflow.
- Expected: the standard user cannot; IT can and the action is audited.
- Evidence: OS service permission output, audit entries, heartbeat gap visible in the portal.
- Status: planned. Requires a physical company laptop on each supported OS.

### 11. Offline behavior

- Steps: With stale posture (older than 15 minutes) or a stopped collector (older than 5 minutes), try new restricted local access. Check an existing session against the tested termination rule. Check BYOD access.
- Expected: new restricted local access fails closed; existing access follows the rule; BYOD uses the remote-only policy.
- Evidence: gate decision logs, timing, session termination record.
- Status: planned. Applies only if local-laptop access (L02) is built.

### 12. Replay and ingestion

- Steps: Feed duplicate and reordered events, paginate across a page boundary, revoke the connector credential, and force a pagination failure.
- Expected: no duplicate cases; revoked credential and pagination failures produce visible errors; the cursor advances only with persisted events.
- Evidence: row counts, connector health view, job `last_error`.
- Status: planned. Job retry and idempotent enqueue are covered by repository tests; connector ingestion is not yet.

### 13. Privacy

- Steps: Generate telemetry and logs while using URLs with query strings, windows with sensitive titles, clipboard content, a password field and a screenshot-like image. Search the database, logs and backups for those strings.
- Expected: none present.
- Evidence: search commands and empty results, field allowlist review.
- Status: planned.

### 14. Manager scope

- Steps: As a manager, request a direct report's work summary, a non-report's summary, security evidence and an employee data export.
- Expected: only direct reports' work summaries are visible; security evidence and other teams are denied; exports need authorisation.
- Evidence: HTTP transcripts, audit entries.
- Status: planned.

### 15. Recovery

- Steps: Follow docs/runbooks/backup-restore.md on a clean host. Rotate secrets, reapply tombstones and holds, measure time.
- Expected: services work; a tombstoned record is absent; a held record is present; RPO 24 h and RTO one business day are met or the miss is reported.
- Evidence: timing sheet, sampled checksums, tombstone and hold verification.
- Status: planned.

### 16. Dependencies

- Steps: Observe outbound traffic at the firewall with the internet disconnected, then restricted, during install, normal use, update and failure.
- Expected: every destination is inventoried with a purpose and owner; no silent fallback to hosted relays or analytics.
- Evidence: firewall logs, the dependency inventory.
- Status: planned.

### 17. Concurrency

- Steps: Five people work at once on real applications for a working session.
- Expected: acceptable experience; median and p95 login and interaction latency, CPU, memory, disk and application results documented.
- Evidence: metrics export, a short tester questionnaire.
- Status: planned.

### 18. Negative evidence

- Steps: Photograph a screen showing a canary document with a phone. On a lab BYOD host with screen capture running, view a remote session.
- Expected: the capture succeeds, demonstrating these are outside prevention claims; the owner handover states it.
- Evidence: the canary photo and capture, and docs/operations/owner-handover.md.
- Status: planned.
