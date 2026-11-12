# Runbook: break-glass access

Use only when normal access is broken and waiting would cause real harm: Keycloak is down, all admins are locked out, or a restore needs access before identity exists. Break-glass is not a way around approvals. It never covers a personal device, and there is no device wipe.

## Who and where

- Two roles: the administrator owner and the recovery approver (both TBD). Neither may use it alone to release sensitive data.
- Break-glass credentials are sealed offline (paper or hardware key in a safe), not stored in any system an employee can reach, and not in this repository. Each use is a new rotation event.

## Procedure

1. **Declare.** The operator tells the recovery approver the reason and the system. The approver agrees (in writing, with time).
2. **Use.** Take the sealed credential. Work from the management network only. Limit the task to the stated fix. Set an expiry (default 4 hours).
3. **Record.** In the portal, if it is reachable, record the reason and expiry; otherwise write them in the paper log and enter them into the portal audit afterwards. The portal audit is append-only, so state the real times.
4. **Finish.** Return to normal access. Rotate the break-glass credential and any secret that was exposed. Reseal it.
5. **Review.** The recovery approver reviews the work within one business day: what was touched, whether any employee data was viewed, whether a case is needed.

## Maintenance exceptions

An IT maintenance exception on a company device is time-limited, audited and approved by someone other than the person using it. It must not disable security products permanently. Record it with `POST /api/v1/devices/{id}/maintenance-exceptions` (list with GET on the same path); it is a record only and does not yet appear in posture output.

## Limits

A single person who holds both the sealed credential and the admin identity can still act alone. Separation depends on the two named people actually being different.
