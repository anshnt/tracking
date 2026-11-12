# Version manifest (D03)

Checked 2026-11-12. Sources: `infra/versions.env`, `infra/VERSIONS.md`, `apps/api/uv.lock` (resolved with `uv sync --frozen`), `apps/web/package-lock.json` (`npm ci`). Versions listed here are the ones pinned or resolved on that date. Digests and an SBOM are not produced yet (`infra/digests.txt` has TODO markers). Licenses for infra images come from `infra/VERSIONS.md`; licenses for Python and Node packages were read from installed package metadata. Nobody has done a legal license review.

## Infrastructure components (infra/versions.env)

| Component | Version | License | Source | External network need | Notes |
| --- | --- | --- | --- | --- | --- |
| Keycloak | 26.8.2 | Apache-2.0 | quay.io/keycloak/keycloak | Image pull; none at run time except the configured IdP federation, if any | Community edition. |
| Apache Guacamole (web + guacd) | 1.6.0 | Apache-2.0 | guacamole/guacamole, guacamole/guacd | Image pull | Same tag for both images. |
| PostgreSQL | 17.11 | PostgreSQL License | postgres image / Debian postgresql-client-17 | Image or apt pull | The minor may have moved on 2026-11-12; re-check. Local tests ran on a WSL Postgres 16, not 17. |
| Caddy | 2.11.9 | Apache-2.0 | caddy image | Image pull. Internal CA in the lab; a public ACME CA only if the owner chooses it | |
| Wazuh | 4.14.10 | GPL-2.0 (agent, manager), mixed for indexer and dashboard | wazuh-docker tag v4.14.10, Wazuh apt repo for agents | Image pull, apt repo (or internal mirror, `internal_mirror_url`) | 5.0.0 is release-candidate only, so not used. apt key and registration checksums are TODO placeholders. |
| Gitea | 28.3.0 | MIT | gitea/gitea | Image pull | Optional profile. Docker tag `28.3.0` is NOT verified on Docker Hub. |
| restic | 0.19.1 | BSD-2-Clause | GitHub release binary | Binary download | `restic_sha256` must be filled in by the operator; playbooks refuse TODO values. |
| Node (build stage) | 22-bookworm-slim | MIT | Docker Hub node | Image pull at build time | Major tag, no digest yet. |
| Python (runtime) | 3.13-slim-bookworm | PSF | Docker Hub python | Image pull at build time | Major.minor tag, no digest yet. |
| uv | 0.11.18 | MIT / Apache-2.0 | astral-sh/uv | Build time only | Copied into the build stage. |

## API dependencies (apps/api, direct)

| Package | Resolved version | License |
| --- | --- | --- |
| fastapi | 0.162.5 | MIT |
| uvicorn[standard] | 0.54.0 | BSD-3-Clause |
| sqlalchemy | 2.1.8 | MIT |
| psycopg[binary] | 3.3.8 | LGPL-3.0-only (bundled libpq wheels are separate; review before distributing) |
| alembic | 1.20.1 | MIT |
| pydantic-settings | 2.16.2 | MIT |
| httpx | 0.28.1 | BSD-3-Clause |
| pyjwt[crypto] | 2.15.1 | MIT |
| python-multipart | 0.0.33 | Apache-2.0 |
| pytest (dev) | 9.2.0 | MIT |
| ruff (dev) | 0.17.4 | MIT |

Notable transitive: pydantic 2.14.3, starlette 1.10.0, cryptography 50.0.2 (Apache-2.0 or BSD). 43 packages in the lock in total; their licenses were not individually audited.

## Web dependencies (apps/web, from package.json and installed metadata)

| Package | Resolved version | License | Kind |
| --- | --- | --- | --- |
| react | 19.3.1 | MIT | runtime |
| react-dom | 19.3.1 | MIT | runtime |
| react-router-dom | 7.18.5 | MIT | runtime |
| vite | 8.3.8 | MIT | build |
| vitest | 5.1.0 | MIT | test |
| typescript | 7.0.2 | Apache-2.0 | build |
| jsdom | 31.0.0 | MIT | test |
| @vitejs/plugin-react, @testing-library/react, @testing-library/jest-dom, @types/react, @types/react-dom | per package-lock.json | not individually checked | build/test |

The built page loads no external fonts, CDN scripts, analytics or hosted APIs (no `https://` references in `apps/web/index.html` or `apps/web/src`). `npm ci` reported 0 vulnerabilities on 2026-11-12; that is a point-in-time check against the npm advisory feed.

## External network dependencies

- Build time: Docker Hub / quay.io image pulls, PyPI (uv), npm registry, GitHub release download for restic, astral uv image/binary.
- Install time on workspace VMs: Debian apt (or the internal mirror), Wazuh apt repo (or mirror). The workspace egress firewall blocks these unless the mirror is reachable; the run-time list is in `policies/egress-allowlist.yaml`.
- Run time: none inventoried as required beyond the owner's own Keycloak, Guacamole, Wazuh, Gitea and backup hosts. This has NOT been verified by observing real traffic (scenario 16, Q01).

## Paid or edition-limited features not used

- Keycloak: no Red Hat build of Keycloak, no support subscription.
- Guacamole: no commercial gateway or paid session-recording add-on; no session recording is configured.
- Wazuh: open source stack only; no Wazuh Cloud, no paid support tier. No EDR product is assumed.
- No hosted SaaS: no Sentry, analytics, hosted identity, hosted logging, hosted backup, hosted time tracker.
- Kimai and other optional work-session metrics are not included (L03).
- Windows or macOS fleet-management editions: not used. Employee workspaces are Linux VMs with xrdp.
