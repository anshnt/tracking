# Runbook: incident response

Owner: security owner (TBD). Security evidence is kept separate from work assessment. A person reviews every case before any action against an employee; nothing is automated into discipline.

## Severity

| Level | Examples | First response |
| --- | --- | --- |
| High | Suspected data exfiltration, admin or gateway compromise, active session of a departed employee, audit tampering | Within 1 hour: contain, then notify the owner |
| Medium | Stale collector on a sensitive VM, repeated failed logins, export policy breach attempt | Same business day |
| Low | Single failed check, expected maintenance noise | Next business day |

## Flow

1. **Open a case** in the portal with severity, source, owner and evidence references (IDs and summaries, not raw content). Every case action is audited.
2. **Triage.** Is it real? Check the source event, collector health (unknown is not compliant) and the audit log. Note false positives so rules can be tuned.
3. **Contain.** Use the limited action catalogue: restrict the workspace, terminate sessions (see offboarding step 2 and 3 for the operator commands), disable the Keycloak account, revoke tokens, freeze pending exports.
4. **Preserve.** Keep the relevant events and audit entries; place a legal hold if there is a legal or HR matter. Do not copy employee content into chat or tickets.
5. **Eradicate and recover.** Rotate secrets that may have been exposed, patch, rebuild the VM from the template if needed, restore from backup per docs/runbooks/backup-restore.md.
6. **Communicate.** Tell the owner and the affected employee as policy and law require. Check whether a notification duty applies in the relevant country (open question 1).
7. **Close** with a rationale and lessons. Update the threat model, runbooks and detection rules if the incident showed a gap.

## Special cases

- **Admin misuse suspected:** the recovery approver, not the suspected admin, leads. Use the independent audit copy.
- **Portal compromise:** rotate the session secret and DB passwords, clear sessions, restore the audit table from the independent copy and compare.
- **Collector gap on a sensitive VM:** treat the device state as unknown, restrict new sensitive access, then find out why (docs/runbooks/connector-failures.md).
