# Runbook: offboarding an employee

Owner: administrator owner (TBD). Target: new logins denied and active sessions terminated within 5 minutes of the action under normal connectivity (to be measured, scenario 8). Keycloak logout alone is not revocation.

Never wipe a personal device. Recover company equipment only.

## Portal side

1. A user with the `admin` or `it` role (as configured) creates an offboarding job in the portal with a reason and an idempotency key. The portal revokes the employee's portal sessions and sets the status so login is refused and every request returns 401.
2. The job has one step per subsystem. A step is `pending`, `running`, `succeeded`, `failed`, `manual_required` or `verified`. The job is `verified_complete` only when every step is `verified`. Until then it shows `incomplete`. Failed steps retry; failures show in the operations view.

## Operator procedure for steps with no automated adapter

Do these in order and record the time and your name for each in the step note.

1. **Identity.** Disable the Keycloak user. Revoke Keycloak sessions and offline tokens.
2. **Gateway session.** In the Guacamole admin interface, find active connections for the user, kill them, and remove the user's connection permissions.
3. **Underlying OS sessions.** On the employee VM (`loginctl list-sessions`, then `loginctl terminate-user <account>`; also check `who`, `ps -u <account>`). Kill background jobs, tmux/screen, cron, systemd user units and any independent SSH or RDP sessions. Lock the account (`usermod -L`, set an expired shell). Keep the VM and files for the retention decision.
4. **Credentials and tokens.** Revoke Git tokens, deploy keys, VPN peers (NetBird), application passwords and API tokens issued to the person. Rotate every shared credential they knew.
5. **Exports.** Cancel pending export requests and release grants for this employee in the portal.
6. **Ownership.** Reassign tasks, repositories and files to a named owner. Preserve only records authorised by the retention policy (check legal holds first).
7. **Assets.** Recover the company laptop. Mark the asset returned. Personal devices: nothing to do.

## Verify independently (do not trust step output alone)

- Keycloak: login attempt as the user is refused.
- Guacamole: no active connection, and a new connection attempt fails.
- VM: `loginctl list-sessions` shows none for the account; `ps -u <account>` empty.
- Tokens: a call with each revoked token returns 401 or 403.
- Portal: a request with the old session cookie returns 401.
- Mark each step `verified` and note the evidence. Record the elapsed time against the 5-minute target.

## Partial failure

Leave the job `incomplete`. Do not close it by hand. Fix the failing system, re-run the step (steps are idempotent), verify, then mark verified. If a step cannot be automated, say so in the owner handover rather than hiding it.
