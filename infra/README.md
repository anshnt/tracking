# Infrastructure as code (backlog I01-I07, PLAN sections 6, 7, 11, 13)

Configuration for a single-host synthetic lab (Docker Compose) and for the production-shaped
split across VMs (Ansible). **Nothing here has been run against real infrastructure.** It was
authored on a machine without Docker. See "Status" for exactly what was checked.

```
infra/
  versions.env, VERSIONS.md, digests.txt   pinned versions, sources, digest TODOs
  compose/                                  lab stack (caddy, keycloak, postgres, portal, guacamole, gitea)
  keycloak/realm-tracking.json              realm import
  guacamole/                                RDP connection templates, SAML property reference, provisioning script
  ansible/                                  roles: common, network_zones, workspace_vm, guacamole_host,
                                            wazuh_agent, backup, portal_host
  tests/validate.py                         offline checks (below)
policies/                                   collection, egress, classification, transfer policy
Dockerfile, .dockerignore                   portal image (API + worker + built web UI)
```

## Bring up the lab

Order matters. Run from `infra/compose`.

1. `cp .env.example .env`, then replace every `CHANGE_ME` (`openssl rand -base64 32`). Set `LAB_DOMAIN`,
   `MGMT_CIDR` (who may open the Keycloak admin console) and `GUAC_BOOTSTRAP_ADMIN` (your email).
2. Add `portal.`, `auth.`, `desktop.`, `git.` + `LAB_DOMAIN` to the hosts file of the test laptop, pointing at the lab host.
3. Build and start (the portal image needs `apps/web` to exist, see "Known gaps"):
   `docker compose --env-file ../versions.env --env-file .env -f docker-compose.lab.yml up -d --build`
   Add `--profile gitea` for internal Git. Startup order is enforced by healthchecks and one-shot jobs:
   postgres (creates roles/databases) -> keycloak (imports the realm) -> portal-migrate (alembic as the owner role)
   -> portal-grants (runtime role loses UPDATE/DELETE/TRUNCATE on `audit_events`, `policy_versions`)
   -> portal-api/worker; guac-schema -> guac-db-init (loads schema, disables `guacadmin`, creates the SAML admin) -> guacamole.
4. Trust the internal CA: copy `root.crt` out of the `lab_ca` volume (the `caddy-ca-export` job copies only the public
   certificate there; the portal reads it from that volume) to the laptop.
   Guacamole's JVM must also trust it to fetch the Keycloak SAML metadata: build a truststore with `keytool`,
   mount it into the guacamole container and set `GUAC_JAVA_OPTS=-Djavax.net.ssl.trustStore=...` (not automated yet).
5. Keycloak: sign in to `https://auth.<LAB_DOMAIN>/admin` from `MGMT_CIDR` with the bootstrap account, create a
   **separate named admin** for the master realm, delete the bootstrap account. In realm `tracking` create users;
   each gets the `employee` role by default and must enrol an OTP on first login. Give `admin`, `it`, `security`,
   `approver` only to separate admin identities, never to an employee's everyday account.
6. Wazuh: official single-node deployment, see `compose/wazuh/README.md`.
7. Workspace VMs: run the Ansible playbooks (below), then `guacamole/provision-connection.sh` per employee with the
   fingerprint the `workspace_vm` role prints.
8. Backups: Ansible `backup` role, then run `/usr/local/sbin/tracking-restore-test.sh` once by hand.

## Production-shaped deployment (Ansible)

```sh
cd infra/ansible
ansible-galaxy collection install -r requirements.yml
cp inventory.example.yml inventory.yml            # edit hosts, zones, one employee per workspace VM
cp group_vars/vault.example.yml group_vars/vault.yml && ansible-vault encrypt group_vars/vault.yml
ansible-playbook playbooks/site.yml --ask-vault-pass --check --diff    # dry run first
```

Roles refuse to run with `CHANGE_ME` or `TODO` values. Zone CIDRs and allowed flows are data in
`group_vars/all.yml`; the `network_zones` role asserts the isolation rules before writing any firewall:
workspace VMs may talk only to named hosts, never to other workspaces, `mgmt` or `data`, and only the guacd
addresses may reach 3389. Run Ansible from the management network.

Prerequisites the playbooks assume (none are fetched from the internet by hosts that default-deny egress):

- `internal_mirror_url` serves `/debian`, `/debian-security` and `/wazuh/4.x/apt/`; the `common` role points every
  egress-dropped zone (workspace) at it. Put the official Wazuh GPG key at `infra/ansible/files/GPG-KEY-WAZUH`;
  its sha256 must equal `vault_wazuh_gpg_key_sha256`.
- Backups: `data01` pushes to restic on `backup01` over sftp (flow `backup-to-repo`). The `backup_repo` role creates
  the `restic` account, limited to the data host's address; the `backup` role installs a dedicated key and a pinned
  host key (`vault_backup_ssh_private_key`, `vault_backup_ssh_public_key`, `vault_backup_repo_host_key`).
- Guacamole: set `guacamole_bootstrap_admin` (your email). The `guacamole_host` role loads the schema, runs
  `compose/postgres/guacamole-bootstrap.sql` and fails if `guacadmin` is still enabled.
- The `guacd` container's bridge (`br-guac-rdp`) may only forward RDP to the workspace zone (nft chain `guacd_egress`).

Data-zone Postgres on its own VM: reuse `compose/postgres/01-init-roles.sh` and `portal-grants.sql`
(there is no Ansible role for it yet).

## Decisions worth knowing

- Per-service Postgres roles and databases; the superuser is used only by the init script. The portal has a
  schema-owner role (migrations) and a DML-only runtime role. A `backup` role has `pg_read_all_data` only.
- Networks `app`, `gateway`, `data` are Docker-internal (no route out). Only caddy publishes a port. guacd is on
  `gateway` (with guacamole) and `workspace` (the only network that can reach RDP hosts).
- Workspace VMs: unprivileged user per employee, no sudo, no container runtime, xrdp TLS only, drive/printer
  channel off, clipboard export restricted on the VM and by Guacamole. No stealth, screenshots, recordings,
  keylogging or personal-device control exist anywhere in this tree.
- PostgreSQL 17 is pinned rather than 18 so the Debian 13 `postgresql-client-17` matches the server for `pg_dump`.
- Wazuh 4.14.10 is pinned; 5.0 is still a release candidate.

## Status per control

"configured" means files exist and passed the offline checks below. Nothing is "tested" in the sense of PLAN
section 16 yet; every row needs a run on real infrastructure.

| Backlog | Control | Status |
| --- | --- | --- |
| I01 | nftables deny-by-default zones, workspace isolation, guacd-only RDP | configured; ruleset rendered and asserted, `nft -c` not run (no nft available), not tested on hosts |
| I01 | Hypervisor/segment firewall mirroring the host rules | planned (environment decision) |
| I02 | Keycloak realm: roles, confidential PKCE client, SAML client, OTP enrolment forced by default required action, brute force, short tokens | configured; JSON parses and invariants asserted; not imported into a running Keycloak |
| I02 | Recovery, logout, admin separation procedures | planned (documented in realm attributes only) |
| I03 | Guacamole + guacd + SAML, per-user connection grants | configured; not run; `cert-fingerprints` parameter to verify for 1.6.0 |
| I03 | xrdp VM, unique user, TLS, no sudo | configured; not run |
| I04 | Transfer restrictions (Guacamole flags, xrdp channels) | configured; clipboard/print/drive/SFTP/upload tests not run |
| I04 | Internet egress block for sensitive VMs | configured as nftables output default-drop; alternate-protocol tests not run |
| I05 | Wazuh server (official stack) | planned; instructions only |
| I05 | Wazuh agent on workspace VMs, scoped collection, restart-on-failure | configured; not run; apt key and registration checksums are TODO placeholders |
| I06 | restic backup, per-DB pg_dump, retention, restore and restore-test scripts | configured; `bash -n` passed, not run; RPO/RTO unmeasured |
| I06 | Append-only/independent prune, Keycloak realm export command, Gitea dump | planned / optional hooks present |
| I07 | Five-user concurrency trial | planned |
| P08 | Gateway session termination adapter | planned (out of scope here) |
| Q01 | Outbound traffic inventory, SBOM, digests | planned (`digests.txt` has TODO markers) |

## Offline validation

`uv run --with pyyaml --with jinja2 python infra/tests/validate.py` parses every YAML and JSON file, parses Jinja,
bans the em dash, floating `latest` tags and CRLF, checks the Guacamole templates against
`policies/guacamole-transfer-policy.yaml`, asserts Keycloak realm invariants and compose network wiring, renders the
firewall for a workspace and a gateway host and checks the key rules, and runs `bash -n` on every script.
Also run once from WSL: `ansible-playbook --syntax-check` on all five playbooks (ansible-core 2.21.6) passed.
Not run: `docker compose config`, `docker build`, `nft -c`, `shellcheck`, any play against a host.

## Known gaps

- `apps/web` did not exist when this was written; the Dockerfile expects `apps/web/package.json`, `package-lock.json`
  and an `npm run build` that emits `dist/`.
- Guacamole to RDP uses a second login prompt (no SSO to RDP). Certificate pinning relies on `cert-fingerprints`.
- guacd and workspace DNAT filtering on Docker hosts relies on a prerouting chain; verify with real published ports.
- The restore script does not re-apply deletion tombstones or legal holds automatically (PLAN P09).
- Prune runs from the host that has write credentials; use an append-only repository to protect against a
  compromised source host.
- Gitea tag `28.3.0` and Docker Hub availability were not verified.
