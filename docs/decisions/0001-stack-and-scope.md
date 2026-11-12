# ADR 0001: Stack and scope

Status: accepted for the pilot. Date: 2026-11-12. Spec: docs/plan/PLAN.md sections 1, 4, 10.

## Context

About five employees, all services on company-controlled servers. One named technical owner. The goal is to keep sensitive work in server workspaces, see work progress, and detect security problems, without building a surveillance product.

## Decision

| Concern | Choice | Why |
| --- | --- | --- |
| Identity and MFA | Keycloak | Self-hosted OIDC, TOTP or hardware keys, Apache-2.0 |
| Remote desktop gateway | Apache Guacamole with guacd | Browser access, per-path transfer controls, Apache-2.0 |
| Workspace OS | One Linux VM per employee with xrdp | Default compatibility trial; unprivileged OS account per person |
| Security telemetry | Wazuh | Logs, config assessment, file integrity; not content-aware DLP |
| Backups | restic to separate company-controlled storage | Encrypted, BSD-2-Clause, simple |
| Portal API | FastAPI (Python) | Small, typed, one language for API, worker and connectors |
| Portal UI | React + TypeScript | Existing mainstream stack |
| Portal data | PostgreSQL | One database for records, audit and the job queue |
| Background work | Postgres jobs table polled by one worker | Five users do not justify a broker; see below |

Optional, only when the stated need exists: Gitea (internal code and tasks), Fleet (company laptop inventory), Kimai (timesheets), self-hosted NetBird (private access network).

## Postgres job queue instead of a broker

Jobs are rows with `run_at`, attempts, an idempotency key and `last_error`. The worker claims due rows with `FOR UPDATE SKIP LOCKED`, retries with exponential backoff, and reclaims stuck jobs. Enqueueing happens in the same transaction as the business change, so there is no dual-write gap. Ceiling: a few hundred jobs a minute. We expect tens a day.

## Deliberately excluded

- Kubernetes, Kafka, Redis, a data lake, a separate analytics database.
- Any hosted SaaS for employee or business content: analytics, crash reporting, external LLMs, remote fonts, screenshot stores.
- Endpoint DLP written in-house, kernel drivers, universal app or browser interception, custom remote desktop protocols.
- Always-on screen recording, screenshots, keystroke or password capture, camera or microphone, clipboard-body capture, window titles, full URLs.
- Stealth, hidden processes, uninstall evasion, permission bypass, personal-device wipe.
- Employee ranking or any productivity score derived from activity signals.
- Forking upstream tools into this repo, or writing to vendor databases for routine lifecycle work.

## Consequences

- One production host is a single point of failure (RPO 24 h, RTO one business day for the pilot). See docs/operations/owner-handover.md.
- Wazuh is security evidence, not a leak-prevention guarantee. Prevention comes from the remote-workspace boundary and egress rules, and is only claimed once tested (docs/validation/test-plan.md).
- Each upstream tool is pinned and upgraded separately (docs/runbooks/patching-and-upgrades.md).
