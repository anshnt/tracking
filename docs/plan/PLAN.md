# Employee security and work visibility implementation plan

**Prepared:** 12 November 2026  
**Confirmed scope:** approximately five employees; services and business data hosted on your own servers.  
**Deliverable:** researched architecture, implementation backlog, acceptance criteria, and instructions for an implementation agent. This is a plan, not deployed or tested security software.

## 1. Recommended decision

Build a small internal **Work and Security Portal** around existing self-hosted components. Keep sensitive work inside individually assigned server workspaces. Offer company laptops for roles that need local applications or offline work. Give BYOD users browser access to their server workspace without installing a surveillance agent on their personal computer.

The strongest practical starting point for five people is:

1. **Keycloak** for internal identity and MFA.
2. **Apache Guacamole** for browser access to five separate Linux virtual desktops, using **xrdp** inside each VM.
3. **Wazuh** for security telemetry from servers, virtual desktops, and company laptops.
4. **Your portal** for onboarding, work summaries, policy status, export requests, and incident workflows.
5. **Gitea**, if you need internal code hosting and task tracking; otherwise connect an existing internal tracker.
6. **Encrypted backups** to separate company-controlled storage, using a tool such as restic.

Add Fleet when company laptops need inventory and policy querying. Add Kimai only if formal timesheets, project budgets, or billing justify another application. Add a self-hosted NetBird deployment if you lack a suitable remote-access network. These are staged additions, not a requirement to operate every tool on day one.

This architecture is an engineering recommendation based on the sources below, not a vendor guarantee. No monitoring system can guarantee zero leakage once someone can see information. Cameras, transcription, a compromised personal computer, and privileged administrators remain material risks.

### What this achieves

| Goal | Primary control | Result to expect |
| --- | --- | --- |
| Keep working files on company servers | Remote desktops, internal repositories, internal storage | Reduces local file copies; screen pixels still reach the employee |
| Limit ordinary copying out | Disable remote clipboard export, drive redirection, printing, SFTP, and direct alternate access | Blocks tested transfer paths through the configured gateway |
| Limit uploads to personal services | Server-side network isolation; only approved internal destinations for sensitive work | Stronger than merely logging browser activity |
| Know what work is progressing | Tasks, deliverable links, review status, employee updates, optional timesheets | Shows outcomes and blockers with context |
| Detect security problems | Wazuh, gateway logs, application audit events, health checks | Alerts require a human owner and tuning |
| Reduce employee tampering | Standard user accounts, separate admin plane, supported service permissions | Resists ordinary-user interference; not unstoppable against root or physical control |
| Present one product | Portal plus authenticated links and narrow integrations | One workflow with separately maintained upstream tools |

## 2. Assumptions and unresolved decisions

Only headcount and self-hosting are confirmed. Do not infer employee jurisdiction from the chat timezone. The agent can develop with synthetic data while these decisions are collected.

| Decision | Working assumption | Changes the design when |
| --- | --- | --- |
| Work type | Browser, documents, ordinary development | CAD, video, GPU, hardware access, or Windows-only applications are needed |
| Endpoint OS | Windows first for company laptops; browser BYOD can be Windows/macOS/Linux | macOS management or Linux local workflows are selected |
| Server ownership | Existing or purchased company-controlled physical servers | Rented dedicated infrastructure is also acceptable |
| External dependencies | No external storage or telemetry for employee/business content; approved updates may use the internet | You require completely disconnected operation |
| Internet availability | Employees can reach the office server reliably | Offline work or poor connectivity is essential |
| Jurisdiction and employee notice | Must be settled before employee monitoring begins | Local requirements determine notice, consultation, basis, retention, and access rights |
| Budget | Unspecified; use resource formulas rather than pretend vendor quotes | Hardware inventory and labor rates are known |
| Administration | One named technical owner and one recovery approver | No one can maintain the services or respond to alerts |

First collect: employee countries, application list, sensitive data types, existing hardware specifications, bandwidth/latency, backup location, availability target, administrator availability, and maximum spend. A deployment that needs Windows VMs must resolve Windows virtualization and remote-access licensing before production; Linux is the default compatibility trial, not an assumption that every business application works on it.

## 3. Company laptops and personal laptops

| Mode | How it runs | Visibility | Protection limits | Recommendation |
| --- | --- | --- | --- | --- |
| Company laptop with local work | Supported Windows service, macOS launch daemon/MDM, or Linux systemd service; disclosed to employees | Device health, approved security events, work-app integrations | Data exists locally; local administrators and offline copies complicate control | Use when local applications or offline work are necessary |
| Company laptop as a thin client | Managed laptop opens the internal remote desktop | Device health plus server session/work events | Screens remain observable; office outage stops work | Best combination when budget allows |
| BYOD browser workspace | Personal browser opens Guacamole; execution and files stay in a server VM | Remote session metadata, internal application actions, work outcomes | Cannot inspect or trust the personal host; host malware can capture screens/input | Default BYOD route for sensitive work |
| BYOD locally installed application | Voluntary, explicitly scoped business software | App-specific business actions only | Personal owner can stop/uninstall it; no reliable whole-device boundary | Limit to low-sensitivity workflows |
| Browser extension or scheduled task | Optional managed-browser feature or periodic maintenance | Narrow browser/app signals | Not a complete DLP boundary; scheduled jobs are not continuous protection | Supplement only |

**Do not implement hidden processes, rootkits, process disguise, covert persistence, permission bypasses, keylogging, password collection, webcam/microphone monitoring, or uninstall evasion.** For company equipment, use supported administrator controls and disclose installed services. If an agent stops reporting, mark its state unknown and restrict future sensitive access through a server-controlled gate. Do not secretly reinstall it on a personal computer.

On Windows, enforce standard-user work accounts, encryption, updates, firewall policy, and approved application configuration with supported OS management. On Linux use equivalent privilege separation and configuration management. On macOS, robust enrollment controls may involve Automated Device Enrollment; that is an Apple-supported management model rather than an invisible background process. Apple MDM uses APNs, so a self-hosted MDM server still has an Apple service dependency. See [Apple enrollment guidance](https://support.apple.com/guide/deployment/automated-device-enrollment-management-dep73069dd57/web) and [Fleet APNs setup](https://github.com/fleetdm/fleet/blob/main/articles/apple-mdm-setup.md).

## 4. Researched tools and reuse decisions

License descriptions below are an initial screening. Before adoption, pin an exact release, inspect its complete license and bundled dependencies, review security advisories and supported upgrade paths, and record the result. Repository main branches can differ from stable releases. Keeping services separate simplifies maintenance; it does not automatically remove license obligations.

| Tool | Useful capability | Self-hosting and license observations | Decision for five employees |
| --- | --- | --- | --- |
| [Apache Guacamole](https://guacamole.apache.org/) / [source](https://github.com/apache/guacamole-client) | Browser remote desktop gateway | Apache-2.0; remote hosts and their OS licenses are separate | Core gateway; configure all transfer paths explicitly |
| [xrdp](https://github.com/neutrinolabs/xrdp) | RDP access to Linux desktops | Apache-2.0; runs inside your Linux VMs | Core for Linux workspace trial; restrict inbound access to guacd |
| [Keycloak](https://github.com/keycloak/keycloak) | Internal identity and SSO | Apache-2.0 | Core identity; MFA, recovery, and separate admin accounts |
| [Wazuh](https://documentation.wazuh.com/current/getting-started/components/wazuh-agent.html) / [source](https://github.com/wazuh/wazuh) | Security logs, configuration assessment, file integrity, response | Self-hostable; current source has GPLv2, AGPLv3 engine, and dual-licensed shared components | Core security, not a content-aware endpoint DLP substitute |
| [Fleet](https://github.com/fleetdm/fleet) | Inventory, osquery queries, device policy workflows | Free code MIT; premium code separately licensed | Add for company laptops after feature validation; avoid duplicating every Wazuh collector |
| [NetBird](https://github.com/netbirdio/netbird) | Identity-controlled private networking | BSD-3-Clause except management/signal/relay directories under AGPLv3 | Optional; self-host management, relay, and identity; restrict BYOD routes |
| [Gitea](https://github.com/go-gitea/gitea) | Internal Git, code review, issues, projects, CI | MIT | Use for engineering work evidence if you need internal hosting; isolate CI runners |
| [Kimai](https://github.com/kimai/kimai) | Timers, timesheets, project budgets, reports, JSON API | AGPL-3.0; plugins may have their own terms; needs MySQL/MariaDB | Optional timesheet system; do not add just to collect more data |
| [ActivityWatch](https://github.com/ActivityWatch/activitywatch) | Local application/window/browser activity and AFK signals | MPL-2.0; local, user-controlled tracking design | Optional employee self-insight only; not the authoritative work or security record |
| [Gitleaks](https://github.com/gitleaks/gitleaks) | Secret scanning for Git/files | MIT CLI; separately review any hosted action/wrapper | Run internally in CI and enforce server-side checks; local hooks alone are bypassable |
| [Ansible](https://github.com/ansible/ansible) | Repeatable server and endpoint configuration | GPLv3-or-later for ansible-core; collections have separate terms | Use from a restricted admin runner; no employee-accessible credentials |
| [restic](https://github.com/restic/restic) | Encrypted backups | BSD-2-Clause | Use with application-consistent database dumps and separate backup credentials |
| [Snipe-IT](https://github.com/grokability/snipe-it) | Asset assignment and equipment records | AGPL-3.0 | Defer; five asset records in the portal are sufficient initially |
| [Kasm Workspaces](https://docs.kasm.com/docs/reference/license) | Remote workspaces and transfer restrictions | Community Edition permits evaluation and eligible non-commercial use, up to five concurrent sessions; commercial production needs suitable licensing | Paid alternative to compare, not a free commercial baseline |
| [OpenDLP mirror](https://github.com/cloudsecuritylabs/openDLP/blob/main/README.md) | Historical sensitive-data discovery | README identifies version 0.5.1 from 2012 | Do not base new endpoint enforcement on this; maintenance and compatibility are not established |
| [Microsoft Purview Endpoint DLP](https://learn.microsoft.com/en-us/purview/endpoint-dlp-learn-about) | Content-aware endpoint activity controls | Commercial Microsoft service with documented OS/browser coverage and onboarding requirements | Capability benchmark; excluded from the strict own-server baseline |

### Important edition traps

Fleet's current public matrix puts several functions, including conditional access, encryption enforcement, lock/wipe, RBAC, and audit logging, in Premium. Do not attribute them to the free edition. Free inventory and API access can still be useful; keep any free-edition admin interface isolated and do not give managers direct access. Pricing and entitlement must be reconfirmed for five hosts. [Fleet feature matrix](https://fleetdm.com/pricing).

Guacamole documents clipboard controls and separate RDP printing, drive, and SFTP settings. Disabling one path does not disable all paths. It is a gateway, not a virtual machine orchestrator or full DLP product. [Guacamole configuration](https://guacamole.apache.org/doc/gug/configuring-guacamole.html).

### Commercial inspiration without copying a surveillance product

| Product | Published capability to study | Proposed interpretation |
| --- | --- | --- |
| [Hubstaff](https://hubstaff.com/features) | Project time, app/URL activity, optional screenshots | Adopt project-linked timesheets and employee visibility; leave screenshots out of the MVP |
| [ActivTrak](https://support.activtrak.com/hc/en-us/articles/360053092432-How-ActivTrak-Respects-Employee-Privacy) | Workforce analytics and privacy controls | Adopt team-level context and employee access to their own records |
| [Teramind](https://www.teramind.co/features/) | Monitoring and DLP feature categories | Adopt explicit security-rule workflows and incident review, not a broad content-recording system |
| [Kasm DLP controls](https://docs.kasm.com/docs/develop/how-to/security/data-loss-prevention) | Clipboard, downloads, printing, and other session channels | Use as a checklist when testing remote-workspace boundaries |

These are feature references, not independent performance evaluations or recommendations to buy them. Do not copy proprietary source, UI assets, wording, or undocumented integrations.

## 5. Threat model and data boundaries

Classify information before writing rules:

- **Public:** approved for external sharing.
- **Internal:** routine business information; only authenticated employees.
- **Confidential:** customer records, contracts, private source, financial details; default server workspace access.
- **Restricted:** production secrets, bulk customer exports, sensitive regulated information; role-limited server environment, explicit release approval, minimal standing access.

| Leakage path | Prevent or reduce | Detect | Remaining gap |
| --- | --- | --- | --- |
| Remote clipboard/file download | Gateway controls plus remote OS restrictions | Gateway configuration drift and export audit | Alternative apps or direct protocol paths if left open |
| Personal email, AI sites, cloud drives, paste sites | Sensitive VMs have internal-only egress; explicit approved release workflow | Approved proxy and application security events | An allowlisted multi-tenant service can still carry data to a personal tenant |
| USB or printing on a company laptop | Supported OS device/print policies; avoid local restricted files | OS events where configured and supported | Not equivalent to content-aware blocking across all applications |
| Git push to personal repository | Internal-only repository route for sensitive VMs; narrow repo permissions and credentials | Internal push/review audit; secret scan | Arbitrary internet egress permits alternative exfiltration channels |
| Bulk internal download/export | Application authorization, scoped queries, export quotas, approval | Export volumes, destination, actor, classification | Thresholds create false positives; small leaks can evade volume detection |
| Stolen password | MFA, short-lived sessions, revocation | Authentication anomalies and recovery events | Compromised active session or personal host |
| Agent removal | Standard-user restrictions; supported service permissions | Independent last-seen checks and collector health | Root/admin can compromise endpoint claims |
| Administrator misuse | Separate admin identities, independent audit copy, second review for sensitive exports | Privileged-action logs | A single person controlling every system remains powerful |
| Photo, local screenshot, manual transcription | Reduce visible information and standing access | Limited reliable detection | Cannot reliably prevent these on BYOD; cameras also affect company laptops |

Do not describe VPN connectivity, file integrity monitoring, or application focus time as proof that data cannot leave. Do not equate time at keyboard with completed work. A file-change alert is not evidence that an external copy was blocked.

## 6. Proposed server architecture

Start with one virtualization host and separate VMs/security zones; keep backups on a second company-controlled device or server. This is a single-production-host design with an acknowledged outage risk. A spare recovery host or second production host is a later reliability purchase, not implied high availability.

```text
Employee laptop, company or BYOD
  -> office LAN or approved private access network
  -> HTTPS reverse proxy
       -> Keycloak identity + MFA
       -> Work and Security Portal
       -> Guacamole gateway -> isolated guacd -> employee-specific VM

Employee VM -> authorized internal Git / files / applications only
Employee VM -> no arbitrary internet, LAN discovery, or admin-network access

Servers / company laptops -> Wazuh security plane
Applications / gateway -> narrow portal adapters -> portal PostgreSQL
Admin workstation -> separate management network -> approved administration
Production -> encrypted, application-consistent backups -> separate storage
```

### Network policy

- Default deny between employee VMs. Permit only necessary internal application flows.
- BYOD access can reach the identity service, portal, and gateway, not internal file shares, SSH, RDP, database ports, or hypervisor management.
- Only guacd can reach workstation RDP ports. Pin and verify remote-host TLS trust; never use certificate-ignore settings as a production shortcut.
- guacd accepts connections only from the Guacamole application. An attacker-controlled gateway is a privileged route into desktops; isolate and patch it accordingly.
- Databases and tool APIs are internal. Admin dashboards are available only from the management network.
- Sensitive workspaces are internal-only. When research or dependency retrieval is needed, use a separate non-sensitive browsing VM and an approved import workflow or internal package mirror.
- General web allowlists are weaker than internal-only access. DNS, redirects, arbitrary URL paths, personal accounts on business domains, SSH, and developer tools must be included in testing.
- Never expose a container runtime socket, hypervisor API, production secrets, or privileged CI runner to an employee VM.

### Initial sizing, to benchmark

These are engineering starting allocations for light workloads, not measured requirements for your applications.

| Workload | Initial allocation | Notes |
| --- | --- | --- |
| Five Linux desktops | 2–4 vCPU, 4–8 GiB RAM, 40–80 GB each | Heavy builds, CAD, or video can require much more |
| Identity, gateway, portal, reverse proxy, portal DB | 4–6 vCPU, 8–12 GiB RAM combined | Separate VMs/containers and per-service credentials; not one shared admin container |
| Wazuh all-in-one | 4 vCPU, 8 GiB RAM, at least 50 GB | Official quickstart's 1–25 agent reference; reserve extra for indexing and retention |
| Optional Git, time tracking, inventory | 2–4 vCPU, 4–8 GiB RAM initially | Add only selected components; Kimai/Fleet may introduce MySQL/MariaDB |
| Production host | Approximately 12–16 modern physical CPU cores, 64 GiB RAM, 1–2 TB usable SSD to trial | vCPU overcommit is workload-dependent; storage includes OS, growth, snapshots, and logs |
| Backup target | Separate device; capacity based on real changed data and retention | RAID and local snapshots are not an independent backup |

The Wazuh allocation is sourced from its [quickstart requirements](https://documentation.wazuh.com/current/quickstart.html). All other allocations require a five-user concurrency trial. Allocate closer to 128 GiB or a separate workspace host if measurements justify it. Measure browser rendering, build time, disk I/O, memory pressure, and gateway CPU at realistic latency before buying more hardware.

## 7. Own-server operation and external dependencies

The baseline must keep source code, documents, employee events, logs, databases, authentication data, and backups on company-controlled infrastructure. No SaaS analytics, crash reporting, external LLM processing, remote fonts, hosted dashboards, or third-party screenshot stores in the portal.

Self-hosting does not imply air-gapping. Define and document outbound access explicitly:

| Dependency | Default handling |
| --- | --- |
| Application database, logs, file storage | Internal services only |
| Identity and MFA | Internal Keycloak; local TOTP or suitable hardware authenticators; offline recovery records |
| DNS, time, certificates | Prefer internal services for private access; public DNS/ACME, if chosen, expose associated metadata and need an exception |
| Packages, signatures, vulnerability feeds | Approved download route or internal mirror; track source, verification, and refresh schedule |
| NetBird | If selected, self-host its control components and relay/STUN dependencies; no default hosted identity or relay shortcut |
| Apple management | APNs and Apple enrollment dependencies require an explicit exception; use another platform if zero external control-plane services is mandatory |
| Windows management and activation | Validate the exact edition, activation model, update route, licensing, and management dependencies; do not promise Intune/Autopilot as an on-premises-only system |
| Notifications | Portal inbox plus existing internal email; no new Slack/email content export unless explicitly chosen |
| Backups | Separate company-controlled storage; consider an encrypted offline/offsite company-held copy for site-loss protection |

Verification: observe outbound network traffic through a controlled firewall during installation, normal use, updates, and failures. Inventory each destination, purpose, data category, and approved owner. Disable optional telemetry using documented settings. For an air-gapped variant, use offline packages, internal certificate/time services, and a signed update import process, and test operation without internet access.

## 8. Portal product specification

The custom product coordinates operations; upstream tools remain separate services. Use SSO links first and add narrow read integrations before privileged actions. Do not fork all upstream code into one repository.

### Employee experience

1. Sign in with MFA and see the applicable monitoring notice, policy version, and contact person.
2. Open the assigned workspace and approved internal applications.
3. View assigned tasks, linked deliverables, blockers, and expected review dates.
4. Submit a short daily update or a project timesheet where required.
5. Request an export by selecting the file/reference, recipient, purpose, and classification.
6. See the personal work records collected, corrections, export status, and access restrictions affecting them.

### Owner and manager experience

- Five-person overview: active assignments, deliverables awaiting review, blockers, overdue work, and missing employee updates.
- Device/workspace state: compliant, noncompliant, unknown, or not applicable, with observation time and exact failing check.
- Security cases: severity, source, evidence metadata, owner, status, and action history.
- Export queue: approved destination, business justification, release expiry, reviewer, and download receipt.
- Onboarding/offboarding checklist with per-system completion status and failed steps.
- No employee ranking, universal productivity percentage, or automatic performance decision from activity signals.

### Reuse boundaries

| Concern | System of record | Portal integration |
| --- | --- | --- |
| Identity and access groups | Keycloak | OIDC for portal; controlled provisioning adapter later |
| Remote connection definitions | Guacamole database/auth extensions | Authenticated launch link first; documented extension or operator workflow for lifecycle |
| Security evidence | Wazuh | Restricted API read; retain IDs and summaries, not duplicate all raw logs |
| Tasks and reviews | Internal tracker/Gitea | Read API or signed webhooks; deep links |
| Timesheets | Kimai if enabled | JSON API adapter; keep timesheet accounting in one place |
| Laptop inventory | Fleet if enabled | Read-only inventory adapter with capability/edition discovery |
| Export approvals, notices, case workflow | Custom portal | Own PostgreSQL schema and authorization |

Use Guacamole's supported SAML authentication extension with Keycloak plus a database extension for connection authorization; test group mapping for the pinned versions. Authentication alone does not grant a safe connection policy. The documented OIDC extension has flow-specific constraints, so do not assume it is interchangeable with the portal's authorization-code/PKCE implementation. [Guacamole SAML documentation](https://guacamole.apache.org/doc/gug/saml-auth.html), [OIDC documentation](https://guacamole.apache.org/doc/gug/openid-auth.html).

Gateway SSO and remote operating-system login are separate boundaries. Create a unique, unprivileged OS account for each employee; decide explicitly how credentials are provisioned, reset, and revoked. For the initial lab, prompting for that employee's remote OS credentials is preferable to embedding shared administrator passwords. If a supported secret-provider integration is adopted later, restrict retrieval to the assigned connection and test revocation. Do not assume Keycloak automatically creates Linux or Windows accounts or that closing the browser logs out the remote desktop.

## 9. Work tracking and collection policy

Collect signals that answer a business question. Continuous security monitoring on company systems and in server workspaces is separate from scheduled employee work-activity collection.

| Signal | MVP default | Access and interpretation |
| --- | --- | --- |
| Tasks, review state, blockers, deliverable links | On | Employee and authorized manager; primary progress evidence |
| Daily employee update | On | Short narrative; can describe meetings, research, and offline work |
| Project time | Optional | Employee-entered or knowingly started timer; editing history preserved |
| Workspace start/end and authentication | On | Security and operations; not proof of continuous effort |
| Device patch/encryption/agent health | Company devices/server VMs only | IT/security; report unknown when stale |
| Export and privileged actions | On | Restricted security/approval roles |
| Application categories and idle periods | Off initially | Optional later, during disclosed work sessions; coarse categories only, never a performance score |
| Window titles, full URLs, clipboard text | Off | Titles/URLs can contain customer data, secrets, and personal information |
| Screenshots and full session recordings | Off | Separate exceptional use case, notice, access, and retention decision required |
| Keystrokes, passwords, personal browsing, camera/audio | Excluded | Do not implement |

If ActivityWatch is trialed, retain its local, user-controlled purpose. Any central export would be new integration work requiring a separate scope and privacy decision; do not relabel it enterprise DLP. Its README describes local storage and activity watchers. [ActivityWatch source](https://github.com/ActivityWatch/activitywatch).

Proposed retention defaults, subject to jurisdiction and actual business purpose: 30 days for optional raw work-activity events, 90 days for security/session metadata, 180 days for approval and privileged-action records, and 12 months for work summaries if justified. Formal payroll, financial, legal-hold, or contract records need their own schedule. Delete expired records and derived copies; encrypted backups expire on a documented rotation, and restore jobs must reapply deletion tombstones and current legal holds.

## 10. Technical specification for the custom code

Use the team's existing supported stack if available. Otherwise, a practical proposal is React/TypeScript for the UI, FastAPI/Python for an API and background worker, and PostgreSQL for portal data. Use a PostgreSQL-backed jobs/outbox table initially. Five employees do not justify Kafka, Kubernetes, a data lake, or an additional analytics database.

### Repository structure

```text
apps/web/                     Employee and administrator UI
apps/api/                     Authorization, workflow, versioned API
apps/worker/                  Idempotent polling, approvals, retention
packages/contracts/           API schemas and event definitions
connectors/                   Keycloak, Wazuh, tracker, optional Fleet/Kimai
infra/compose/                Local app development and lab services
infra/ansible/                Server roles, network rules, VM configuration
policies/                     Versioned templates and collection allowlists
tests/                        Contract, authorization, integration, end-to-end
docs/                         Threat model, runbooks, evidence, decisions
```

Keep upstream services' databases and schemas separate. One PostgreSQL instance may host separate databases/roles for supported components at this scale, but never shared superuser credentials. Do not force MySQL-dependent tools into PostgreSQL.

### Core records

- `employees`: internal UUID, immutable identity subject, manager, status; avoid email as the sole identity key.
- `assets`: asset UUID, ownership, assigned employee, OS, upstream IDs; restricted fields for company equipment only.
- `workspaces`: UUID, owner, role profile, classification ceiling, connection reference, lifecycle state.
- `policy_versions` and `policy_assignments`: immutable version/hash, scope, activation time, exceptions, reviewer.
- `posture_observations`: source, observed/received time, checks, expiry; observations are evidence, not trusted commands.
- `work_updates`: date, task references, deliverables, blocker, employee correction history.
- `security_events`: source ID, source version, type, severity, actor/resource, event time, redacted metadata.
- `cases`: owner, reason, evidence references, status, actions, closure rationale.
- `export_requests`: object/version reference, classification, recipient, purpose, status, reviewer, expiry, release checksum/receipt.
- `audit_events`: actor, action, target, reason, before/after metadata hashes, request ID, time; append-only for application roles.
- `jobs` and `connector_checkpoints`: idempotency keys, next run, attempts, cursor, last successful sync.
- `retention_rules`, `legal_holds`, and `deletion_tombstones`: enforce lifecycle across production and restore.

### Proposed API surface

| Endpoint | Purpose and authorization |
| --- | --- |
| `GET /v1/me` and `/v1/me/collection-policy` | Employee profile, collected categories, notice/version |
| `GET /v1/workspaces` | Authorized workspace references only |
| `GET /v1/devices/{id}/posture` | Employee own device or scoped IT role |
| `POST /v1/work-updates` | Employee writes own update; manager cannot silently rewrite it |
| `POST /v1/export-requests` | Create a request, not release a file |
| `POST /v1/export-requests/{id}/decisions` | Designated reviewer; forbid self-approval |
| `POST /v1/export-requests/{id}/release` | Separate capability, revalidation, short expiry, audited receipt |
| `GET /v1/cases` and `POST /v1/cases/{id}/actions` | Security scope; limited action catalogue |
| `POST /v1/offboarding-jobs` | Privileged role, reason, idempotency key, explicit target review |
| `GET /v1/operations/connectors` | IT-only health, cursor age, edition/capability state |

Every list/detail/action must enforce object-level authorization. Use secure HTTP-only session cookies, CSRF protection where applicable, strict origin checks, request limits, parameterized queries, secret redaction, and OIDC token issuer/audience/nonce validation. Do not put service tokens in browser storage or expose vendor credentials to the front end.

### Event contract and correctness

Each normalized event includes `schema_version`, `event_id`, `source`, `source_event_id`, `employee_id` if resolved, `asset_id` if resolved, `event_type`, `occurred_at`, `received_at`, `classification`, `retention_policy`, and allowlisted metadata. Use UTC in storage and the employee's chosen timezone in displays.

Deduplicate on source plus source event ID. Handle pagination, replay, reordered events, clock skew, rate limits, schema changes, and identity reassignment. Preserve an unresolved identity rather than guessing. Cursor advancement and event persistence must be atomic. Use bounded exponential retry and an operator-visible failed-job queue. Display stale/unknown data with timestamps; a successful API call is not proof that collection is complete.

## 11. Access and tamper resistance

For a company-owned laptop, the acceptable goal is: **ordinary employees cannot disable required controls using their work account; IT can service them; loss of telemetry is visible.** No promise of undetectability or absolute inability to stop software is credible against the owner of a personal laptop or an administrator controlling the OS.

Use native service managers with supported startup/restart settings and service permissions, standard-user employee accounts, managed configuration, authenticated updates, and centrally observed heartbeats. Prefer upstream endpoint agents over a new privileged cross-platform agent. A separate employee-facing page explains what is installed and why.

For new sensitive local-device access, proposed policy: posture observation no older than 15 minutes; required collector heartbeat no older than 5 minutes; failure causes unknown/noncompliant state. These are proposed thresholds to tune in a pilot, not built-in guarantees of any shortlisted tool. A posture-aware gateway must enforce this on every protected route; Fleet or a VPN being present does not implement it automatically. BYOD remote-only access uses an explicitly different policy and does not pretend the personal device has passed local posture checks.

If device health becomes unknown during an active sensitive session, alert immediately and require the chosen enforcement adapter to terminate or restrict that session within the tested target window. Do not assume IdP disablement, a VPN rule change, or a short token lifetime terminates an already-open connection.

Provide audited, expiring IT maintenance exceptions and a documented break-glass recovery procedure. Do not self-modify, hide services, disable security products, or bypass OS permission prompts. Full-device wipe is excluded from the MVP and must never be available for personal laptops.

## 12. Export and offboarding workflows

### Approved export

`requested -> reviewed -> approved/rejected -> staged -> released -> expired`

Approval alone is not a transfer mechanism. A restricted release worker stages only the approved object/version into a release area. Validate authorization, classification, destination, expiry, and current employment status again at release time. For the MVP, an administrator can manually deliver the file through an already approved business channel and attach a receipt; do not imply a complete secure external delivery service exists. The release worker must not fetch arbitrary user-supplied URLs or filesystem paths. One-time portal downloads can be added later with short-lived grants and audit, understanding that an authorized recipient can copy the released file.

### Offboarding

`requested -> access revoked -> active sessions terminated -> credentials rotated -> assets reviewed -> verified complete`

Disable identity and new logins; terminate gateway sessions and underlying OS sessions, background tasks, and any independent SSH/RDP connections; revoke repository tokens, VPN peers, application passwords, and export grants; transfer business ownership; preserve only authorized records; recover company equipment. Rotate shared credentials that the employee knew. Do not erase personal equipment.

Maintain separate statuses for each subsystem and retry safely. Target new-login denial and active-session termination within five minutes of an offboarding action under normal connectivity, verified end-to-end. Keycloak logout alone is insufficient. If automated session termination is not supported by a stable interface in the pinned gateway version, implement an approved extension or use a tested operator procedure and show offboarding as incomplete until verified.

## 13. Deployment and operations

Use Docker Compose for application development and suitable low-complexity service deployment inside separated VMs. Run the remote desktops as separate VMs, not privileged containers sharing an employee-accessible host. Use Ansible for repeatable host configuration and an existing supported hypervisor; choosing the hypervisor is an environment decision, not a reason to invent one.

Production controls:

- Pin supported releases and container digests; record an SBOM, licenses, upstream advisories, and the tested configuration. No floating `latest` tags in production.
- Use a restricted internal secret store or protected service credential files initially; no credentials in source, example configs, logs, browser bundles, or backup manifests.
- Mirror artifacts where required. Verify signatures/checksums from trustworthy release metadata and update in a lab before production.
- Separate identity, gateway, security, and management permissions. Application roles must not have unrestricted access to hypervisor or endpoint commands.
- Use separate backup credentials, encrypted database dumps, and restore rehearsals. A snapshot without database consistency is not a recovery plan.
- Maintain an independent audit copy on company-controlled storage with retention protections. Hash chaining adds tamper evidence but cannot make a log immutable against an administrator who controls both data and keys.
- Alert through an internal channel for identity outage, gateway errors, collector gaps, disk pressure, failed backups, certificate expiry, connector failures, and excessive failed logins.
- Assign one human owner for patching, triage, employee support, and restore drills. A dashboard without an operator does not protect data.

Proposed recovery targets: RPO 24 hours and RTO one business day for the first pilot. Restore Keycloak, gateway connection data, portal DB, internal repositories, workspace data, and configuration into a clean environment. If a one-day interruption is unacceptable, fund a spare host and improve backup frequency before production.

## 14. Delivery phases and effort

These are rough planning estimates for one experienced full-stack/infrastructure engineer with part-time IT/security review, existing server access, and compatible applications. Agent assistance does not replace real-device testing, license review, or an operational owner. Some work overlaps; do not add the ranges mechanically as a fixed delivery promise.

| Phase | Approximate effort | Exit condition |
| --- | --- | --- |
| 0. Discovery and decisions | 1–2 engineer days | Applications, data classes, countries, hardware, owners, and dependency policy documented |
| 1. One-user infrastructure lab | 3–5 days | MFA, isolated VM, gateway controls, security events, and backup/restore demonstrated |
| 2. Five-user security pilot | 3–5 days | Concurrent work, blocked transfer tests, onboarding/offboarding, and outage behavior accepted |
| 3. Portal MVP | 8–12 days | Employee view, work summary, read integrations, export queue, audit, RBAC, retention |
| 4. Integration and hardening | 5–8 days | Adversarial paths, dependency audit, authorization review, restore, runbooks, and rollback validated |
| 5. Optional local-laptop management | 5–10 additional days | Each supported OS and edition proven on physical company devices |

Expect approximately 4–7 calendar weeks for the core with timely decisions and review. Exclude kernel DLP development, universal app/browser interception, custom remote desktop protocols, GPU workstation engineering, payroll automation, and continuous screen recording. A usable one-user workspace can precede the portal.

## 15. Agent backlog with dependencies and acceptance

| ID | Priority / depends on | Work | Acceptance evidence |
| --- | --- | --- | --- |
| D01 | P0 | Record applications, ownership, jurisdictions, data classes, server inventory | Decision log distinguishes confirmed inputs from assumptions |
| D02 | P0 / D01 | Threat model and privacy/collection policy | Named owners approve categories and access before employee collection |
| D03 | P0 / D01 | License, edition, external-dependency and release audit | Exact version manifest; no unexplained hosted dependency |
| I01 | P0 / D01 | Network zones and deny-by-default firewall rules | BYOD and employee VM cannot reach admin/database/peer VM networks |
| I02 | P0 / I01 | Keycloak MFA and recovery setup | Employee/admin separation; login/recovery/logout tests |
| I03 | P0 / I01–I02 | Guacamole, guacd, one Linux/xrdp VM | Assigned user connects; another employee cannot; TLS verified |
| I04 | P0 / I03 | Transfer and egress restrictions | Clipboard, print, drive, SFTP, internet upload, alternate protocol tests |
| I05 | P0 / I01 | Wazuh and scoped telemetry | Synthetic change/login events arrive; collector outage is visible |
| I06 | P0 / I01–I05 | Encrypted independent backup and recovery | Restore to clean VM with sampled checksums and measured time |
| I07 | P0 / I03–I06 | Five-user concurrency and compatibility trial | Real application workload works; measured latency and resource report |
| P01 | P1 / I02 | API/UI scaffold, migrations, portal authentication | Repeatable local setup; no default production secrets |
| P02 | P0 / P01 | Object-level authorization and audit | Cross-user ID substitution denied; privileged actions recorded |
| P03 | P1 / P02 | Employee policy and personal-record views | Own data only; collection version and correction history visible |
| P04 | P1 / P02 | Work summary and internal tracker adapter | Deliverables and blockers shown; no keyboard-derived productivity score |
| P05 | P1 / I05,P02 | Wazuh read adapter and connector health | Deduplication, pagination, stale-state, and outage recovery demonstrated |
| P06 | P1 / P02 | Device/workspace inventory and posture model | Unknown distinct from compliant; ownership constraints enforced |
| P07 | P0 / P02 | Export request, review, and staged release workflow | No self-approval; exact object/recipient/expiry bound; receipt auditable |
| P08 | P0 / I02–I04,P02 | Offboarding workflow and runbook | Active sessions and independent credentials revoked; partial failure surfaced |
| P09 | P1 / P02–P08 | Retention, holds, deletion and restore handling | Expiry deletes expected data; holds and restored tombstones verified |
| Q01 | P0 / all core tasks | Security review and outbound-traffic verification | No unauthorized routes, SaaS telemetry, content logs, or exposed secrets |
| Q02 | P0 / Q01 | Pilot rollout and rollback rehearsal | One user first; then five; successful restore and owner handover |
| L01 | P2 / pilot | Fleet evaluation on company laptop | Edition-aware checklist, physical-device policy and tamper tests |
| L02 | P2 / L01 | Posture-aware local access gate | Every local sensitive route covered; stale data cannot silently permit access |
| L03 | P2 / pilot | Kimai or optional work-session metrics | Adopt only for demonstrated business need; collection policy updated |

P0 means a release prerequisite, not necessarily the first task chronologically. P1 is core product work. P2 is optional after the five-person pilot.

## 16. Required validation scenarios

Use synthetic canary documents and test credentials; never real customer secrets for trial exfiltration. Store test steps, exact versions, configurations, timestamps, observed results, and evidence references internally. Label each control as planned, configured, tested, or failed.

1. **Identity:** MFA is required; disabled employees cannot start a new session; shared accounts are absent.
2. **Isolation:** employee A cannot access employee B's VM, task records, export objects, or security cases by changing an ID.
3. **Clipboard:** copy text, images, and files from remote to local through every enabled client/protocol; expected blocked paths are actually blocked.
4. **Transfer channels:** printing/PDF, RDP drives, SFTP, gateway upload/download, session sharing, and direct SSH/RDP cannot bypass policy.
5. **Egress:** personal cloud upload, webmail, external Git, alternate DNS, redirects, arbitrary outbound sockets, and personal accounts on allowed domains are denied in the sensitive VM.
6. **Developer privileges:** employee code cannot access container sockets, host files, CI secrets, hypervisor management, or another workspace's credentials.
7. **Export:** self-approval, changed object version, expired approval, recipient substitution, path traversal, arbitrary URL fetching, and double release are rejected.
8. **Offboarding:** keep a session and long-running job open, then offboard; verify gateway, OS, application tokens, VPN, and pending releases independently.
9. **Collector failure:** stop an authorized lab collector or cut its network route; the portal becomes unknown/stale and does not report compliant.
10. **Tamper controls:** a standard company-laptop user cannot stop/uninstall required services through supported ordinary-user actions; IT can maintain them through an audited workflow.
11. **Offline behavior:** new restricted local access fails closed when posture is stale; existing access follows the tested termination rule. BYOD uses remote-only policy.
12. **Replay and ingestion:** duplicate/reordered events do not duplicate cases; revoked connector credentials and pagination failures produce visible errors.
13. **Privacy:** URL query strings, window titles, clipboard bodies, passwords, and screenshot content are absent from standard telemetry and logs.
14. **Manager scope:** managers see authorized work summaries, not broad security evidence or other teams' records; employee data exports are access controlled.
15. **Recovery:** restore onto clean infrastructure, rotate compromised secrets, reapply deletions/holds, and meet agreed recovery targets.
16. **Dependencies:** observe traffic with the internet disconnected or restricted; identify every external dependency; no silent fallback to hosted relays or analytics.
17. **Concurrency:** five people perform actual work simultaneously; document median/p95 login and interaction latency, CPU, memory, disk, and application results.
18. **Negative evidence:** demonstrate that a phone camera or compromised BYOD host remains outside prevention claims; describe this honestly in the owner handover.

No release on happy-path UI screenshots alone. Tests must exercise the real enforcement points and supported endpoint OS builds. This planning package does not claim any of these runtime tests have passed.

## 17. Costs and build versus buy

For five employees, operational effort will often matter more than per-seat subscription arithmetic. Start with the remote workspace controls and proven workflows; build custom workflow code after the lab works. Do not spend months writing a DLP agent to avoid a modest license fee.

Use this cost model, filling in actual quotes:

```text
Monthly equivalent = hardware purchase / useful-life months
                   + electricity + backup storage + connectivity increment
                   + licensed features + OS/application licenses
                   + maintenance hours * actual hourly cost

Initial implementation = engineer days * actual day rate
                       + hardware/setup purchases + independent review

Optional laptop purchase = company laptop count * delivered unit cost
```

Illustration only, in your chosen currency: server/backup hardware 2,000; useful life 36 months; power/backup/connectivity 50/month; maintenance 4 hours at 30/hour; optional licenses 0. Monthly equivalent is approximately 226 before laptops, taxes, OS/app licenses, engineering implementation, or downtime costs. These are arbitrary budget inputs, not market prices. Replace them with your actual existing-server costs and quotations.

Choose a paid, self-hosted endpoint DLP product only if there is a demonstrated requirement for local content-aware controls that the remote-workspace design cannot meet. Require a supported on-premises architecture, no unapproved telemetry, an OS/browser/channel matrix, trial evidence, and five-seat commercial terms. Reusing open-source components is not evidence that a custom bundle will outperform maintained commercial DLP.

## 18. Governance and employee notice

Before collecting employee work-activity data, identify the relevant countries and have the employer's appropriate adviser review purpose, lawful basis, proportionality, consultation obligations, employee access/correction, retention, and any cross-border flows. An employee acknowledgement is not automatically a valid lawful basis for every kind of monitoring. The UK ICO's worker-monitoring guidance is a useful example of necessity, transparency, and impact assessment; it is UK-specific and currently marked under review, not a substitute for applicable local advice. [ICO worker monitoring guidance](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/employment/monitoring-workers/data-protection-and-monitoring-workers/).

The notice should explain: why collection happens, ownership-specific scope, exact categories, collection times, who can access data, retention, security escalation, employee review/correction, personal-device limits, and the contact person. Keep security evidence separate from work-performance assessment. Do not automate discipline or employment decisions from activity signals.

## 19. Copy and give this instruction to the implementation agent

```text
Implement the Employee Security and Work Visibility plan for approximately five
employees. All business data, employee telemetry, identity services, logs, and
backups must remain on company-controlled servers.

Read this entire plan, then start with D01-D03 and an isolated synthetic-data lab.
Preserve confirmed constraints. Ask for missing application/OS/country/hardware
information while completing independent local development. Document assumptions.

Use Keycloak, Apache Guacamole, separate employee VMs with xrdp when Linux is
compatible, Wazuh, and encrypted independent backups. Add Gitea, Fleet, Kimai,
or self-hosted NetBird only when the stated need exists. Inspect exact stable
release licenses, dependencies, security advisories, and edition limitations.
Never assume paid capabilities are free or that a GitHub main branch is stable.

Build a small portal, not a new endpoint surveillance platform. Use the existing
supported stack, or React/TypeScript + FastAPI/Python + PostgreSQL. Keep vendor
services and schemas separate. Add SSO links and read-only adapters first.
Implement scoped authorization, work summaries, collection transparency,
connector health, export approvals, offboarding, audit, and retention.

Do not implement stealth, undetectability, keylogging, password capture, camera/
microphone surveillance, rootkits, permission bypass, uninstall evasion, or any
personal-device wipe. Use supported service permissions on company devices and
server-side restrictions. Treat stale endpoint state as unknown. Do not claim
total prevention of screen capture, photos, transcription, or admin tampering.

Do not treat authentication as complete session revocation. Prove gateway and
underlying OS session termination, credential revocation, and pending-export
revocation end-to-end. Do not use undocumented vendor APIs as stable contracts
without a pinned-version adapter and compatibility tests. Do not write directly
to vendor databases for routine lifecycle integration.

Deliver a runnable lab deployment, reproducible configuration, version/license
manifest, threat model, automated meaningful tests, real-boundary test evidence,
backup/restore instructions, employee notice draft, operating runbooks, rollback,
and a release report marking each control planned/configured/tested/failed.

Work through the backlog in dependency order. Do not introduce Kubernetes,
Kafka, custom kernel drivers, or always-on screen recording. Do not connect real
employees or production data until the deployment owner has accepted the
collection policy, jurisdiction review, dependency exceptions, and pilot results.
```

## 20. Definition of done

The implementation is complete when all five employees can perform their actual assigned work; sensitive files stay in company-controlled workspaces except approved releases; tested transfer and egress paths enforce the chosen policy; managers can review deliverables and blockers; employees can inspect their own collection scope and records; access revocation covers active sessions and credentials; collector gaps are visible; a clean restore succeeds; and an identified owner can operate, update, and recover the system.

Every residual risk, unsupported OS/application/channel, manual step, paid feature, and external dependency must be explicit. The finished system should be described in terms of controls actually tested, never as invisible, unstoppable, or leak-proof.
