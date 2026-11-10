# Capital Cortex — MySQL Migration Blocker Register

> **Historical record (dated 2026-11-03).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. The current register is docs/CORTEX_MYSQL_BLOCKER_REGISTER.md. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


*2026-11-03 · branch `feature/changes-login` (uncommitted; nothing committed, pushed, reset or stashed).*

**Scope.** Only blockers to moving Capital Cortex from PostgreSQL 16 to MySQL 8.4. Meris and the funding-API work are out of scope.

**Evidence.** Every result below comes from runs on 2026-11-03 against the local test server `capital-cortex-mysql-test` (MySQL 8.4.13). No production system was contacted.

**Statuses:**

| Status | Meaning |
|---|---|
| VERIFIED_CLOSED | Fixed, with evidence |
| IN_PROGRESS | Being worked on |
| OPEN | Developer or user action still needed |
| EXTERNALLY_BLOCKED | Needs DevOps or the DBA |
| REQUIRES_APPROVAL | Needs a decision |

## Summary

| | Count |
|---|---|
| Blockers in this register | **28** |
| VERIFIED_CLOSED | **14** |
| OPEN | **4** (MB-04, MB-08, MB-15, MB-24) |
| EXTERNALLY_BLOCKED | **2** (B1, B2) |
| REQUIRES_APPROVAL | **8** (MB-07, MB-11, MB-19, MB-20, MB-21, MB-22, MB-23, B3) |

## Security

### MB-01: committed fallback password `cortex-pw` (VERIFIED_CLOSED)
- **Affected files:** `infra/docker-compose.mysql.yml`.
- **Root cause:** the production overlay fell back to a committed default password.
- **Fix:** every secret uses the `${VAR:?…}` form, which stops compose if the value is missing (done on 2026-11-02).
- **Evidence:** `git grep cortex-pw` finds only the test that asserts it's absent. `test_mysql_overlay_has_no_fallback_secrets` passes.
- **Remaining action:** none. **Owner:** Developer.

### MB-02: test/demo compose files fell back to committed MySQL and Keycloak passwords (VERIFIED_CLOSED)
- **Affected files:** `infra/docker-compose.mysql-test.yml`, `infra/docker-compose.mysql-demo.yml`.
- **Root cause:** `${MYSQL_TEST_PASSWORD:-<literal>}`-style defaults.
- **Fix:** all four secrets are now required (`:?`).
- **Evidence:** `docker compose config -q` is OK with `.env`. The new `test_test_and_demo_stacks_require_secrets_and_hide_the_root_password` passes.
- **Remaining action:** none. **Owner:** Developer.

### MB-03: password literals in code, scripts, tests and the launcher (VERIFIED_CLOSED)
- **Affected files:**
  - code: `platform_core/config/settings.py` (default URL), `platform_core/db/session.py` (`get_mysql_test_url`);
  - scripts: `migrate_pg_to_mysql.py` (MySQL loopback default), `benchmark_mysql_app_paths.py`, `benchmark_mysql_slos.py`, `seed_mysql_load.py`, `verify_mysql_runtime.py`, `rehearse_data_migration.py`;
  - tests: `tests/integration/conftest.py`, `tests/unit/test_mysql_keycloak.py`, `tests/unit/test_mysql_session.py`;
  - launcher: `CORTEX_MYSQL_DEMO_START.ps1`.
- **Root cause:** convenience fallbacks equal to the dev credential.
- **Fix:**
  - The values are now read from the environment or `<NAME>_FILE`. `tests/conftest.py` loads `MYSQL_TEST_*` from the git-ignored `.env`.
  - The default URL has no password, and the launcher stops if `.env` lacks one.
  - The testcontainers fallback generates a random password.
- **Evidence:**
  - A repository-wide grep for the MySQL literals finds only the regression test that asserts they're absent.
  - New `test_etl_refuses_mysql_target_without_a_configured_password_even_on_loopback` passes.
  - The unit suite is 383/383 with no literal anywhere.
- **Remaining action:** none. **Owner:** Developer.

### MB-04: PostgreSQL-side dev fallbacks remain (OPEN)
- **Affected files:** `infra/docker-compose.yml` (the PostgreSQL rollback stack), `scripts/ops_common.py`, the PostgreSQL loopback default in `scripts/migrate_pg_to_mysql.py`.
- **Root cause:** they're part of the PostgreSQL stack, kept for the rollback window as instructed.
- **Fix:** not changed, deliberately.
- **Evidence:** grep lists 9 sites.
- **Remaining action:** remove them when the PostgreSQL stack retires after cutover, or make them `:?` now if the PostgreSQL stack is still run outside development.
- **Owner:** Developer.

### MB-05: healthcheck passed the root password on the command line (VERIFIED_CLOSED)
- **Affected files:** `infra/docker-compose.mysql-test.yml`.
- **Root cause:** `mysqladmin … -p$$MYSQL_ROOT_PASSWORD` made the password visible in the container's process list.
- **Fix:** `MYSQL_PWD="$$MYSQL_ROOT_PASSWORD" mysqladmin ping … --silent`. The container was recreated; its named volume `capital-cortex_mysql_test_data` and data were kept.
- **Evidence:**
  - Health is `healthy`, and `ps` shows 0 processes with `-p`.
  - All 10 `cortex*` databases are intact after recreation.
  - The test above passes.
- **Remaining action:** none. **Owner:** Developer.

### MB-06: the `cortex` application account held server-wide admin privileges (VERIFIED_CLOSED)
- **Affected files:** `infra/mysql/least_privilege.sql` (new), `infra/docker-compose.mysql-test.yml`.
- **Root cause:**
  - Binary logging is on, and `log_bin_trust_function_creators=0`, so only SUPER could create the schema's 4 triggers.
  - The account had been given `SUPER`, `CREATE USER`, `SYSTEM_USER`, `FILE`, `SHUTDOWN` and about 40 dynamic privileges.
- **Fix:**
  - The server now runs with `--log-bin-trust-function-creators=1`, the same as the production overlay (B12).
  - `REVOKE ALL PRIVILEGES ON *.*` from `cortex`.
  - Grants are now `ALL` on `cortex.*`, `keycloak.*` and the `cortex\_%` wildcard only.
  - The previous grants are saved in the scratchpad for exact rollback.
- **Evidence:**
  - Grants are now `USAGE ON *.*` plus the three schema grants.
  - As `cortex`: `SET GLOBAL` → 1227; `CREATE USER` → 1227; `CREATE DATABASE outside_scope` → 1044.
  - `cortex` created `cortex_privcheck_20261103` and built the full schema with Alembic: m0004, 50 tables, **4 triggers**.
  - Unit 383/383 and integration 21/0/3 run as this account.
  - Keycloak and the demo work.
  - `test_least_privilege_script_revokes_global_and_keeps_schema_grants` passes.
- **Remaining action:** DevOps provisions the production account with the same shape.
- **Owner:** Developer (done); DevOps (production).

### MB-07: the working test credential equals a value that used to be committed (REQUIRES_APPROVAL)
- **Affected files:** `.env` (git-ignored; not edited).
- **Root cause:** the code fallbacks used the real dev password.
- **Fix:** not rotated, as instructed: no rotation without a coordinated plan. Now that MB-02 and MB-03 are closed, rotation is a one-step change.
- **Remaining action:** agree a time, then:
  1. Run `ALTER USER 'cortex'@'%' IDENTIFIED BY '<new>'` as root.
  2. Update `MYSQL_TEST_PASSWORD` in `.env`.
  3. Recreate `keycloak-demo` (which reads it).
  4. Re-run the smoke test.
- **Owner:** Developer + Project Lead.

### MB-08: stale stack-test MySQL listens on all interfaces (OPEN)
- **Affected item:** container `capital-cortex-mysql` (project `capital-cortex-stacktest`, 2026-10-31, schema m0001, `0.0.0.0:13306`).
- **Root cause:** it predates the hardening, and its restart policy brings it back with Docker.
- **Fix:** my stop attempt was **refused by the session's permission policy**.
- **Remaining action:** run `docker update --restart=no capital-cortex-mysql; docker stop capital-cortex-mysql`. That keeps the container and its volume. Or recreate it from the hardened compose.
- **Owner:** Developer / user.

### MB-25: rehearsal script hard-coded rehearsal passwords (VERIFIED_CLOSED)
- **Affected files:** `scripts/rehearse_data_migration.py`.
- **Fix:** `_secret()` reads `MIGRATION_PG_PASSWORD`/`POSTGRES_PASSWORD` and `MIGRATION_MYSQL_PASSWORD`/`MYSQL_TEST_PASSWORD`, or their `_FILE` forms, and refuses to run without them.
- **Evidence:** the script compiles, and 0 literals remain.
- **Remaining action:** none. **Owner:** Developer.

## Schema consistency

### MB-09: legacy table layouts, including `alert_delivery` without `target`/`detail` (VERIFIED_CLOSED)
- **Affected files:** `migrations_mysql/versions/m0004_reconcile_legacy_layouts.py` (new).
- **Root cause:**
  - Some databases came from an early MySQL port of the schema.
  - m0001 uses `CREATE TABLE IF NOT EXISTS`, so those tables kept their old shape.
  - In `cortex`: `alert`, `alert_rule`, `alert_delivery`, `retention_run` and `legal_hold` had old columns, and two ENUMs used an old vocabulary.
  - In `cortex_integration`: legacy `alert_delivery` columns.
- **Fix:**
  - m0004 rebuilds a legacy table from the baseline **only if it has 0 rows**.
  - It converts an ENUM **only if every stored value is valid**.
  - Otherwise it stops with the exact reason. It never deletes or rewrites a row.
- **Evidence:**
  - 5 real-MySQL tests pass: rebuild and idempotence, refusal with data kept, ENUM conversion and refusal, baseline untouched, DEFAULT literal ignored.
  - The 5 legacy tables in `cortex` and the `alert_delivery` table in `cortex_integration` were rebuilt; all were empty.
  - `financial_instrument.class` and `opportunity.class` in `cortex` were converted.
- **Remaining action:** MB-11. **Owner:** Developer.

### MB-10: databases at different revisions, m0001 to m0003 (VERIFIED_CLOSED)
- **Root cause:** migrations weren't applied to every test database.
- **Fix:** `alembic -n mysql upgrade head`, run as the least-privilege `cortex` account.
- **Evidence:** `scripts/check_mysql_schema_drift.py` reports **OK** for `cortex_demo`, `cortex_integration`, `cortex_bench_1m`, `cortex_migrate_check` and `cortex_unit`, all at m0004. Tables, columns, indexes, FKs, uniques, CHECKs and triggers all match a database freshly built from the migrations.
- **Not changed, on purpose:** the restore-drill and rehearsal copies (`cortex_restore_drill_20261102`, `cortex_restore_enc_20261102`, `cortex_pgcopy_rehearsal`), so they stay faithful evidence of those drills.
- **Remaining action:** none. **Owner:** Developer.

### MB-11: `cortex` dev database still has the old `opportunity.pipeline_stage` vocabulary (REQUIRES_APPROVAL)
- **Affected item:** database `cortex` (6 old test rows).
- **Root cause:** the rows hold `screening`, which has no equivalent among the baseline stages (discovered, qualified, engaged, submitted, diligence, term_sheet, committed, closed, lost).
- **Fix:** m0004 stops here by design: the mapping is a business decision, and I haven't guessed one.
- **Evidence:** the drift report lists exactly 1 remaining difference, and the revision stays at m0003.
- **Remaining action:** either approve a mapping (for example `screening`→`qualified`) and apply it, or approve archiving the 6 test rows. Then run `alembic -n mysql upgrade head`.
- **Owner:** Project Lead (decision), Developer (apply).

### MB-12: no automated drift detection (VERIFIED_CLOSED)
- **Affected files:** `scripts/check_mysql_schema_drift.py` (new).
- **Fix:** a read-only comparison against a database built from the migrations, covering revision, tables, columns, indexes, FKs, CHECKs and triggers. It exits 1 on drift, so CI can gate on it.
- **Evidence:** it found every issue in MB-09, MB-10 and MB-11.
- **Remaining action:** add it to CI.
- **Owner:** Developer.

## Tests

### MB-13: unit-test isolation for the scoring profile (VERIFIED_CLOSED)
- **Affected files:** `tests/unit/test_mysql_invariants_and_mutex.py`.
- **Root cause:** the test assumed the org had no active profile, but `score_service` auto-creates `syrs_default`.
- **Fix:** the test deactivates existing profiles inside its own rolled-back transaction. The assertions are unchanged.
- **Evidence:** it passes alone and in the suite, and the profile is still active afterwards.
- **Remaining action:** none. **Owner:** Developer.

### MB-14: tests used the old vocabulary, hidden by the drift (VERIFIED_CLOSED)
- **Affected files:** `tests/unit/test_mysql_router_sql.py`.
- **Root cause:** the tests seeded `class='equity'` and `pipeline_stage='screening'`, which are valid in neither PostgreSQL nor the MySQL baseline.
- **Fix:** they now use `venture_equity` and `qualified`. No assertion depends on those values.
- **Evidence:** the suite is 383/383.
- **Remaining action:** none. **Owner:** Developer.

### MB-15: the default unit-test database is the drifted `cortex` (OPEN)
- **Affected item:** `.env` `MYSQL_TEST_DATABASE`.
- **Root cause:** MB-11.
- **Fix:** `cortex_unit` was created at m0004.
- **Evidence:** with `MYSQL_TEST_DATABASE=cortex_unit`, the suite is **383 passed, 0 failed**. On `cortex`, `test_copilot_queries_mysql` fails until MB-11 is resolved.
- **Remaining action:** set `MYSQL_TEST_DATABASE=cortex_unit` in `.env` (your file; not edited), or resolve MB-11.
- **Owner:** Developer.

### MB-16: integration suite after the schema and list changes (VERIFIED_CLOSED)
- **Evidence:**
  - All 8 files exit 0: **21 passed, 0 failed, 3 skipped**.
  - The skips are the PostgreSQL-only AGE Cypher, AGE catalog and pgvector HNSW tests; each points to its passing MySQL test.
  - `cortex_integration` is at m0004.
- **Remaining action:** none. **Owner:** Developer.

### MB-17: demo smoke after the changes (VERIFIED_CLOSED)
- **Evidence:**
  - Fresh API, worker and web on the current code.
  - **Smoke 10/10:** password then TOTP; `amr=[pwd,otp]`; audience; MFA-required role; audit verify; OPA 403; service account; bus → worker → audit; chain re-verify.
  - The demo kept 1,026 opportunities across the Docker and app restart.
  - The MFA marker was switched on only for this run and switched back off, keeping the user's local password-only choice (D-033).
- **Remaining action:** none. **Owner:** Developer.

## Backup and restore

### MB-18: backup and restore in development (VERIFIED_CLOSED)
- **Affected files:** `scripts/backup_mysql.py`.
- **Evidence (2026-11-03, on `cortex_integration`):**
  - Encrypted backup `20261103T055100Z`: 6 s, verify PASS.
  - Restore into the new `cortex_restore_drill_20261103`: PASS, with 50 tables, 218 rows (strict) and 4 triggers.
  - `CHECKSUM TABLE … EXTENDED`: **50/50 tables, 0 mismatches**.
  - Restoring over an existing database was refused.
  - The 2026-11-02 drill artifacts were kept.
- **Remaining action:** production schedule, key custody, off-host destination and a binlog PITR rehearsal (A6).
- **Owner:** DevOps.

## Decisions and operations

| ID | Blocker | Status | Action | Owner |
|---|---|---|---|---|
| MB-19 | Opportunity list/search p95 is above 2 s at 200k rows. The measured 2026-11-02 figures are in the readiness report, not re-run today | REQUIRES_APPROVAL | Choose: cached or on-demand facets; FULLTEXT-only search instead of `LIKE '%q%'`; buffer pool sizing | Project Lead + Developer |
| MB-20 | Keycloak shares the MySQL instance and slowed under batch load (B20) | REQUIRES_APPROVAL | Separate instance, or batch windows | Project Lead + DevOps |
| MB-21 | Vector index capacity: 143 s cold build and 2.7 GB at 200k (B23) | REQUIRES_APPROVAL | Warm-up, ANN index, or a vector store | Project Lead |
| MB-22 | Work uncommitted: 175 entries; plan in the readiness report (B21) | REQUIRES_APPROVAL | Approve the branch and commit plan | Project Lead + Developer |
| MB-23 | PostgreSQL runtime branches (50 modules) and `make up` (PostgreSQL stack) kept for the rollback window | REQUIRES_APPROVAL | Remove them in the cutover change after B3 | Project Lead |
| MB-24 | Docker Desktop stopped 3 times during this work | OPEN | Investigate host stability before demos (memory, disk, updates) | User / DevOps |
| B1 | No production PostgreSQL backup | EXTERNALLY_BLOCKED | Deliver an authorised dump (A2) | DevOps |
| B2 | Production location and access unknown | EXTERNALLY_BLOCKED | Confirm host; read-only, TLS-verified access (A1) | DevOps + Project Lead |
| B3 | No cutover approval | REQUIRES_APPROVAL | Go/no-go per `CORTEX_PRODUCTION_MIGRATION_ACTION_PLAN.md` §7 | Project Lead |
