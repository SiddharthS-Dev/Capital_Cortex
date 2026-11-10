# Capital Cortex — MySQL 8.4 Migration: Current State & Remaining Work

> **Historical record (dated 2026-10-30).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


**Audit date:** 2026-10-30
**Branch:** `feature/changes-login` (confirmed)
**Method:** source code, live databases and fresh test runs. Earlier `CORTEX_MYSQL_*` reports were treated as claims to check, not as evidence.

## Verdict: **PARTIALLY COMPLETE**

The code gaps found in this audit are fixed. Fresh runs passed: the full unit suite (292 tests), the MySQL integration suite (20 passed, 3 PostgreSQL-only skips, 0 failed), end-to-end runtime verification on `asyncmy`, and an isolated physical rehearsal through the corrected ETL. **Cutover is not ready.** Two things remain open:

- **No real-data rehearsal.** No authorised PostgreSQL dump exists, so the migration has only ever been run on synthetic data.
- **Nothing measures performance at scale.** The 1M-record benchmark has never run, and its harness doesn't exercise the application's actual hot paths.

The Phase 14 verdict "READY FOR CUTOVER REVIEW" was not supported. That rehearsal would have lost four tables, could not detect bad data loads, and ran against a target that had none of the safety triggers (§16).

---

## 1–2. Repository state

| Item | Value |
|---|---|
| Branch | `feature/changes-login` |
| Modified (tracked) | 79 (77 before this audit; added: `alembic.ini`, `infra/api/Dockerfile`) |
| Untracked | 47 (38 before this audit). Added by this audit (7): `migrations_mysql/`, `infra/mysql/`, `platform_core/db/mysql_schema.py`, `tests/unit/test_migrate_reconciliation.py`, `tests/unit/test_mysql_schema_versioning.py`, this report, `CORTEX_MYSQL_INTEGRATION_PROGRESS.md`. Also newly visible but **not created by this work** (2): `dd_out.txt`, `dd_err.txt`, Docker Desktop launcher logs dated 2026-10-23, left untouched. |
| Last commit | `f2c447a Update base and JSON API perception adapters`. **None of the migration work is committed.** |

No reset, clean, stash, commit, push or branch switch was performed.

## 3–5. Feature status

**Fresh** = verified by execution during this audit. **Historical** = supported only by earlier reports.

| Feature | Status | Evidence |
|---|---|---|
| MySQL schema (`scripts/schema_mysql.sql`) | IMPLEMENTED AND VERIFIED (fresh) | 49 tables and 4 triggers created on a scratch DB through the new MySQL migration history. |
| Session/engine, dialect detection | IMPLEMENTED AND VERIFIED (fresh) | `test_mysql_session.py` passes on `asyncmy` and `aiomysql`; `verify_mysql_runtime.py` passed (§15). |
| PG/MySQL dual-path SQL in the app | IMPLEMENTED AND VERIFIED (fresh) | About 49 files branch on `is_mysql_session`. `test_mysql_router_sql.py` (10 tests) and the phase 1–3, pipeline, feedback-loop and seed integration flows pass against live MySQL (§15). |
| Graph (AGE replacement) | IMPLEMENTED AND VERIFIED (fresh, unit level) | `test_mysql_graph.py` (8 tests) passes; §11. |
| Vectors (pgvector replacement) | IMPLEMENTED; storage VERIFIED (fresh), search at scale NOT VERIFIED | §12. |
| Audit hash chain + `audit_lock` mutex | Chain VERIFIED (fresh, on migrated data); append-only trigger VERIFIED (fresh) | Rehearsal `audit_chain_valid: true`; a DELETE on `audit_log` was rejected (error 1644). |
| Keycloak on MySQL | IMPLEMENTED AND VERIFIED (fresh, test environment); stack provisioning was **missing**, now FIXED | `test_mysql_keycloak.py` passes against the test Keycloak; §13. |
| Docker Compose (MySQL stack) | Deployment blocker FIXED; config VERIFIED (`docker compose config`); stack not started | §14. |
| ETL (`scripts/migrate_pg_to_mysql.py`) | Was PARTIALLY IMPLEMENTED, now FIXED and VERIFIED (fresh, synthetic data) | §8, §16. |
| Rehearsal script | Defects FIXED | §16. |
| Reconciliation | Was unreliable (false PASS), now FIXED and VERIFIED (fresh) | §9. |
| MySQL schema versioning | Was NOT IMPLEMENTED, now IMPLEMENTED AND VERIFIED (fresh) | §18. |
| SQLAlchemy ORM metadata comparison | NOT APPLICABLE | The app uses raw SQL; there are no ORM models. |
| Real-data rehearsal | BLOCKED | No authorised dump (§16). |
| 1M benchmark | NOT RUN | §17. |

## 6–8. Tables and ETL coverage

**Actual counts:**
- **PostgreSQL** (Alembic `0001`–`0005`): 48 application tables.
- **MySQL** (`schema_mysql.sql`): 49, i.e. the same 48 plus `audit_lock`.
- **ETL before this audit:** 45 entries. That list held 44 real tables plus `audit_lock`, which doesn't exist in PostgreSQL.

**The four tables named by the previous audit were still missing** from `TABLE_MIGRATION_ORDER`:

| Table | Holds | Status now |
|---|---|---|
| `financial_instrument` | Instruments referenced by `opportunity.instrument_id` | Migrated (fresh: 1/1 rows, checksum match) |
| `legal_hold` | Legal holds, a compliance record | Migrated (fresh: 1/1) |
| `retention_run` | Retention job audit trail | Migrated (fresh: 1/1) |
| `setting` | Versioned admin settings, including jsonb scalars | Migrated (fresh: 2/2) |

**Every table now has exactly one explicit policy:**
- **Migrated (48 tables):** `TABLE_MIGRATION_ORDER`.
- **Target-only:** `audit_lock` (seeded mutex) and `alembic_version` (MySQL migration history).
- **Source-only:** `alembic_version` (PostgreSQL migration history).

A table found in either database without a policy now fails preflight.

**Order:** the "topological" order had **16 foreign-key violations**, all children placed before `inference` or `scoring_profile`. Disabling foreign-key checks during the load masked them. Fixed by moving those two parents up, and a test now checks the order against every foreign key in `schema_mysql.sql`.

## 9. Reconciliation reliability

| False-PASS path found in the code | Fix | Regression test |
|---|---|---|
| A report missing tables returned PASSED; the old unit test asserted exactly that, with 2 tables | Coverage check: missing, unexpected or duplicate tables → FAILED | `test_report_omitting_tables_fails`, `test_duplicate_and_unexpected_results_fail` |
| A table missing in the source was skipped silently and counted as 0 = 0 | Preflight inventory plus per-table problems → FAILED | `test_inventory_flags_missing_and_unpoliced_tables`, `test_table_skipped_for_missing_source_fails` |
| Columns present only in PostgreSQL were silently dropped (the load used the intersection of the two column sets) | Every non-generated source column must exist in MySQL, unless listed in `DROPPED_SOURCE_COLUMNS` (currently empty) | `test_column_plan_detects_dropped_and_generated_columns` |
| **The target checksum was computed from the in-memory transformed rows, not from MySQL**, so it could not detect truncation or encoding loss | The table is re-read from MySQL after load and checksummed | `test_target_checksum_reads_back_what_mysql_stored` |
| Decimals were hashed as 4-decimal floats; any string with `status = 'success'` hashed as `'succeeded'`; strings that looked like JSON or dates were reinterpreted | Type-aware canonical form: exact decimals, no text guessing, declared `VALUE_MAPPINGS` only | `test_checksum_compares_json_vectors_and_decimals_exactly` |
| The checksum depended on row order (`SELECT` without `ORDER BY`) | Order-independent: the sorted per-row hashes are hashed together | `test_table_checksum_is_order_independent` |
| Orphan rows were undetectable: foreign-key checks are off during load and turning them back on doesn't validate existing rows | Every MySQL foreign key is re-checked with a LEFT JOIN after load | `test_orphan_rows_fail`, `test_orphan_queries_cover_composite_keys_and_ignore_nulls` |
| A missing `audit_lock` row went unnoticed (the rehearsal had truncated it) | Mutex row is required for PASSED | `test_missing_audit_mutex_row_fails` |
| A dry run reported PASSED | A dry run reports `DRY_RUN`, never PASSED | `test_dry_run_never_reports_passed` |
| Loading into a non-empty target was allowed; the runbook's own sequence (load schema, then ETL) would have failed with a duplicate key on `tenant` | Preflight requires an empty target except the declared schema seed rows, which are replaced from the source | `test_preflight_*`; live refusal (16 problems) |

**Value conversion defects also fixed:**
- **Timezones:** aware timestamps had their zone stripped without converting to UTC. With a non-UTC PostgreSQL session, every timestamp would shift, and so would every audit hash, because `chain._ts` reads naive values as UTC. Now converted to UTC, and the source is read with `SET TIME ZONE 'UTC'`.
- **jsonb scalars** (`setting.value` such as `365` or `"dark"`) were not serialised and would be rejected by MySQL JSON columns.
- **`uuid[]` arrays** made `json.dumps` raise `TypeError`.
- **`UNIQUE_CHECKS=0`** was removed: with it, InnoDB may admit duplicates into secondary unique indexes.
- **Source consistency:** the source is now read in one read-only REPEATABLE READ snapshot.
- **Strict mode:** preflight refuses a non-strict `sql_mode`, which would silently truncate values.

## 10. Database drivers and configuration

There are no contradictions in the code; the contradictions were in the reports.

| Use | Driver | Where |
|---|---|---|
| App runtime (async) | `asyncmy` | `normalize_database_url` default; `DATABASE_URL=mysql+asyncmy://…` in `docker-compose.mysql.yml` |
| Alternative async | `aiomysql` | Supported by `session.py` (with a patch); used only by `test_mysql_keycloak.py` |
| Sync (Alembic, ETL, tools) | `pymysql` | `migrations*/env.py` rewrite `+asyncmy`/`+aiomysql` → `+pymysql`; ETL connects with pymysql |
| PostgreSQL source | `psycopg` 3 | ETL extraction |

Installed: asyncmy 0.2.17, aiomysql 0.3.2, pymysql 1.2.3, psycopg 3.3.6, SQLAlchemy 2.0.55, Alembic 1.20.1.

**Report errors corrected here:**
- Phase 14 says its runtime probe used `aiomysql`; the runtime default is `asyncmy`.
- Phase 13 lists `platform_core/config.py` as inspected; that file does not exist (settings are in `platform_core/config/settings.py`).
- Phase 14 says `source_run.status` maps `succeeded`→`success`. The code maps `success`→`succeeded`, and both schemas allow only `succeeded`.

**Host note:** early in this audit, Windows Application Control blocked the native extensions of `asyncmy` and `hypothesis` ("DLL load failed … Application Control policy has blocked this file"). The block was **transient**: later in the same session both imported normally and every `asyncmy` test passed. The likely cause is native files in this OneDrive-synced `.venv` not yet being available locally or still being scanned. If it recurs, keep the venv outside OneDrive or mark it "Always keep on this device".

## 11. Graph migration

The application does **not** use recursive CTEs, contrary to the earlier reports. `cortex/l2_representation/graph_traversal.py` runs a Python-driven BFS that issues one indexed `relationship_edge` query per hop. `WITH RECURSIVE` appears only in `verify_mysql_runtime.py`, `rehearse_data_migration.py` and `benchmark_mysql_slos.py`.

**Status:** implemented and verified fresh at unit level (`test_mysql_graph.py`: 8 passed against live MySQL). Its performance at scale is unmeasured (§17).

## 12. Vector migration

- **Storage:** 1024-dim float32 packed little-endian into `VARBINARY(4096)` (`platform_core/db/vector.py`). **Verified fresh:** `embedding.vector` survived PostgreSQL → MySQL with byte-exact checksums (5/5 rows). The checksum now compares packed float32 bytes, not 5-decimal rounding.
- **Search:** a per-tenant scikit-learn `NearestNeighbors` index is built in memory from *all* of the tenant's embeddings and cached. At 1M embeddings that is about 4 GB per tenant. This is the largest unmeasured scale risk (§17).

## 13. Keycloak

- The test Keycloak (26.0) runs on MySQL `keycloak`; this audit re-ran its unit suite with the containers up (§15).
- **Gap fixed:** in `docker-compose.mysql.yml`, nothing created the `keycloak` database or granted the app user access to it. `MYSQL_DATABASE` creates only `cortex`. The test environment's DB had been created by hand from `schema_mysql.sql` as root.
- **Added:** `infra/mysql/init/01-keycloak.sh`, mounted at `/docker-entrypoint-initdb.d`. It runs only when a data volume is first initialised; for an existing volume, run its two statements once as root.

## 14. Docker

- **Daemon:** unavailable for most of this audit, then restarted. The isolated test containers were started by this audit: `capital-cortex-mysql-test` (:53306), `cortex-pg-rehearsal` (:55433), and OPA/Keycloak test. Their mounts were inspected first, and none uses `capital-cortex_pgdata`.
- **Production:** no `capital-cortex-postgres` container exists on this host; the volume `capital-cortex_pgdata` exists and was not touched.
- **Deployment blocker fixed:** in the MySQL Compose stack, `migrate` inherited `alembic upgrade head`, which runs the PostgreSQL history (`CREATE EXTENSION …`) and fails on MySQL. `api` waits for `migrate` to succeed, so **the MySQL stack could never start**. `migrate` now runs `alembic -n mysql upgrade head`.
- **Image fixed:** `infra/api/Dockerfile` now ships `migrations_mysql/` and `scripts/schema_mysql.sql`.
- `docker compose -f infra/docker-compose.yml -f infra/docker-compose.mysql.yml config` resolves correctly. The full stack has not been started.

## 15. Test results (fresh, 2026-10-30)

| Suite | Result |
|---|---|
| ETL + reconciliation + schema versioning (`test_migrate_pg_to_mysql.py`, `test_migrate_reconciliation.py`, `test_mysql_schema_versioning.py`) | **43 passed** (10 existing + 33 new) |
| Full unit suite, Docker down (before fixes) | 214 passed, 14 failed, 31 errors. All 45 failures environmental: `asyncmy` DLL blocked (transient), or MySQL/Keycloak unreachable. |
| **Full unit suite, test containers up (after fixes)** | **292 passed, 0 failed, 0 errors** (7 min 17 s). Includes every MySQL session, graph, vector, router-SQL, invariant/mutex, Keycloak and ETL test. |
| **Integration suite (`tests/integration -m integration`)** | **23 tests: 20 passed, 0 failed, 3 skipped**. All 8 files exit 0; 705 s wall clock (pytest 601 s). Run file by file in the foreground against `cortex_integration` on :53306, with no testcontainers fallback. The 3 skips are PostgreSQL-only (AGE Cypher, AGE labels, pgvector HNSW), conditional on the MySQL dialect, each with passing MySQL coverage. Per-file detail: [`CORTEX_MYSQL_INTEGRATION_PROGRESS.md`](CORTEX_MYSQL_INTEGRATION_PROGRESS.md). An earlier single background attempt was interrupted when the session ended; that was not a failure. |
| **`scripts/verify_mysql_runtime.py`** | **PASSED** on MySQL 8.4.13 with `asyncmy`: `/healthz` 200, transactional write/read, graph edge, 1024-dim blob round-trip, audit chain verified across 506 records, clean reconnect after pool dispose. |

**Test changes:** in `test_migrate_pg_to_mysql.py`, three tests' mock setup was updated for the new metadata queries and the MySQL read-back. No assertion was removed. One assertion changed from `len(table_results) == 2` to the full table count. The original 2-table input is now `test_report_omitting_tables_fails`, which requires FAILED.

## 16. Physical data rehearsal

**State found:**
- The Phase 14 rehearsal source (`capital-cortex-pg-rehearsal`, database `cortex`) no longer exists.
- The container present, `cortex-pg-rehearsal`, holds database `cortex_disposable`: full schema, **no data**. `rehearse_data_migration.py` hardcodes database `cortex`, so it cannot run against it as-is.
- The target `cortex_rehearsal` had **0 triggers** (no I3 outbox/recommendation invalidation, no append-only audit) and **0 `audit_lock` rows**, because the rehearsal truncated it.

**Fresh isolated rehearsal**, through the corrected ETL, with `cortex_rehearsal` first brought onto the versioned schema:
- **Source:** `cortex_disposable` with the rehearsal script's synthetic seed, plus one or two rows each in the four previously missing tables.
- **Result:** 48/48 tables reconciled. 17 tables populated, 31 empty.
- **Integrity:** 0 count mismatches, 0 checksum mismatches (read back from MySQL), 0 orphans, mutex present, audit chain valid. **PASSED** in 4.62 s.
- **Negative check:** re-running onto the populated target was refused before any write (16 problems).

**What this does not prove:** behaviour on real data. 31 of 48 tables had no rows. Volume, real jsonb shapes, encodings and real foreign-key graphs are untested.

**Missing dependency:** an authorised, sanitised `pg_dump -Fc` of production (or a staging copy), restored into a disposable PostgreSQL 16 + AGE + pgvector container. **No dump or backup exists in the workspace.**

## 17. One-million-record benchmark

**Status: NOT RUN.** Disk (17 GB free; about 5 GB needed) and Docker are no longer blockers.

**Not run deliberately:** `scripts/benchmark_mysql_slos.py` times hand-written SQL, including a recursive CTE the app never executes. It does not exercise the application's real hot paths:
- the per-hop graph BFS;
- the in-memory scikit-learn vector index, about 4 GB per tenant at 1M embeddings.

Its numbers would not answer the scale question. The harness needs those paths added first.

## 18. MySQL schema versioning

- **Found:** NOT IMPLEMENTED. `migrations/` is PostgreSQL-only (`CREATE EXTENSION`, plpgsql, jsonb) with no dialect guards. The MySQL schema existed only as a hand-applied SQL file. The integration fixture applied it with a naive `split(";")` that breaks the `DELIMITER $$` trigger bodies, so a freshly created test database got no triggers.
- **Implemented (minimal; the PostgreSQL history is untouched):**
  - `platform_core/db/mysql_schema.py`: a `DELIMITER`-aware statement splitter. `CREATE DATABASE`/`GRANT` are left to provisioning.
  - `migrations_mysql/` (`env.py`, template, `m0001_mysql_baseline`): applies `schema_mysql.sql`, is idempotent, and refuses non-MySQL URLs.
  - `alembic.ini` gains a `[mysql]` section. Usage: `alembic -n mysql upgrade head`. Future MySQL changes go in new revisions.
  - `tests/integration/conftest.py` now uses the splitter.
- **Verified fresh:**
  - On scratch DB `cortex_migrate_check`, two upgrades gave 49 tables plus `alembic_version`, 4 triggers and the seed rows, and the second upgrade was a no-op.
  - A DELETE on `audit_log` was rejected by the trigger.
  - `cortex_rehearsal` was upgraded in place and gained its 4 triggers and mutex row.

## 19. Remaining blockers

1. **No authorised production dump.** The real-data rehearsal can't be done. The owner needs to provide a sanitised `pg_dump`.
2. **No meaningful scale measurement.** The benchmark harness doesn't cover the vector search or graph BFS (§17).
3. **Nothing committed.** 79 modified and 47 untracked files, in a OneDrive-synced folder, on a branch named for an unrelated login feature.
4. **The cutover runbook needs revisiting** (Phase 14 §6):
   - Phase B should apply the schema with `alembic -n mysql upgrade head`, not the `mysql` CLI.
   - The compose MySQL port defaults to 53306, not the 3306 the runbook assumes.
   - Phase C must create the `keycloak` database.
5. **No production PostgreSQL on this host.** The location of the production source must be confirmed.

## 20. Next steps, in order

1. Commit the migration work on a dedicated branch after review. This audit made no commits.
2. Run the unit and integration suites in Linux CI as a standing gate, so results don't depend on this host.
3. Obtain an authorised, sanitised dump and restore it into a disposable PostgreSQL. Point `scripts/rehearse_data_migration.py` at it: its database name is hardcoded to `cortex`, and it would also re-seed synthetic data, so the seeding step should be skipped for a real dump. Then run `migrate_pg_to_mysql.py --report …`. Any column-coverage failures need an explicit decision in `DROPPED_SOURCE_COLUMNS`.
4. Extend `benchmark_mysql_slos.py` to call `search_opportunity_embeddings` and `graph_traversal.neighbourhood`/`paths`. Then run it at 1M on the isolated MySQL (`cortex_benchmark`), measuring memory as well as latency.
5. Update the cutover runbook (§19 item 4) and start the full MySQL Compose stack once in staging.
6. Then take the go/no-go to stakeholders.

**Test artefacts left in the isolated test MySQL (:53306):**
- Scratch database `cortex_migrate_check`. It contains one probe `audit_log` row that the append-only trigger prevents deleting; drop the database when no longer needed.
- `cortex_rehearsal`: now on `m0001_mysql_baseline`, holding the fresh rehearsal data.
- `cortex_disposable` (:55433): holds the synthetic seed.
