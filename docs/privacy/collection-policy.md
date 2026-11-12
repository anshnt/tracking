# Collection policy

Version: DRAFT 0. Not in force. Requires named owner approval and jurisdiction review (docs/decision-log.md, open questions 1 and 12). Machine-readable allowlists belong in `policies/`; this document is the human version. Rationale: docs/decisions/0002-collection-policy.md.

## Principles

Collect only what answers a business question. Security monitoring is separate from work tracking. Security evidence is not a performance measure. No automated discipline.

## Categories

| Signal | Default | Applies to | Who can see | Retention (proposed) |
| --- | --- | --- | --- | --- |
| Tasks, review state, blockers, deliverable links | On | All | Employee, direct manager | 12 months |
| Daily work update (employee-written) | On | All | Employee, direct manager | 12 months, correction history kept |
| Project time | Optional, employee-entered | Where enabled | Employee, direct manager | 12 months |
| Workspace start and end, authentication events | On | Server workspaces | Security, operations; employee sees own | 90 days |
| Device patch, encryption, collector health | On | Company laptops and server VMs only | IT, security; employee sees own | 90 days, shown as unknown when stale |
| Export requests and privileged actions | On | All | Security and approval roles; employee sees own | 180 days |
| Application categories and idle time | Off | Disclosed sessions only, if ever enabled | Not decided | 30 days |
| Window titles, full URLs, clipboard text | Never | n/a | n/a | n/a |
| Screenshots, recordings | Never in the MVP | n/a | n/a | n/a |
| Keystrokes, passwords, personal browsing, camera, audio | Never | n/a | n/a | n/a |

## Scope by ownership

- Server workspaces: security and session metadata, as above.
- Company laptops: device health and approved security events from a disclosed, supported service.
- Personal devices (BYOD): browser session metadata at the gateway and internal application actions only. Nothing is installed on or inspected from the personal computer.

## Access

Employees see their own records. A manager sees work summaries of direct reports only, not security evidence or other teams. Security reviewers see cases and export requests. Administrators act through a separate identity, and every privileged action is in the audit log. Employee data exports are access controlled.

## Correction

An employee can add a correction to their work updates; the original is kept in the history. Corrections to other records go through the contact person.

## Retention and deletion

Expired records and derived copies are deleted by a scheduled job. Legal holds suspend deletion. Backups expire on a documented rotation, and a restore reapplies deletion tombstones and current holds (docs/runbooks/backup-restore.md).

## Changes

A new category, or any widening of access, needs a new immutable policy version, owner approval and an updated notice before collection starts.
