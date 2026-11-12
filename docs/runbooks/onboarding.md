# Runbook: onboarding an employee

Owner: administrator owner (TBD). Precondition: the collection policy is accepted and the employee notice is approved for that employee's country (docs/decision-log.md). Never onboard a real employee before the pilot gates are met.

## Steps

1. **Request.** Manager asks in writing with name, role, start date, device type (company laptop or BYOD), classification ceiling needed. Record the request.
2. **Identity.** Create the Keycloak user (unique account, never shared). Assign realm roles from `employee`, `manager`, `it`, `security`, `approver`, `admin`. Give an employee only `employee`; admin is a separate identity. Require MFA enrolment at first login. Confirm the realm roles mapper puts roles in the ID token.
3. **Portal record.** The employee appears in `employees` on first login (immutable OIDC subject). Set manager, timezone and status `active`.
4. **Workspace.** Clone the VM template, create a unique unprivileged OS account, set the classification ceiling. Create the Guacamole connection assigned only to this user. Remote OS credentials are prompted from the employee, not embedded. Confirm RDP is reachable only from guacd and TLS trust is pinned.
5. **Network.** Place the VM in the employee zone: default deny to other VMs, internal-only egress for sensitive work.
6. **Telemetry.** Install the Wazuh agent on the VM (and on a company laptop, with disclosure). Confirm a synthetic event reaches the portal.
7. **Notice.** Assign the current policy version. The employee signs in and acknowledges it. Acknowledgement is recorded but is not treated as the legal basis.
8. **Asset.** For a company laptop record the asset, owner and OS. For BYOD record `personal` and nothing installed.
9. **Verify.** Employee connects; another employee cannot (scenario 2); copy-out is blocked (scenario 3). Record evidence.
10. **Close the checklist** with date, operator and evidence references.

## Rollback

Disable the Keycloak user and follow docs/runbooks/offboarding.md for the half-created account.
