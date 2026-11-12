# ADR 0003: Repository layout

Status: accepted. Spec: PLAN.md section 10, which proposed a slightly different tree.

## Layout

```text
apps/api/             Python package "portal": API, worker and connectors together
  portal/routers/     HTTP routers, mounted at /api/v1
  portal/handlers/    Job handlers, auto-imported by the worker
  portal/connectors/  Event sources and revocation adapters, with fakes for tests
  tests/              pytest suite (unit and integration, real Postgres)
  alembic/            Migrations
apps/web/             React UI, served from dist by the API when built
packages/contracts/   Exported OpenAPI and event schema (generated from the API)
infra/                Compose files and Ansible roles
policies/             Versioned policy templates and collection allowlists
docs/                 Decisions, threat model, privacy, runbooks, validation, operations
```

## Deviation from the plan

The plan lists `apps/worker/`, a top-level `connectors/` and a top-level `tests/`. We use one Python package and one container image instead:

- The worker, API and connectors share models, config, audit and the job helpers. Splitting them means a shared library or duplicated code.
- One image, one dependency lock, one migration history. The same image runs as `uvicorn portal.main:app` or `python -m portal.worker`.
- Tests sit next to the code they exercise and reuse one set of fixtures.

The boundaries the plan cares about still hold: connectors only talk through the interfaces in `portal/connectors/base.py`, the worker only runs registered handlers, and vendor databases are never touched. Ceiling: if the worker ever needs different privileges or scaling from the API, split it into its own image then (same package, second entrypoint and a second database role).
