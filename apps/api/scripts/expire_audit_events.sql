-- Audit expiry (PLAN s9, 180 days). Run by the DATABASE OWNER role, never the app role:
--   psql "$OWNER_DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/expire_audit_events.sql
-- audit_events is append-only; the trigger is disabled for this one transaction only.
-- The run is recorded as a deletion_tombstones row (identifiers and counts only).
BEGIN;
ALTER TABLE audit_events DISABLE TRIGGER audit_events_append_only;
WITH gone AS (
    DELETE FROM audit_events WHERE created_at < now() - interval '180 days' RETURNING id
)
INSERT INTO deletion_tombstones (subject_type, subject_id, rule)
SELECT 'audit_events_expiry', to_char(now(), 'YYYY-MM-DD"T"HH24:MI:SSOF') || ' count=' || count(*),
       'approvals-180d'
FROM gone;
ALTER TABLE audit_events ENABLE TRIGGER audit_events_append_only;
COMMIT;
