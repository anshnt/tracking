# Runbook: patching and upgrades

Owner: administrator owner (TBD). Check upstream advisories weekly for Keycloak, Guacamole and guacd, xrdp, Wazuh, PostgreSQL, the base OS of every VM, and the portal's Python and Node dependencies.

## Rules

- Pin exact releases and container digests. No floating `latest` tags in production.
- Verify checksums and signatures from the vendor's release metadata. Read the licence and bundled dependencies of the exact release; record them in the version manifest.
- Try every upgrade in a lab first, then production. Never test on production data.
- Take and verify a backup (docs/runbooks/backup-restore.md) before any upgrade that changes data.
- Gateway and identity are high risk: patch security fixes for Keycloak and Guacamole promptly, within days for critical advisories.
- Prefer a spare maintenance window announced to employees.

## Routine

1. Review advisories; list affected components.
2. Update the lab. Run the portal tests (`cd apps/api && uv run pytest -q`) and the relevant validation scenarios (identity, transfer controls, egress) because an upgrade can reset gateway settings.
3. Check gateway transfer settings (clipboard, drive, printing, SFTP) are still disabled after the upgrade.
4. Apply to production. Run `uv run alembic upgrade head` for portal releases. Check `/api/health`.
5. Record versions, date, operator and result. Keep the previous release and database dump for rollback.

## Rollback

Redeploy the previous pinned release. If a migration ran, restore the pre-upgrade database dump (a migration is not assumed reversible). Note that the audit table cannot be edited, so restore from the dump rather than deleting rows.

## Portal dependency updates

Update `uv.lock` deliberately, run the full test suite and `ruff`, and review changed packages. Do not allow unreviewed automatic updates in production.
