#!/bin/sh
# One-shot after alembic: restrict the runtime role on append-only tables.
set -eu
export PGPASSWORD="$PORTAL_MIGRATOR_DB_PASSWORD"
psql -v ON_ERROR_STOP=1 -h postgres -U portal_migrator -d portal -f /postgres/portal-grants.sql
