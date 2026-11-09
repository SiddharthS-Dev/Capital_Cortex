-- Least privilege for the application account `cortex` (MySQL 8.4). Run as root; idempotent; changes no data.
--
--   docker exec -i capital-cortex-mysql-test sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot' < infra/mysql/least_privilege.sql
--
-- Why the account had server-wide privileges: binary logging is on, and without log_bin_trust_function_creators=1
-- MySQL lets only SUPER create triggers, which the schema (4 triggers) and its migrations need. The server now runs
-- with --log-bin-trust-function-creators=1 (infra/docker-compose.mysql*.yml), so schema-level TRIGGER is enough.
--
-- After this script `cortex` holds no global privilege (no SUPER, CREATE USER, SYSTEM_USER, PROCESS, FILE, RELOAD,
-- SHUTDOWN, ...). It keeps ALL on its own schemas: `cortex`, `keycloak` (Keycloak's tables) and `cortex\_%`, which
-- covers cortex_demo, cortex_integration and the benchmark / rehearsal / restore-drill copies, and lets the
-- integration suite create cortex_integration on a fresh server.
-- Production accounts are provisioned by DevOps with the same shape (schema-level only); never run this there blindly.

-- Global level only (static and dynamic privileges); the schema-level grants below are kept/re-granted.
REVOKE ALL PRIVILEGES ON *.* FROM 'cortex'@'%';

GRANT ALL PRIVILEGES ON `cortex`.* TO 'cortex'@'%';
GRANT ALL PRIVILEGES ON `keycloak`.* TO 'cortex'@'%';
GRANT ALL PRIVILEGES ON `cortex\_%`.* TO 'cortex'@'%';

SHOW GRANTS FOR 'cortex'@'%';
