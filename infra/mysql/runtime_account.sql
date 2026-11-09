-- Capital Cortex: DML-only runtime account for the API and worker (SECURITY-DB-1). NOT APPLIED: needs approval.
--
-- Why: today the API, the worker and the migrations share `cortex`, which holds ALL PRIVILEGES on `cortex`.* (see
-- least_privilege.sql). A compromised API process could DROP the audit_log triggers (trg_audit_no_update /
-- trg_audit_no_delete), TRUNCATE audit_log (MySQL triggers do not fire on TRUNCATE) or alter the schema.
-- Target: `cortex` stays the schema owner used only by `migrate`; `cortex_app` gets data access only, and on
-- audit_log only SELECT + INSERT, so the chain is append-only for the application even without the triggers.
--
-- MySQL cannot subtract a table privilege from a database-level grant, so data privileges are granted per table.
-- Re-run step 3 after every migration that adds a table (the drift check lists new tables).
--
-- Run as root with the mysql client (the password is read from a prompt, never typed into the command line):
--   mysql -h 127.0.0.1 -P 53306 -u root -p
--
-- 1. Account (enter the new password at the client; store it in the secret store as MYSQL_APP_PASSWORD):
--      CREATE USER IF NOT EXISTS 'cortex_app'@'%' IDENTIFIED BY '<from the secret store>';
--    For production also: ALTER USER 'cortex_app'@'%' REQUIRE SSL;

-- 2. Database-level privileges that cannot be granted per table. LOCK TABLES lets the audit append's
--    `SELECT ... FOR UPDATE` serialise writers without UPDATE on audit_log.
GRANT LOCK TABLES, EXECUTE, CREATE TEMPORARY TABLES ON `cortex`.* TO 'cortex_app'@'%';

-- 3. Generate the per-table grants, review the output, then run it:
SELECT CONCAT(
         'GRANT SELECT, INSERT',
         IF(table_name = 'audit_log', '', ', UPDATE, DELETE'),
         ' ON `cortex`.`', table_name, '` TO ''cortex_app''@''%'';'
       ) AS grant_statement
  FROM information_schema.tables
 WHERE table_schema = 'cortex' AND table_type = 'BASE TABLE'
 ORDER BY table_name;

-- 4. Verify (expect no DROP, ALTER, CREATE, INDEX, TRIGGER, REFERENCES; audit_log: SELECT, INSERT only):
SHOW GRANTS FOR 'cortex_app'@'%';

-- 5. Switch the runtime (approval; recreates api/worker): DATABASE_URL for api and worker uses cortex_app; migrate
--    keeps cortex. Rollback: point DATABASE_URL back at cortex and recreate api/worker; then
--      DROP USER 'cortex_app'@'%';
--    Nothing in this script changes data or the existing `cortex` account.
