# Capital Cortex — MySQL Migration Blocker Resolution Report

> **Historical record (dated 2026-11-03).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


*2026-11-03.*
- **Branch:** `feature/changes-login`; HEAD `f2c447a` unchanged. No commit, stash, reset, clean or push.
- **Environment:** every action was local, on the test server `capital-cortex-mysql-test` (MySQL 8.4.13). No production system was contacted.
- **Secrets:** this report contains no passwords, tokens, TOTP seeds, client secrets or connection strings.
- **Baseline used:** the investigation findings. `CORTEX_MYSQL_REMAINING_BLOCKERS_REPORT.md` was never saved.

## Totals

| | Count | Items |
|---|---|---|
| **Fixed and verified locally** | **4** | DATA-2, SEC-3, SEC-4, OPS-2 |
| **Fixed, verification pending** | **1** | CI-1: the drift gate is in the workflow and its steps pass locally; it hasn't run on GitHub (nothing is pushed) |
| **Needs your approval** | **5** | DATA-1, OPS-1, TEST-1, SEC-1/SEC-2 (rotation), GIT-1 |
| **Needs DevOps/DBA** | **4** | B1, B2, INFRA-1, ENV-1 |
| **Needs the Project Lead** | **6** | B3, PERF-1, ARCH-1, ARCH-2, ARCH-3, ARCH-4 |

**Tests, compared with the baseline:**

| Suite | Baseline | Now |
|---|---|---|
| Unit (`MYSQL_TEST_DATABASE=cortex_unit`) | 383 passed / 0 failed | **398 passed / 0 failed** (+15 new: 4 verify-script, 9 drift-checker, 2 secret/ETL) |
| Integration (8 files, all exit 0) | 21 / 0 / 3 skipped | **21 passed / 0 failed / 3 skipped** (the same PostgreSQL-only skips) |
| Demo smoke | 10/10 | **10/10** (MFA enforced for the run, then switched back off) |
| Runtime verification on `cortex_unit` | Failed on head (`screening`) | **Passes, and cleans up its 6 rows** |
| Schema drift | — | 6 databases OK at m0004; `cortex` still drifts on 1 column (DATA-1, by design) |
| CI-equivalent (`mysql-schema` steps) | — | Build ×2 from empty: exit 0; re-run: exit 0; drift: exit 0 |

**Not production-ready.** The migration is not 100% complete while B1, B2, INFRA-1 and B3 remain open.

## 1. Fixed

### DATA-2: runtime verification wrote an invalid stage and never cleaned up (FIXED AND VERIFIED)
- **Root cause:** `scripts/verify_mysql_runtime.py` wrote `pipeline_stage='screening'`, which isn't in the baseline vocabulary. It also left 6 rows per run (opportunity, organisation, 2 entities, an edge, an embedding), and its import rewrote `DATABASE_URL` and `REDIS_URL`.
- **Fix:**
  - The stage is now `VERIFY_STAGE = "qualified"`, which a test checks against `schema_mysql.sql`.
  - Each ID is recorded **before** its insert. A `finally` block calls `cleanup_verification_records()`, which deletes **only those primary keys**, child tables first; it never filters on title, provenance or flags.
  - The audit record is kept, because `audit_log` is append-only.
  - Environment setup moved into `configure()`, which runs only under `__main__`.
- **Files:** `scripts/verify_mysql_runtime.py`; new `tests/unit/test_verify_mysql_runtime.py`.
- **Tests:** 4/4.
  - The stage is in the vocabulary.
  - Importing the script doesn't change the process environment.
  - Cleanup leaves an unrelated look-alike row (same title, provenance and demo flag) untouched.
  - A full run as a subprocess passes, with all 6 created IDs gone afterwards and the look-alike row kept.
- **Before / after:** before, it failed on a head-revision database, and on the drifted `cortex` it left `screening` rows; that's how the 6 DATA-1 rows came to exist. After, it reports "ALL RUNTIME VERIFICATION CHECKS PASSED" and removes `{'relationship_edge': 1, 'embedding': 1, 'entity': 2, 'opportunity': 1, 'organization': 1}`.
- **Remaining risk:** each run still adds 1 audit record, by design. **Owner:** Developer.

### SEC-3: MySQL test password in untracked reports (FIXED AND VERIFIED)
- **Fix:** 6 occurrences replaced with `[REDACTED]`:
  - `CORTEX_MYSQL_GIT_REVIEW_REPORT.md` (1);
  - `CORTEX_MYSQL_PHASE2_EXECUTION_REPORT.md` (3);
  - `CORTEX_MYSQL_PHASE3_EXECUTION_REPORT.md` (1);
  - `CORTEX_MYSQL_PHASE8_EXECUTION_REPORT.md` (1).

  All four files are untracked. No other text changed.
- **Evidence:** a rescan of every `.md` finds 0 remaining copies of the MySQL test, root or rehearsal values.
- **Owner:** Developer.

### SEC-4: PostgreSQL and Keycloak dev fallbacks (FIXED AND VERIFIED)

| Site | Kind | Fix |
|---|---|---|
| `infra/docker-compose.yml` (8 lines) | Runtime fallback (PostgreSQL rollback stack) | `${POSTGRES_PASSWORD:?…}` and `${KEYCLOAK_ADMIN_PASSWORD:?…}`; `KC_DB_PASSWORD` still falls back to the now-required `POSTGRES_PASSWORD` |
| `scripts/ops_common.py` | Runtime fallback | Empty default; `pg_connect()` stops with a clear message if `POSTGRES_PASSWORD` is unset |
| `scripts/bootstrap_admin.py` | Runtime fallback | `_required(env, "KEYCLOAK_ADMIN_PASSWORD")` |
| `scripts/migrate_pg_to_mysql.py` | PostgreSQL loopback default | `local_default=None`: the source password must come from the environment or a file |
| `.env.example` (2 lines) | Template holding real dev values | Empty placeholders |
| `CORTEX_MYSQL_PHASE8_EXECUTION_REPORT.md`, `postgresql_dependency_scan.csv` | Historical evidence | Value replaced with `[REDACTED]` |
| `tests/unit/test_mysql_keycloak.py` | Test fixture | Reads `KEYCLOAK_ADMIN(_PASSWORD)` from `.env` through `tests/conftest.py` |
| `tests/unit/test_mysql_session.py` | Sample URL | Placeholder |
| `tests/unit/test_mysql_compose_security.py` | Regression guard | Kept: it asserts the value is **absent** |

- **Not changed:** the PostgreSQL rollback functionality. The PostgreSQL stack's compose config renders with `.env` (`config -q` OK), because `.env` sets every required value.
- **Tests:**
  - 61 affected tests pass: secure-connect, compose security, session, Keycloak, ETL.
  - New: `test_postgres_rollback_stack_requires_its_database_and_keycloak_secrets` and `test_etl_refuses_postgres_source_without_a_configured_password_even_on_loopback`.
- **Scan:** both literals appear only in the absence-guard test.
- **Remaining risk:** the values are still in **public git history**; see SEC-1.
- **Owner:** Developer.

### OPS-2: stack-test definition depended on a scratchpad file (FIXED AND VERIFIED)
- **Fix:** new `infra/docker-compose.mysql-stacktest.yml`, a committed copy of the temporary override:
  - the stack-test image tags;
  - Keycloak pointed at `keycloak_fresh`;
  - same project name, so the same volume `capital-cortex-stacktest_mysqldata`;
  - no secrets.
- **Evidence:** rendered with a placeholder env file: MySQL ports `127.0.0.1:13306` (loopback, previously all interfaces), volume `mysqldata`, Keycloak database `keycloak_fresh`. Nothing was started or changed.
- **Owner:** Developer.

### CI-1: drift check in CI (FIXED, VERIFICATION PENDING)
- **Fix:** a new `mysql-schema` job in `.github/workflows/ci.yml`:
  - a throwaway `mysql:8.4` service container, whose password is derived from the run ID; no repository secret and no production access;
  - builds the schema twice from empty with `alembic -n mysql upgrade head`;
  - re-runs it to prove it's a no-op;
  - runs `check_mysql_schema_drift.py`, which exits non-zero on any drift;
  - runs the drift and m0004 tests.
- **New test:** `tests/unit/test_check_mysql_schema_drift.py`, 9/9. Identical databases give exit 0. Each of 8 drifts gives exit 1: extra, missing and changed column, dropped FK, dropped CHECK, extra index, revision, stray table.
- **Local equivalent:** YAML valid; build ×2 exit 0; re-run exit 0; drift exit 0.
- **Pending:** a real GitHub run, after GIT-1.
- **Owner:** Developer.

## 2. Needs your approval (nothing below has been executed)

### DATA-1: six legacy `screening` rows in `cortex`
- **Records:** `2e176a27-9191-4df2-8634-c621d6fd9747`, `417c7e27-ec12-4147-8005-3a7e4e2f87ea`, `aafca61b-044b-47e2-bd64-d5ca2e0d1163`, `c2f3bf8f-d0f2-46f9-b2af-d3fd75cf480c`, `47f6340b-c090-4c57-a12e-ba845d268cff`, `3dc2f4ef-68bd-4045-ada2-51203bfb7528`.
- **Content:**
  - all `grant`, status `active`, `is_demo=1`, score 0.88;
  - created 2026-10-29/30, provenance `{"origin":"runtime_verification"}`.
- **Linked by ID (not foreign keys):**
  - 6 counterparty organisations, each used only by its own row;
  - 6 opportunity entities plus organisation entities;
  - 6 edges;
  - 4 embeddings;
  - 3 audit records (append-only).
- **No dependents** in recommendations, factor history, interactions, outcomes or proposals.

**Step 0, for either option:** take an encrypted backup of `cortex`: `python scripts/backup_mysql.py backup --databases cortex --dest <dir>`, with `MYSQL_BACKUP_ENCRYPTION_KEY_FILE` set.

**Option A, recommended: map to `qualified`.** It touches 6 values, and nothing else changes.
```sql
SELECT id, pipeline_stage, is_demo, JSON_UNQUOTE(JSON_EXTRACT(source_ref,'$.origin')) AS origin
  FROM cortex.opportunity WHERE pipeline_stage = 'screening';                       -- before: expect 6 rows
START TRANSACTION;
UPDATE cortex.opportunity SET pipeline_stage = 'qualified'
 WHERE id IN ('2e176a27-9191-4df2-8634-c621d6fd9747','417c7e27-ec12-4147-8005-3a7e4e2f87ea',
              'aafca61b-044b-47e2-bd64-d5ca2e0d1163','c2f3bf8f-d0f2-46f9-b2af-d3fd75cf480c',
              '47f6340b-c090-4c57-a12e-ba845d268cff','3dc2f4ef-68bd-4045-ada2-51203bfb7528')
   AND pipeline_stage = 'screening' AND is_demo = 1
   AND JSON_UNQUOTE(JSON_EXTRACT(source_ref,'$.origin')) = 'runtime_verification';
SELECT ROW_COUNT();                       -- must be 6; otherwise ROLLBACK
COMMIT;
```
Then:
1. Run `alembic -n mysql upgrade head` on `cortex`; m0004 converts the ENUM.
2. Run `scripts/check_mysql_schema_drift.py --reference cortex_unit --targets cortex`, which should report OK.

- **Rollback:** before the ENUM conversion, run the same UPDATE in reverse. After it, restore the step-0 backup into a new database.

**Option B: archive the whole verification bundle** in a separate database (an archive table inside `cortex` would itself count as drift).
```sql
CREATE DATABASE cortex_archive_20261103 CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE TABLE cortex_archive_20261103.opportunity  AS SELECT * FROM cortex.opportunity  WHERE id IN (<6 ids above>);
CREATE TABLE cortex_archive_20261103.organization AS SELECT * FROM cortex.organization
  WHERE id IN (SELECT counterparty_id FROM cortex_archive_20261103.opportunity);
CREATE TABLE cortex_archive_20261103.entity AS SELECT * FROM cortex.entity
  WHERE (ref_table = 'opportunity'  AND ref_id IN (SELECT id FROM cortex_archive_20261103.opportunity))
     OR (ref_table = 'organization' AND ref_id IN (SELECT id FROM cortex_archive_20261103.organization));
CREATE TABLE cortex_archive_20261103.relationship_edge AS SELECT * FROM cortex.relationship_edge
  WHERE from_entity IN (SELECT id FROM cortex_archive_20261103.entity) OR to_entity IN (SELECT id FROM cortex_archive_20261103.entity);
CREATE TABLE cortex_archive_20261103.embedding AS SELECT * FROM cortex.embedding
  WHERE entity_id IN (SELECT id FROM cortex_archive_20261103.opportunity);
-- verify archive counts (expected 6 / 6 / entities / 6 / 4) before deleting
START TRANSACTION;
DELETE FROM cortex.relationship_edge WHERE id IN (SELECT id FROM cortex_archive_20261103.relationship_edge);
DELETE FROM cortex.embedding         WHERE id IN (SELECT id FROM cortex_archive_20261103.embedding);
DELETE FROM cortex.entity            WHERE id IN (SELECT id FROM cortex_archive_20261103.entity);
DELETE FROM cortex.opportunity       WHERE id IN (SELECT id FROM cortex_archive_20261103.opportunity);
DELETE FROM cortex.organization      WHERE id IN (SELECT id FROM cortex_archive_20261103.organization);
COMMIT;
```
Then the same upgrade and drift check as in Option A.

- **Rollback:** before the ENUM conversion, `INSERT … SELECT` back from the archive, parents first. After it, reinsert with the stage set to `qualified`, or restore the backup.
- **The audit records stay in both options;** they're append-only and only reference the IDs.

### OPS-1: stop the stale stack-test MySQL
- **Re-verified 2026-11-03:**
  - `restart=unless-stopped`; port `13306` on **all interfaces**;
  - **0** client sessions, and only listening sockets on the host;
  - the other 7 containers of its project exited; it's alone on its network.
- **Action:** `docker update --restart=no capital-cortex-mysql` then `docker stop capital-cortex-mysql`.
- **Impact:** none on any running application. The container and the volume `capital-cortex-stacktest_mysqldata` (with `cortex`, `keycloak`, `keycloak_fresh`, `keycloak_import_check`) are kept.
- **Rollback:** `docker start capital-cortex-mysql`, then `docker update --restart=unless-stopped capital-cortex-mysql`. Better, recreate it bound to loopback with `infra/docker-compose.mysql-stacktest.yml`.

### TEST-1: unit tests default to the drifted `cortex`
- **State:** `cortex_unit` exists at m0004, built by the least-privilege account, and the suite is 398/0 against it. The integration tests use their own `cortex_integration`.
- **Action:** in your `.env`, change `MYSQL_TEST_DATABASE=cortex` to `MYSQL_TEST_DATABASE=cortex_unit`.
- **Impact:**
  - `get_mysql_test_url()`, the unit tests and `verify_mysql_runtime.py` will default to `cortex_unit`;
  - the compose `MYSQL_DATABASE` value is only read when a **new** volume is initialised, so the existing server is unaffected;
  - the demo (`cortex_demo`) and integration tests (`cortex_integration`) are unaffected.
- **Rollback:** set it back to `cortex`.
- **Alternative:** do DATA-1, and `cortex` becomes usable again.

### SEC-1 / SEC-2: credential rotation
- **Exposure:** `github.com/SiddharthS-Dev/Capital_Cortex` is **public** (`private: false`). These are in its history:
  - the PostgreSQL dev password and the Keycloak dev admin password;
  - 3 Keycloak client secrets, the dev user password and the smoke-test TOTP seed (decision D-013).
- **Reuse:** the local `.env` reuses the Keycloak admin value, the MySQL app password and the MySQL root password (verified by hash comparison).
- **The MySQL values were never committed,** but they appeared in uncommitted code, reports and session output.

**Rotation runbook (on approval; no value is ever printed):**
1. **Generate** new values with `python -c "import secrets; print(secrets.token_urlsafe(32))"` and write them straight into `.env` with a small script; nothing goes to the screen.
2. **MySQL:** as root, `ALTER USER 'cortex'@'%' IDENTIFIED BY …`, then `ALTER USER 'root'@'%'` and `'root'@'localhost'`. Update `MYSQL_TEST_PASSWORD` and `MYSQL_TEST_ROOT_PASSWORD`.
3. **Recreate the dependents:**
   - `docker compose --env-file .env -f infra/docker-compose.mysql-demo.yml up -d keycloak-demo` (its database password changes);
   - the `mysql-test` healthcheck reads its own env, so recreate it with `… mysql-test.yml up -d mysql-test`; the volume is kept;
   - restart the demo API and worker with `CORTEX_MYSQL_DEMO_START.ps1`.
4. **Keycloak admin:** reset the master-realm admin password through the admin API, then update `KEYCLOAK_ADMIN_PASSWORD`. The bootstrap variables are only read on a first start.
5. **Realm hardening:**
   - regenerate the `cortex-api`, `cortex-worker` and `cortex-ingestion` secrets with `POST /clients/{id}/client-secret`, and update `WORKER_CLIENT_SECRET` and the others in `.env`;
   - reset or disable the dev users;
   - re-enrol `smoke-auditor`'s OTP.

   **Dependency:** `scripts/smoke.py` uses the committed TOTP seed, so it must first be changed to read the seed from the environment. That's a small code change, to make on approval.
6. **PostgreSQL:** run `ALTER ROLE cortex PASSWORD …` in the PostgreSQL rollback container when it's next started, and update `POSTGRES_PASSWORD`.
7. **Verify:** smoke 10/10; unit suite; `verify_mysql_runtime.py`; and confirm each **old** value is refused (MySQL 1045, Keycloak 401).
8. **Never commit** `.env`. Rewriting the public history needs separate approval; rotation is the priority.

### GIT-1: branch and commit plan (prepared, not executed)
- **State:** 183 entries now (177 before this round: +6 new untracked files). HEAD `f2c447a` is already on `origin/develop`.
- **Proposed:**
  1. `git switch -c feature/mysql-migration`. This carries the working tree and changes nothing.
  2. Commit in this order:
     1. schema and migrations: `scripts/schema_mysql.sql`, `migrations_mysql/`, `platform_core/db/{compat,mysql_schema,session,vector}.py`, `platform_core/audit/chain.py`, `platform_core/{jsonutil,signing,idempotency}.py`, `cortex/l4_reasoning/factors/builtin.py`;
     2. the 48 dual-path modules, plus `seed/`;
     3. infra and security: `infra/docker-compose*.yml`, `infra/mysql/`, `.env.example`, `.gitattributes`, `make.ps1`, `Makefile`, `alembic.ini`, `pyproject.toml`;
     4. tooling: the `scripts/*mysql*`, `secure_connect.py`, `backup_mysql.py`, `check_mysql_schema_drift.py`, `rehearse_data_migration.py`, `ops_common.py`, `bootstrap_admin.py`;
     5. tests and CI;
     6. redacted reports and the runbook.
  3. Funding work goes on `feature/live-funding-sources`.
  4. The login work (`infra/keycloak/generate_realm.py`, `realm-cortex.json`) stays on `feature/changes-login`.
- **Hunk split of the 4 mixed files** (`git add -p`):

| File | MySQL commit | Funding commit |
|---|---|---|
| `cortex/l1_perception/ingestion.py` | `uuid` import; MySQL branch of `_store_signal`; MySQL `source_run` insert; MySQL `reconcile_unprocessed` query | `time`/`accept` imports; `_put_raw` object-store fallback; `raw_storage`; `run_id` parameter and the PostgreSQL `COALESCE(:id)` insert; stale-run recovery; `rejected`/`rejections`; `timeout` |
| `cortex/l1_perception/registry.py` | `uuid` import; MySQL branch of `sync_sources` | `SourceConfig.timeout_seconds`, `SourceConfig.accept` |
| `cortex/l2_representation/entity_resolver.py` | All hunks, including `ORG_NAME_MAX` (a MySQL `VARCHAR(255)` fix) | None |
| `cortex/l8_actuation/api/routers/sources.py` | MySQL SQL in `list_sources`/`source_runs`; dialect `id_clause` in `patch_source` | `uuid` import; `run_now` (`run_id`, 409); `GET /sources/{id}/runs/{run_id}`; health-reset rule |

- **Exclude from every commit:**
  - `.env` (git-ignored);
  - `dd_out.txt`, `dd_err.txt`, `postgresql_dependency_scan.csv`, `postgresql_dependency_file_summary.csv`, `rehearsal_reconciliation_report.json`, `scripts/rehearsal_reconciliation_report.json`;
  - the root `package-lock.json`: an empty 93-byte stray from 2026-10-21 with no `package.json`. It doesn't belong to the frontend, whose lock file `apps/web/package-lock.json` is tracked and unchanged.
- **Before any push:** the repository is public, so re-run the secret scan (gitleaks in CI) and rotate first.

## 3. Needs DevOps/DBA (handoff requirements; none can be closed from local configuration)

| ID | Required evidence |
|---|---|
| **B1** (DevOps → DBA) | An authorised production PostgreSQL 16 dump and its checksums; a restore into an isolated PostgreSQL with AGE and pgvector; row counts and checksums matching the source; then the full rehearsal (ETL PASSED, 0 mismatches, 0 orphans, valid audit chain, Keycloak export/import, smoke) |
| **B2** (DevOps + Project Lead) | Production host, provider (D-011 is still open; Terraform is a stub), owner, network route, and read-only, TLS-verified credentials. Or approval of the dump-only path |
| **INFRA-1** (DevOps) | Production MySQL host and size (buffer pool at least the working set; benchmark data is 2.97 GB against a 512 MB test pool); private network (`docker-compose.mysql-private.yml`); off-host encrypted backups (`MYSQL_BACKUP_DEST`/`S3_ENDPOINT` are empty in `.env`); key custody; schedule; a rehearsed PITR (binlog retention 7 days and a binlog shipper exist); a MySQL exporter and alert routes (none exist); Keycloak `start` with HTTPS (every compose file uses `start-dev`); a production Vault or KMS (the current Vault is a dev-mode container) |
| **ENV-1** (you / DevOps) | Docker Desktop stopped 3 times and the session host restarted twice; this round needed two Docker restarts. Investigate host stability (memory, disk, updates) before demos |

## 4. Needs the Project Lead (decision documents; no decision taken here)

### PERF-1: list and search to 2 s
- **Measured on 2026-11-03** on `cortex_bench_1m` (200k opportunities, single user; warm medians, cold in brackets):
  - Facet counts over all rows: **1,133 ms** (2,338 cold), even with the covering index.
  - Total count: exact **303 ms**; capped at 1,001: **20 ms**.
  - Search, current shape (FULLTEXT **or** substring): **7,629 ms**. The substring part alone: 6,683 ms (32 s cold), with **0** matches for "energy storage".
  - FULLTEXT word/prefix only: **413 ms**, with the **same 20,000 results** for this query; first page of 50: **88 ms**.
  - Page query (deferred join plus m0003 indexes, already done): about 17 ms.
- **The latest end-to-end p95 (2026-11-02):** radar 18.7 s, recent 9.3 s, search 28.1 s. **The target is not met.**
- **No further optimisation that keeps behaviour identical remains.**
- **Decisions needed:**
  1. **Facets:** a cached summary table updated on write (milliseconds to read; small staleness and maintenance work) or facets loaded on demand.
  2. **Search:** FULLTEXT word/prefix only, losing substring matches inside words and on counterparty names; or keep substring matching on titles only; or add an n-gram FULLTEXT parser (more storage).
  3. **Totals:** exact, or capped ("1,000+").
  4. **Production buffer pool:** at least the working set, for example 4 GB or more for about 3 GB of data, or 60–70% of server RAM.

  End-to-end p95 must be re-measured after implementation; it isn't claimed here.

### ARCH-1: Keycloak database separation
- **Evidence:** login took 8 s and logout 6 s while the shared MySQL was under a 1M-row batch load (B20).
- **Options:**
  - **A:** a separate MySQL instance for Keycloak (isolated, one more server to run and back up).
  - **B:** shared, with batch windows (cheaper; needs scheduling discipline; risk stays at peaks).
  - **C:** shared, with resource limits.
- **Recommendation for discussion:** A for production; B is acceptable for the demo.

### ARCH-2: vector index capacity
- **Evidence:** 143 s cold build and about 2.7 GB per API process at 200k vectors, an exact in-memory index per tenant (B23).
- **Options:**
  - **A:** warm-up at start (no code risk; still the RAM cost per process).
  - **B:** a persisted approximate-nearest-neighbour index, for example HNSW in hnswlib or faiss (fast start, lower RAM, approximate results, a new dependency).
  - **C:** an external vector store (separate service, the most operational work).
- **Also decide:** an accuracy tolerance for approximate search, and the number of API processes.

### ARCH-3: PostgreSQL rollback strategy
- **Facts:** no reverse sync (MySQL → PostgreSQL) exists. Rolling back after users write to MySQL loses those writes unless they're exported (`backup_mysql.py`) and replayed by hand.
- **Decide:**
  - the rollback window (for example 7–14 days);
  - whether writes made after cutover may be lost or must be replayed;
  - who triggers a rollback;
  - and keep the PostgreSQL source read-only and untouched until the window closes (action plan §7.4).

### ARCH-4: removing the PostgreSQL code
- **Inventory:**
  - **48 dual-path modules** (`is_mysql_session`) across l1–l8 plus `seed/generate.py`, `seed/purge.py` and `platform_core/idempotency.py`;
  - PostgreSQL-only parts: `migrations/` (the PostgreSQL Alembic chain), `infra/postgres/` (the AGE and pgvector image), `platform_core/db/age.py`;
  - compose services `postgres`, `postgres-load` and `wal-shipper` with their volumes;
  - `make.ps1` targets `up`, `backup`, `restore`;
  - the PostgreSQL-source tools `migrate_pg_to_mysql.py`, `rehearse_data_migration.py` and `ops_common.py`;
  - 3 PostgreSQL-only integration tests.
- **Proposal:** remove everything in one change **after** cutover sign-off and the rollback window (ARCH-3), keeping the ETL until production data is reconciled.
- **Do not remove before then.**

### B3: cutover approval
Not given. It needs:
- an approved maintenance window and rollback window;
- a communications plan;
- the signed go/no-go (`CORTEX_PRODUCTION_MIGRATION_ACTION_PLAN.md` §7).

## 5. Files changed in this round
- `scripts/verify_mysql_runtime.py`
- `scripts/ops_common.py`, `scripts/bootstrap_admin.py`, `scripts/migrate_pg_to_mysql.py`
- `infra/docker-compose.yml`, `.env.example`
- `.github/workflows/ci.yml`
- `tests/conftest.py`
- `tests/unit/test_secure_connect.py`, `test_mysql_compose_security.py`, `test_mysql_session.py`, `test_mysql_keycloak.py`
- Masking only: `CORTEX_MYSQL_GIT_REVIEW_REPORT.md`, `CORTEX_MYSQL_PHASE{2,3,8}_EXECUTION_REPORT.md`, `postgresql_dependency_scan.csv`
- **New:** `tests/unit/test_verify_mysql_runtime.py`, `tests/unit/test_check_mysql_schema_drift.py`, `infra/docker-compose.mysql-stacktest.yml`, this report.
- **Test-only scratch databases created** (they're not drift targets): `cortex_ci_a`, `cortex_ci_b`, `cortex_drift_ref`, `cortex_drift_target`.

**Not changed:**
- `.env`;
- any Docker container or volume;
- the 6 DATA-1 rows;
- any credential;
- git state;
- production.
