-- Run as portal_migrator after `alembic upgrade head`. Idempotent.
-- The DB triggers already block UPDATE/DELETE; this also blocks TRUNCATE and makes the
-- runtime role incapable of it even if a trigger is dropped.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO portal;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO portal;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO backup;
REVOKE UPDATE, DELETE, TRUNCATE ON audit_events FROM portal;
REVOKE UPDATE, DELETE, TRUNCATE ON policy_versions FROM portal;
