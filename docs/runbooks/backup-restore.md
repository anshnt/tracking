# Runbook: backup and restore

Owner: administrator owner (TBD) and recovery approver (TBD). Targets for the pilot: RPO 24 hours, RTO one business day. Not yet measured; a rehearsal must record real numbers.

## What is backed up

Keycloak realm and database, Guacamole connection data, the portal database, internal repositories, workspace data, configuration (Ansible inventory and compose files, without secrets in plain text), and the independent audit copy. Wazuh configuration; log retention as decided.

## Backup (daily)

1. Take application-consistent dumps: `pg_dump` per database (Keycloak, Guacamole, portal). A filesystem snapshot alone is not a backup.
2. restic backup of dumps, repositories and workspace data to the separate company-controlled target. Use a separate backup credential that cannot reach production and a repository password held offline by the recovery approver.
3. `restic check` weekly; `restic forget --prune` to the retention rotation (must not exceed the retention policy; expired employee data must not outlive its schedule in backups).
4. Alert on a missed or failed backup.

## Restore rehearsal (quarterly and before the pilot)

1. Prepare a clean VM with no connection to production. Note the start time.
2. Restore the latest snapshot with restic. Restore each database dump with `pg_restore`.
3. Run `alembic upgrade head` against the restored portal database with the matching release.
4. **Reapply deletion tombstones and legal holds.** Rows in `deletion_tombstones` record data that was lawfully deleted after the backup was taken. Check `legal_holds` is current, then run `uv run python -m portal.retention --reapply` from `apps/api` (with `DATABASE_URL` set) so tombstoned records are removed again. Verify a sampled tombstoned record is absent and a held record is present.
5. Rotate compromised or exposed secrets: OIDC client secret, DB role passwords, connector tokens, session secret. Revoke all portal sessions (clear the `sessions` table).
6. Bring up Keycloak, Guacamole, portal and worker; sign in as a test user; open a workspace.
7. Sample checksums on at least 20 files from workspace data and repositories against the source manifest.
8. Record the end time, achieved RTO, backup age (achieved RPO), failures and fixes. File the record with the validation evidence (scenario 15).

## Real recovery

Same as the rehearsal, with the recovery approver present. Do not reconnect the restored environment to employees until secrets are rotated and tombstones reapplied. Record the audit copy gap between the last backed-up audit event and the incident.
