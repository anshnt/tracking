#!/bin/sh
# Runs once on first start of an empty data directory (postgres entrypoint).
# One database + one login role per service. Apps never get the superuser.
# The bootstrap superuser (POSTGRES_USER) is only used by this script and by break-glass admin work.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v kc_pw="$KEYCLOAK_DB_PASSWORD" \
  -v guac_pw="$GUACAMOLE_DB_PASSWORD" \
  -v mig_pw="$PORTAL_MIGRATOR_DB_PASSWORD" \
  -v app_pw="$PORTAL_DB_PASSWORD" \
  -v gitea_pw="$GITEA_DB_PASSWORD" \
  -v bak_pw="$BACKUP_DB_PASSWORD" <<'SQL'
-- Roles (NOSUPERUSER etc. are the defaults, spelled out on purpose)
CREATE ROLE keycloak        LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'kc_pw';
CREATE ROLE guacamole       LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'guac_pw';
CREATE ROLE gitea           LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'gitea_pw';
-- portal_migrator owns the schema (runs alembic); portal is the runtime role with DML only.
CREATE ROLE portal_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'mig_pw';
CREATE ROLE portal          LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'app_pw';
-- read-only role for pg_dump; separate credential from every app
CREATE ROLE backup          LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD :'bak_pw';
GRANT pg_read_all_data TO backup;

CREATE DATABASE keycloak  OWNER keycloak;
CREATE DATABASE guacamole OWNER guacamole;
CREATE DATABASE gitea     OWNER gitea;
CREATE DATABASE portal    OWNER portal_migrator;

-- nobody connects to a database they do not belong to
REVOKE CONNECT ON DATABASE keycloak, guacamole, gitea, portal FROM PUBLIC;
GRANT CONNECT ON DATABASE keycloak  TO keycloak, backup;
GRANT CONNECT ON DATABASE guacamole TO guacamole, backup;
GRANT CONNECT ON DATABASE gitea     TO gitea, backup;
GRANT CONNECT ON DATABASE portal    TO portal_migrator, portal, backup;
SQL

# Runtime role gets DML on whatever the migrator creates from now on.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname portal <<'SQL'
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO portal, backup;
GRANT CREATE ON SCHEMA public TO portal_migrator;
ALTER DEFAULT PRIVILEGES FOR ROLE portal_migrator IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO portal;
ALTER DEFAULT PRIVILEGES FOR ROLE portal_migrator IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO portal;
SQL
# audit_events / policy_versions are append-only: portal-grants.sql (run after migrations)
# removes UPDATE/DELETE from the runtime role on those tables.
