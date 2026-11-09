# Credential rotation runbook (SEC-1 / SEC-2)

Status: **prepared, not executed.** No credential has been rotated. Every step that changes a credential, a
database record or a container needs explicit approval first.

Working-tree clean-up done (SEC-1, SEC-2; 2026-11-03, uncommitted):

- No credential value remains in tracked or untracked repository files outside the git-ignored `.env`:
  - the realm generator and `realm-cortex.json`, the compose files and `.env.example`;
  - `README.md` and the docs, the scripts and the tests.
- The dev realm carries Keycloak `${VAR}` placeholders, which Keycloak resolves from its environment at import:
  - `SMOKE_USER_PASSWORD` for every dev user;
  - `API_CLIENT_SECRET`, `WORKER_CLIENT_SECRET` and `INGESTION_CLIENT_SECRET` for the clients.

  Every compose file that imports the realm requires them with `:?`.
- The base compose has no secret default left. MinIO, Vault, Grafana, the worker secret, PostgreSQL and the Keycloak
  admin are all `:?`. CI generates every one of them per run.
- `.gitleaks.toml` no longer allow-lists the realm, the smoke script or the E2E helpers.
- `tests/unit/test_realm_secrets.py` and `test_mysql_compose_security.py` keep this from regressing. Each one
  compares the live `.env` values against docs, config, scripts and tests, and reports variable names only.

This does **not** un-publish anything. Every value below is still in the public git history and must be rotated.

Why: the GitHub repository is public and its history contains development credentials. Removing them from the
working tree does not un-publish them, so every exposed credential must be treated as known to anyone and replaced.

Rules for whoever runs this:

- Never paste a value into a terminal command line, a log, a ticket or chat. Generate values into the git-ignored
  `.env` (or a password manager) and pass them by variable or stdin.
- Change one credential family at a time. Verify it before starting the next.
- Keep the old value available, offline, until the family's verification has passed. That is the rollback.
- Do not rewrite git history as part of this runbook. History clean-up is a separate decision, and it does not help
  until rotation is done.

## 1. What is exposed

All values are identified by name only.

The working tree is clean for every row (SEC-1/SEC-2), so "exposed" now means the public git history. The running
services still hold the old values.

| Credential (`.env` variable) | Exposure now | Live consumers (verified by name search, 2026-11-03) |
|---|---|---|
| Keycloak admin password (`KEYCLOAK_ADMIN_PASSWORD`) | git history; the same value is live in `.env` | `capital-cortex-keycloak-demo` (`KC_BOOTSTRAP_ADMIN_PASSWORD`, first start only), `cortex/l8_actuation/keycloak_admin.py`, `scripts/bootstrap_admin.py`, `tests/unit/test_mysql_keycloak.py`; CI per-run |
| Client secret `cortex-worker` (`WORKER_CLIENT_SECRET`) | git history; live in `.env` and in the running Keycloak | worker (`docker-compose.yml`, `docker-compose.mysql-private.yml`, demo launcher), every Keycloak realm import, `scripts/smoke.py`, `tests/unit/test_mysql_keycloak.py`; CI per-run |
| Client secret `cortex-api` (`API_CLIENT_SECRET`) | git history; live in the running Keycloak; **not yet in `.env`** | realm import only. No runtime consumer was found; the API validates tokens through JWKS. Confirm before rotating. |
| Client secret `cortex-ingestion` (`INGESTION_CLIENT_SECRET`) | git history; live in the running Keycloak; **not yet in `.env`** | realm import only. No runtime consumer was found. Confirm before rotating. |
| Demo user password (`SMOKE_USER_PASSWORD`, every dev user) | git history; live in the running Keycloak; **not yet in `.env`** | humans using the demo; realm import; `scripts/smoke.py`, `contract_live.py`, `demo_phase2.py`, `demo_phase3.py`, `load_test.py`, `benchmark_mysql_app_paths.py`, `apps/web/e2e`, `tests/unit/test_mysql_keycloak.py` |
| TOTP seed for `smoke-auditor` (`SMOKE_TOTP_SECRET`) | git history; live in the running Keycloak; **not yet in `.env`** | `scripts/smoke.py`, `apps/web/e2e`, `tests/unit/test_mysql_keycloak.py`; `generate_realm.py` at generation time |
| PostgreSQL password (`POSTGRES_PASSWORD`) | git history; live in `.env` | `infra/docker-compose.yml` postgres and its clients, `scripts/migrate_pg_to_mysql.py`, `rehearse_data_migration.py`, `restore_drill.py`, `ops_common.py`. No Capital Cortex PostgreSQL container was running at inventory time. |
| MySQL application password (`MYSQL_TEST_PASSWORD` / `MYSQL_PASSWORD`) | **not in git history**, but it was printed in an earlier session's terminal output | `capital-cortex-mysql-test` (`MYSQL_PASSWORD`), `capital-cortex-keycloak-demo` (`KC_DB_PASSWORD`, set at container creation), demo launcher, `platform_core/db/session.py`, the MySQL scripts, `tests/conftest.py` |
| MySQL root password (`MYSQL_TEST_ROOT_PASSWORD` / `MYSQL_ROOT_PASSWORD`) | **not in git history**; printed as above | `capital-cortex-mysql-test` healthcheck (`MYSQL_PWD`, container env set at creation), demo launcher, `scripts/backup_mysql.py`, `infra/mysql/init/01-keycloak.sh` (now `MYSQL_PWD`), `make.ps1` |
| MinIO root password (`MINIO_ROOT_PASSWORD`) | git history (the old compose default); live in `.env` | every base-compose app service (`OBJECT_STORE_SECRET_KEY`), `minio`, `minio-init`, `wal-shipper`, `scripts/ops_common.py` (backup, restore drill) |
| Vault dev root token (`VAULT_DEV_ROOT_TOKEN`) | git history (the old compose default); live in `.env` | base-compose `vault` (dev mode, in-memory) and every app service (`VAULT_TOKEN`) |
| Grafana admin password (`GRAFANA_ADMIN_PASSWORD`) | git history (the old compose default); live in `.env` | base-compose `grafana`, `docker-compose.mysql-private.yml`, `scripts/smoke.py` (Tempo/Grafana check) |

## 2. Preconditions

1. Docker Desktop running; `capital-cortex-mysql-test` and `capital-cortex-keycloak-demo` healthy.
2. A copy of the current `.env` stored outside the repository and outside any synced folder, for rollback.
3. Done (SEC-2, uncommitted): the generator, realm, docs, `.env.example` and compose carry no value, so a rotated
   value is never written back into a committed file. Commit that work before rotating, so that `make realm` or a
   compose change can't re-introduce a value.
4. **`.env` completed (approval needed: it is a `.env` change).** Compose now refuses to start, for the base stack,
   the MySQL test stack and the MySQL demo stack, until these are set:
   - `SMOKE_USER_PASSWORD`, `API_CLIENT_SECRET` and `INGESTION_CLIENT_SECRET`. These are missing today, so the demo
     launcher's `compose up` stops with "required variable SMOKE_USER_PASSWORD is missing".
   - `SMOKE_TOTP_SECRET`, for smoke, E2E and the MFA login test.

   Until rotation, set them to the values the running Keycloak holds, so that `.env` describes reality. The realm
   is not re-imported, because it already exists.
5. Adding the four variables changes the Keycloak services' configuration, so the next
   `docker compose up` (the demo launcher) **recreates `capital-cortex-keycloak-demo`**. Its data is in MySQL and
   nothing is re-imported, but it is a recreate and needs approval.

## 3. Safe rotation sequence

The order is chosen so that no service ever holds a credential its counterpart has already dropped. Each step lists
its effect on dependents.

### Step 1: MySQL application account (`cortex`). Zero-downtime with MySQL dual passwords.

1. As root, for each host row of the account (`SELECT host FROM mysql.user WHERE user='cortex'`):
   `ALTER USER 'cortex'@'<host>' IDENTIFIED BY <new> RETAIN CURRENT PASSWORD;` (MySQL 8.0.14+, server is 8.4.13).
   Old and new passwords both work from this point.
2. Update `MYSQL_TEST_PASSWORD` (and `MYSQL_PASSWORD` where used) in `.env`.
3. Recreate `capital-cortex-keycloak-demo` so it picks up the new `KC_DB_PASSWORD`. **This is a container recreate;
   approval needed.** The Keycloak data lives in MySQL, so nothing is lost, and the realm is not re-imported because
   it already exists.
4. Restart the demo API and worker through `CORTEX_MYSQL_DEMO_START.ps1`.
5. Verify: `pytest tests/unit/test_mysql_keycloak.py` (schema and persistence tests), API `/readyz`, worker log
   free of authentication errors.
6. As root: `ALTER USER 'cortex'@'%' DISCARD OLD PASSWORD;`
7. Rollback before 6: put the old value back in `.env` and recreate again. Both passwords still work.

Dependents check: Keycloak, API, worker, scripts and tests all read the same `.env` variable. The dual-password
window covers the gap between changing the account and restarting each consumer.

### Step 2: MySQL root

1. As root: `ALTER USER 'root'@'%' IDENTIFIED BY <new> RETAIN CURRENT PASSWORD;` (repeat for `'root'@'localhost'`).
2. Update `MYSQL_TEST_ROOT_PASSWORD` / `MYSQL_ROOT_PASSWORD` in `.env`.
3. The `capital-cortex-mysql-test` healthcheck reads `MYSQL_ROOT_PASSWORD` from the env baked in at container
   creation. It keeps passing while the old password is retained. Before discarding the old password, the container
   must be recreated with the new env (**approval needed**; the data volume is kept, and `MYSQL_ROOT_PASSWORD` is
   ignored on an initialised data directory, so the recreate does not reset anything).
4. Verify: healthcheck healthy; `scripts/backup_mysql.py --help`-level connectivity check; drift check
   `scripts/check_mysql_schema_drift.py`.
5. `ALTER USER 'root'@… DISCARD OLD PASSWORD;`

Do **not** discard the old root password before the recreate: the container would go unhealthy, and dependents
would be stopped or restarted by compose.

Separate item: the older `capital-cortex-mysql` container (project `capital-cortex-stacktest`) was created before the
compose fix. It still runs `mysqladmin ping -u root -p…`, so its root password is visible in that container's
process list on every healthcheck. Both the compose file (`infra/docker-compose.mysql.yml`) and the init script
(`infra/mysql/init/01-keycloak.sh`) now use `MYSQL_PWD`, and `tests/unit/test_realm_secrets.py` guards them. The
running container only picks this up when it is recreated. That needs approval; alternatively, retire the
container, which is already on the "pause before" list. Rotate its root password at the same time.

### Step 3: Keycloak admin

1. In the Keycloak admin console (or `kcadm.sh set-password` reading the value from stdin), change the password of
   the master-realm admin user. Changing `KC_BOOTSTRAP_ADMIN_PASSWORD` alone does **not** change an existing admin.
2. Update `KEYCLOAK_ADMIN_PASSWORD` in `.env`.
3. Restart the API and worker only if `cortex/l8_actuation/keycloak_admin.py` is in use. It reads the setting at
   start.
4. Verify: `tests/unit/test_mysql_keycloak.py::test_keycloak_admin_api_operations`.
5. Better still: create a dedicated service-account client for `keycloak_admin.py`, so the human admin password is
   never shared with code. That is an architecture decision, and needs approval.

### Step 4: Keycloak client secrets

For each client (do `cortex-worker` first; it is the only one with a confirmed consumer):

1. Admin console → Clients → *client* → Credentials → *Regenerate*. The old secret stops working immediately.
   (Alternatively, set a chosen value with the Admin REST API, so that `.env` is written first.)
2. At once, update the client's variable in `.env` (`WORKER_CLIENT_SECRET`, `API_CLIENT_SECRET` or
   `INGESTION_CLIENT_SECRET`, which also feed the realm import of any fresh stack) and restart the worker through
   the launcher.
3. Verify: worker obtains a token (worker log), and `scripts/smoke.py` passes the bus round-trip.
4. `cortex-api` and `cortex-ingestion`: first confirm there is no consumer (search deployment configs outside this
   repository too). Then regenerate the same way.

Expected break: the worker cannot authenticate during the seconds between regeneration and restart. Jobs retry. Run
this outside a demo session.

### Step 5: Demo user password

1. Set a new `SMOKE_USER_PASSWORD` in `.env`. It is the single source: realm import, smoke, E2E and the demo
   scripts all read it. It must meet the realm policy (12+ characters, an upper-case letter, a digit and a special
   character) and contain no double quote or backslash.
2. Reset each dev user's password through the Admin REST API (`PUT /admin/realms/cortex/users/{id}/reset-password`,
   temporary=false), or with a `partialImport` as in step 6.
3. Tell everyone who uses the demo accounts, through a private channel.
4. Verify: `test_keycloak_human_user_auth_code_pkce_token`, then smoke and E2E.

### Step 6: `smoke-auditor` TOTP seed

The running Keycloak still holds the committed seed (realm import only happens on first start).

1. Generate a new seed (`python -c "import secrets; print(secrets.token_hex(20))"` redirected into `.env` as
   `SMOKE_TOTP_SECRET`, not printed).
2. Either:
   - (a) remove the user's OTP credential (Admin console → Users → smoke-auditor → Credentials → Delete OTP) and
     re-create it with a realm `partialImport` (`ifResourceExists: OVERWRITE`) of the `smoke-auditor` user generated
     by `generate_realm.py` with the new seed. The import also sets that user's password from
     `SMOKE_USER_PASSWORD`, so do it after step 5; or
   - (b) delete the OTP credential and set the `CONFIGURE_TOTP` required action, then enrol with the new seed.

   Both change Keycloak database records, so both need approval.
3. Verify: `test_keycloak_mfa_user_totp_token`, and smoke with the MFA marker on (D-033 toggle; also a database
   change, needs approval).

### Step 7: PostgreSQL

**Owner.** The blocker register assigns SEC-1/2 to Developer / Security and production PostgreSQL to DevOps. It names no
individual. Record a named owner for each row below before starting. Nobody rotates a row without that owner's approval.

| Environment | Details | Status (2026-11-09) | Action |
|---|---|---|---|
| This machine's `.env` | `POSTGRES_PASSWORD` | Matches the public value | Replace, after the servers that use it |
| Base-stack PostgreSQL | Role `cortex`, databases `cortex` and `keycloak`; volumes `capital-cortex_pgdata`, `capital-cortex_pgwal` | No container | Rotate or retire |
| Load stack | `postgres-load`, database `cortex_load` | Not running | Rotate if ever started |
| `cortex-pg-realdata` | Stopped; 127.0.0.1:55434; volume `capital-cortex-rehearsal_pgcopy` | Environment does not hold the public value; may hold real data | Owner decides; do not start without approval |
| `cortex-pg-rehearsal` | Stopped; database `cortex_disposable`; port 55433 on all interfaces when running | Environment does not hold the public value | Retire, or rotate before any start |
| Other developers' machines | Any clone of `f2c447a`, `feat/capital-outreach` or `feat/cortex_1.0` | Unknown; these fall back to the public value when unset | Each developer checks |
| Staging, production | No host in this repository | Unknown | DevOps confirms |
| Backups | The role password can return with a restore | Unknown | DevOps confirms |

For each row, in order:

1. Confirm the named owner's approval, and that the server may be started if it is stopped.
2. Keep the old value offline, outside the repository and any synced folder, for rollback.
3. Generate the new value straight into a password manager or the git-ignored `.env`, never on a command line:
   `python -c "import secrets; print(secrets.token_urlsafe(32))"`, redirected, not displayed.
4. On that server, run `\password cortex` in psql, so the value does not reach the server log.
5. Update every client in that environment: `POSTGRES_PASSWORD`, `MIGRATION_PG_PASSWORD`, and the base-stack Keycloak,
   whose `KC_DB_PASSWORD` falls back to `POSTGRES_PASSWORD`. Recreating a container needs approval.
6. Verify the new value: `scripts/ops_common.py`-based tools connect, and `scripts/rehearse_data_migration.py` passes in
   dry-run mode.
7. Verify the old value is refused: a login with it must fail with SQLSTATE `28P01`. Report only accepted or refused.
8. Return the server to its previous state. Record the environment, date, owner and both results, never a value.

Changing `.env` alone rotates nothing, and removing the value from Git does not un-publish it. CI is not affected: it
generates a fresh `POSTGRES_PASSWORD` per run. A rollback to release `f2c447a` must always set `POSTGRES_PASSWORD`
explicitly, because that release falls back to the public value. Destroy the offline old values only after every row
is verified.

## 4. CI after SEC-1

The `build-scan-smoke` job generates, per run and masked with `::add-mask::`, every credential the stack needs:
- the TOTP seed and the dev-user password;
- the three client secrets;
- the PostgreSQL, Keycloak-admin, MinIO, Vault and Grafana secrets.

It builds the realm with that seed, and Keycloak resolves the realm placeholders from the same variables. No
repository secret is needed, and none of the rotated values are used by CI.

## 5. Step 8: MinIO, Vault, Grafana (after step 7)

Their old compose defaults are public, and `.env` still holds the same values.
- **MinIO:** change `MINIO_ROOT_PASSWORD` in `.env`, then recreate `minio` and the services that read it
  (`minio-init`, `wal-shipper`, api, worker). This needs approval. Existing buckets and objects are kept.
- **Vault:** dev mode is in-memory and has no persistent data, so a new `VAULT_DEV_ROOT_TOKEN` plus a recreate of
  `vault` and the app services is enough.
- **Grafana:** change the admin password in Grafana (`grafana cli admin reset-admin-password`, value from stdin or
  the environment) and in `.env`. `GF_SECURITY_ADMIN_PASSWORD` only applies on first start.

Check with `scripts/backup.py` (MinIO), `/readyz` and the smoke Tempo check (Grafana).

## 6. Done when

- Every row in section 1 has a new value, verified by its listed test or check.
- `secret_scan`-style exact-value search finds none of the new values in the working tree or history.
- Old values are destroyed from the offline rollback store after one successful demo cycle.
