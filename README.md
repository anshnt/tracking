# tracking

Work and Security Portal for a five-person, self-hosted team: identity and MFA (Keycloak), browser access to isolated Linux workspaces (Guacamole + xrdp), security telemetry (Wazuh), encrypted backups (restic), and a small portal for work summaries, collection transparency, export approvals, offboarding and audit.

The plan this repository implements is in [docs/plan/PLAN.md](docs/plan/PLAN.md) ([HTML version](docs/plan/plan.html)).

No stealth, keylogging, screen recording, camera/microphone capture or personal-device wipe. Controls are described by what has actually been tested.

## What is in this repository

```
apps/api/            FastAPI portal API, worker, connectors, Alembic migrations (Python 3.13, uv, package "portal")
apps/web/            React + TypeScript UI (Vite); built into apps/web/dist and served by the API
packages/contracts/  openapi.json (generated) and event.schema.json (normalized event)
infra/               Docker Compose lab, Keycloak realm, Guacamole templates, Ansible roles, offline validator
policies/            collection, egress, classification and file-transfer policies
docs/                plan, ADRs, threat model, privacy notice draft, runbooks, validation test plan
Dockerfile           one image for the API, the worker and migrations
```

The worker is the same package as the API: `python -m portal.worker`. It runs the Postgres job queue
(connector polls, retention, export staging and expiry, offboarding steps, case creation).

## Quickstart (local development)

You need Python 3.13 with [uv](https://docs.astral.sh/uv/), Node 22 or later, and a PostgreSQL 16 or 17
you can reach. Docker is not required for any of this.

```sh
# API (from apps/api). Any empty database works; this URL is the dev default.
export DATABASE_URL=postgresql+psycopg://tracking:tracking@127.0.0.1:5433/tracking
export PORTAL_ENV=development PORTAL_DEV_AUTH=1
export PUBLIC_ORIGIN=http://localhost:5173      # the origin the browser uses (CSRF checks it)
uv sync
uv run alembic upgrade head
uv run uvicorn portal.main:app --port 8000
uv run python -m portal.worker                  # in a second shell

# Web (from apps/web), in a third shell; /api is proxied to 127.0.0.1:8000
npm ci
npm run dev                                     # http://localhost:5173
```

Dev sign-in, without Keycloak: `POST /api/auth/dev-login` with `{"subject": "dev-admin", "roles": ["admin"]}`
(plus the `Origin` and `X-Requested-With: portal` headers every write needs). It answers 404 unless
`PORTAL_ENV=development` and `PORTAL_DEV_AUTH=1`, and production refuses to start with dev auth,
`CHANGE_ME` placeholders, the dev database URL, a non-https `PUBLIC_ORIGIN` or no `OIDC_ISSUER`.

Optional connectors are off by default and enabled with `<NAME>_ENABLED=1` plus their URL and token
variables (Wazuh, Keycloak, Guacamole, Gitea, Fleet, Kimai, xrdp); see the module docstrings in
`apps/api/portal/connectors/`.

## Tests

```sh
cd apps/api
export TEST_DATABASE_URL=postgresql+psycopg://tracking:tracking@127.0.0.1:5433/tracking_test  # created if missing
uv run ruff check . && uv run ruff format --check .
uv run pytest -q

cd ../web && npm test && npm run build

# infra, offline (no Docker needed)
uv run --with pyyaml --with jinja2 python infra/tests/validate.py
```

After changing a route or schema, refresh the contract: `cd apps/api && uv run python scripts/export_openapi.py`.
`tests/test_contracts.py` fails if `packages/contracts/openapi.json` is stale. CI (`.github/workflows/ci.yml`)
runs the API, web, infra and Docker image jobs.

## Documentation

- [docs/plan/PLAN.md](docs/plan/PLAN.md): the spec
- [docs/decisions](docs/decisions), [docs/decision-log.md](docs/decision-log.md), [docs/threat-model.md](docs/threat-model.md)
- [docs/runbooks](docs/runbooks): onboarding, offboarding, backup and restore, incidents, break glass, connectors, export release
- [docs/validation/test-plan.md](docs/validation/test-plan.md): the 18 scenarios and their honest status
- [docs/privacy](docs/privacy): collection policy and the draft employee notice (needs jurisdiction review)
- [docs/operations/owner-handover.md](docs/operations/owner-handover.md): residual risks
- [infra/README.md](infra/README.md): lab bring-up, Ansible roles, pinned versions

## What is tested and what is not

Tested (automated, against a real local PostgreSQL, with upstream services faked by mock HTTP transports):
the API and its authorization rules (roles, object-level 404s, CSRF, sessions), audit append-only triggers,
the job queue and worker handlers, event ingest and retention, export approvals, security cases,
offboarding orchestration, connector error handling, the OpenAPI contract, the web client's request
rules (typecheck, build, unit tests), and the infra files offline (parsing, policy and realm invariants,
nftables rendering, Ansible syntax checks).

Not tested: anything against real Keycloak, Guacamole, xrdp, Wazuh, Gitea, Fleet or Kimai; the web UI in a
browser against a live API; Docker builds and the Compose lab; Ansible runs against hosts; firewall rules
(`nft`); backups and restores on real storage; and the real-boundary scenarios in the validation plan
(clipboard, transfer channels, egress, tamper, isolation). Controls are labelled planned, configured,
tested or failed in `docs/validation/test-plan.md`, and nothing is called tested there unless it was.
Known gaps are listed in [docs/operations/owner-handover.md](docs/operations/owner-handover.md).
