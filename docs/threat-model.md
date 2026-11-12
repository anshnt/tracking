# Threat model (D02)

Scope: the Work and Security Portal and the self-hosted stack around it (Keycloak, Guacamole, xrdp VMs, Wazuh, backups). Spec: PLAN.md section 5. This is a design document; no control is claimed as working until docs/validation/test-plan.md shows it tested.

## Data classes

| Class | Meaning | Default handling |
| --- | --- | --- |
| Public | Approved for external sharing | None |
| Internal | Routine business information | Authenticated employees |
| Confidential | Customer records, contracts, private source, finance | Server workspace only |
| Restricted | Production secrets, bulk customer exports, regulated data | Role-limited environment, explicit release approval, minimal standing access |

## Assets

- Business files and source code in employee VMs and internal repositories.
- Portal database: employee records, work updates, security events, cases, export requests, audit events.
- Identity: Keycloak realm, MFA secrets, recovery records.
- Gateway: Guacamole connection definitions and guacd reach into VM RDP ports.
- Backups, backup credentials and the independent audit copy.
- Secrets: OIDC client secret, DB roles, connector tokens, session secret.

## Actors

| Actor | Trust | Notes |
| --- | --- | --- |
| Employee | Authenticated, standard user | Sees their own screen content; the main residual leak source |
| Manager | Authenticated, scoped | Sees direct reports' work summaries only |
| Security reviewer | Privileged role | Cases and export review; cannot approve own requests |
| Administrator | Highest trust | Separate admin identity; the single most powerful actor |
| BYOD host | Untrusted | Personal computer, cannot be inspected |
| External attacker | Untrusted | Stolen password, phishing, exposed service |
| Departed employee | Untrusted after offboarding | Open sessions and unrevoked tokens are the risk |

## Trust boundaries

1. Browser or BYOD host to reverse proxy (internet or LAN to our edge).
2. Reverse proxy to Keycloak, portal and Guacamole.
3. Guacamole to guacd to employee VM RDP ports (only guacd may reach xrdp).
4. Employee VM to the rest of the network (default deny; internal Git, files and apps only).
5. Portal to connectors and upstream tools (read-only adapters first, least-privilege tokens).
6. Application roles to the database (audit table append-only for the application role).
7. Production to backup storage (separate credentials, separate device).
8. Admin plane (management network, separate identities) to everything else.

## Leakage paths

| Path | Prevent or reduce | Detect | Residual |
| --- | --- | --- | --- |
| Remote clipboard or file download | Gateway clipboard, drive, printing and SFTP disabled; remote OS restrictions | Gateway config drift check; export audit | Other apps or protocol paths left open |
| Personal email, AI sites, cloud drives, paste sites | Sensitive VMs internal-only egress; approved release workflow | Proxy and app security events | An allowlisted multi-tenant service can reach a personal tenant |
| USB or printing on a company laptop | Supported OS device and print policy; avoid local restricted files | OS events where supported | Not content-aware; not all applications |
| Git push to a personal repository | Internal-only Git route; narrow repo permissions | Push and review audit; secret scan | Open internet egress allows other channels |
| Bulk internal download or export | Object-level authorization, scoped queries, quotas, approval | Export volume, destination, actor, class | Thresholds give false positives; small leaks evade volume checks |
| Stolen password | MFA, short sessions, revocation | Authentication anomalies, recovery events | Compromised active session or personal host |
| Collector or agent removal | Standard user, supported service permissions | Independent last-seen check; stale means unknown | Root or admin can falsify endpoint claims |
| Administrator misuse | Separate admin identities, independent audit copy, second review of sensitive exports | Privileged-action logs, audit hash of changes | One person controlling all systems stays powerful |
| Photo, local screenshot, manual transcription | Reduce what is visible, reduce standing access | Not reliably detectable | Cannot be prevented on BYOD or company laptops |
| Departed employee's open session | Offboarding terminates gateway and OS sessions, revokes tokens | Per-step verification; job stays incomplete until verified | Gap between action and termination (target 5 min, to be measured) |
| Portal bugs (ID substitution, CSRF, injection) | Object-level checks, CSRF origin check, parameterized queries, redaction | Audit, tests | Logic bugs remain until reviewed (Q01) |

## Non-goals (not prevented, and we say so)

- A phone camera pointed at a screen, and manual retyping.
- A compromised BYOD host (screen capture, input capture). Remote-only access cannot trust the host.
- Administrator misuse beyond what separation of duties and the audit copy reduce. Hash chaining is tamper evidence, not immutability against someone holding both data and keys.
- Undetectable or unstoppable endpoint control. We do not build hidden agents or uninstall evasion.
- Content-aware DLP across all applications and channels.
- Availability beyond a single production host with RPO 24 h and RTO one business day.

## Notes

VPN connectivity, file integrity alerts and application focus time are not proof that data cannot leave. A file-change alert does not show that an external copy was blocked.
