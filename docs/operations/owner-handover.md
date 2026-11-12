# Owner handover

For the person who will operate this system. It states what the system does not do. Nothing here has been run on real infrastructure yet; control status lives in docs/validation/test-plan.md.

## What you own

Patching, alert triage, employee support, restore drills and the recovery decision. One named administrator owner and one recovery approver are required. A dashboard with no operator protects nothing. Both are still TBD (docs/decision-log.md).

## Residual risks

1. **People can see the information.** An employee in a remote desktop can photograph the screen or retype what they see. A compromised personal computer can capture the screen and input. We cannot prevent either and we do not detect them reliably (scenario 18).
2. **Administrators are powerful.** Whoever controls the hosts, the database and the keys can alter or read almost anything. Separate admin identities, an independent audit copy and second review of sensitive exports reduce this; they do not remove it. Hash chaining is tamper evidence, not immutability.
3. **Wazuh and file monitoring are evidence, not blocking.** They do not prove that data could not leave.
4. **Egress is only as good as the allowlist.** Allowed multi-tenant services can carry data to a personal tenant.
5. **Single production host.** An outage stops work. Pilot targets are RPO 24 hours and RTO one business day, unmeasured until the first restore rehearsal. A spare host is a purchase decision.
6. **Company laptops.** Local copies and local administrators weaken control. Ordinary users cannot stop required services; root or physical control can. Fleet premium features are not assumed free.
7. **BYOD.** Remote-only access, nothing installed, no local posture claim.
8. **Offboarding depends on a verified gateway and OS session kill.** If the pinned Guacamole version lacks a stable session-termination interface, an operator does it by hand (docs/runbooks/offboarding.md) and the job stays incomplete until verified. The 5-minute target is unmeasured.
9. **Export delivery is manual.** No secure external delivery service exists. An authorised recipient can copy a released file.
10. **Legal and privacy review is not done.** The collection policy and notice are drafts. No real employee data should be collected until a jurisdiction review and owner sign-off.
11. **Software gaps carried from the build.** Abandoned pre-login session rows and expired sessions are not purged yet; the audit table needs production DB grants limited to INSERT and SELECT (TRUNCATE is not trapped by the trigger); Keycloak realm roles must appear in the ID token; RP-initiated Keycloak logout is not implemented, so logging out of the portal does not end the Keycloak session; OIDC discovery and JWKS are cached without a TTL until restart or an unknown key id.
12. **Unsupported or unvalidated.** Windows VMs and licensing, macOS management, GPU or CAD workloads, offline work, and any application not tested on Linux/xrdp.
13. **Manual steps.** Backup credential custody, break-glass seal, license review per release, firewall rule review, outbound traffic review.
14. **External dependencies to record.** Approved package and update routes; Apple APNs if macOS management is ever added; public ACME and DNS if chosen. Each needs an explicit exception.

## What not to say about this system

Do not call it invisible, unstoppable or leak-proof. Describe it by the controls actually tested.

## Before go-live checklist

- Owner and recovery approver named.
- Collection policy accepted, notice approved per country, jurisdiction review done.
- Security review and outbound traffic verification (Q01) complete.
- One-user pilot, then five-user pilot, with the validation scenarios run and statuses updated.
- A clean restore rehearsal done and timed.
- Version manifest and licence review recorded.
