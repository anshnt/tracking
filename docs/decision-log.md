# Decision log (D01)

Separates what is confirmed from what is assumed and what is still open. Update this file when an input arrives; do not edit PLAN.md. Owner for every open item is TBD until the deployment owner names one.

## Confirmed inputs

| Input | Value | Source |
| --- | --- | --- |
| Headcount | Approximately five employees | Requester, 2026-11-12 |
| Hosting | Self-hosted on company-controlled servers | Requester, 2026-11-12 |

Nothing else is confirmed. Employee jurisdiction must not be inferred from chat timezones.

## Assumptions (working defaults, change when an open question is answered)

| Assumption | Changes the design when |
| --- | --- |
| Work is browser, documents and ordinary development | CAD, video, GPU, hardware access or Windows-only apps are needed |
| Company laptops are Windows first; BYOD uses a browser only | macOS or Linux local workflows are chosen |
| Servers are existing or purchased company-owned hardware | Rented dedicated servers are acceptable |
| No external storage or telemetry for employee or business content; approved updates may use the internet | Fully disconnected operation is required |
| Employees reach the office server reliably | Offline work or poor connectivity is essential |
| Linux VMs with xrdp are compatible with the applications | A Windows-only application exists (then licensing must be resolved first) |
| One technical owner and one recovery approver exist | Nobody can maintain services and answer alerts |
| RPO 24 hours, RTO one business day for the pilot | One day of downtime is unacceptable (buy a spare host) |
| Proposed thresholds: posture age 15 min, heartbeat age 5 min, offboarding revocation within 5 min | Pilot measurements say otherwise |

## Open questions to collect

| # | Question | Needed for | Owner | Status |
| --- | --- | --- | --- | --- |
| 1 | In which countries do employees work? | Notice, lawful basis, consultation, retention, cross-border flows | TBD | open |
| 2 | Which applications do employees use daily? | Linux VM compatibility, egress allowlist | TBD | open |
| 3 | Which data types are handled (customer, financial, regulated, source)? | Classification ceilings per workspace | TBD | open |
| 4 | What server hardware exists (CPU, RAM, disk, hypervisor)? | Sizing, concurrency trial | TBD | open |
| 5 | What are bandwidth and latency from each employee location? | Remote desktop viability | TBD | open |
| 6 | Where will backups live (second device, offsite copy)? | I06, RPO | TBD | open |
| 7 | What availability target is acceptable? | Spare host decision | TBD | open |
| 8 | Who is the administrator owner and the recovery approver? | Runbook roles, break-glass | TBD | open |
| 9 | What is the maximum budget? | Optional components, paid licenses, independent review | TBD | open |
| 10 | Which employees use company laptops and which use BYOD? | Local-device scope, posture policy | TBD | open |
| 11 | Is an internal tracker or Gitea already in use? | Work-summary adapter | TBD | open |
| 12 | Who approves collection categories and access (named owners)? | D02 sign-off, pilot gate | TBD | open |

## Gates

No real employee or production data is connected until the owner has accepted the collection policy, a jurisdiction review is complete, dependency exceptions are recorded and pilot results are accepted.
