-- Run as the guacamole role after the stock schema is loaded. Idempotent.
-- 1) The stock schema ships guacadmin/guacadmin. Overwrite the password with random bytes and
--    disable it so the account cannot log in (all logins go through SAML).
UPDATE guacamole_user
   SET password_hash = decode(md5(random()::text) || md5(random()::text), 'hex'),
       password_salt = decode(md5(random()::text) || md5(random()::text), 'hex'),
       password_date = now(),
       disabled      = true
 WHERE entity_id = (SELECT entity_id FROM guacamole_entity WHERE name = 'guacadmin' AND type = 'USER');

-- 2) Bootstrap admin whose username equals the SAML NameID (email) of the first operator.
--    Has an unusable password; only SAML can authenticate it.
INSERT INTO guacamole_entity (name, type)
SELECT :'admin_user', 'USER'
 WHERE NOT EXISTS (SELECT 1 FROM guacamole_entity WHERE name = :'admin_user' AND type = 'USER');

INSERT INTO guacamole_user (entity_id, password_hash, password_salt, password_date)
SELECT e.entity_id,
       decode(md5(random()::text) || md5(random()::text), 'hex'),
       decode(md5(random()::text) || md5(random()::text), 'hex'),
       now()
  FROM guacamole_entity e
 WHERE e.name = :'admin_user' AND e.type = 'USER'
   AND NOT EXISTS (SELECT 1 FROM guacamole_user u WHERE u.entity_id = e.entity_id);

INSERT INTO guacamole_system_permission (entity_id, permission)
SELECT e.entity_id, p.permission::guacamole_system_permission_type
  FROM guacamole_entity e,
       (VALUES ('CREATE_CONNECTION'), ('CREATE_USER'), ('ADMINISTER')) AS p(permission)
 WHERE e.name = :'admin_user' AND e.type = 'USER'
   AND NOT EXISTS (SELECT 1 FROM guacamole_system_permission sp
                    WHERE sp.entity_id = e.entity_id
                      AND sp.permission = p.permission::guacamole_system_permission_type);
