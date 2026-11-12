# ADR 0002: Collection policy

Status: accepted as the engineering default; employee collection is blocked until the owner accepts it and a jurisdiction review is done (docs/decision-log.md). Spec: PLAN.md sections 9, 18.

## Decision

1. Collect only signals that answer a named business question. Progress comes from tasks, deliverables, blockers and a short employee-written update, not from activity telemetry.
2. Security monitoring of company systems and server workspaces is separate from work-activity collection, and security evidence is never used as a performance measure.
3. Allowlist, not blocklist. A signal is collected only if it is listed in `policies/` and in docs/privacy/collection-policy.md. Anything new needs a new policy version and a notice update first.
4. Policy versions are immutable (a database trigger blocks UPDATE and DELETE on `policy_versions`). A change is a new version with a hash, scope and reviewer.
5. The employee sees what is collected about them, can correct their own work updates (history kept), and is told which policy version applies.
6. Never collected, not even as an option: window titles, full URLs, clipboard bodies, screenshots, recordings, keystrokes, passwords, personal browsing, camera, audio.
7. No automated discipline or employment decision from any signal. A human reviews every case.

## Defaults (subject to jurisdiction review)

Raw work-activity events 30 days (off by default), security and session metadata 90 days, approval and privileged-action records 180 days, work summaries 12 months if justified. Legal holds override expiry. Restores reapply tombstones and holds.

## Consequences

Less data means fewer insights and fewer false alarms. Managers get deliverables and blockers, not a timeline of a person's day.
