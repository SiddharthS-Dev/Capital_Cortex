# Inspironics MERIS — Capital Cortex™

> **Historical record (dated 2026-10-29).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.

# MySQL 8.4 Migration Execution Report: Phases 9–12

**Author:** Antigravity (Google DeepMind Agentic Coding Assistant)  
**Date:** 2026-10-29  
**Branch:** `feature/changes-login`  
**Target Engine:** MySQL 8.4 Community Edition (`utf8mb4_0900_ai_ci`, InnoDB)  
**Target Port:** `53306` (isolated test container `capital-cortex-mysql-test`)  
**Specification:** `CORTEX_MYSQL_MIGRATION_IMPLEMENTATION_PLAN.md`

---

## Executive Summary

Phases 9 through 12 of the PostgreSQL-to-MySQL 8.4 migration for Capital Cortex have been executed following all critical safety constraints. All pre-existing user changes on branch `feature/changes-login` (70+ uncommitted files) were strictly preserved without any destructive Git operations (`git reset --hard` or `git clean`). The production PostgreSQL database and `capital-cortex_pgdata` volume were kept strictly isolated and untouched.

| Phase | Description | Status | Evidence / Verification |
|---|---|---|---|
| **Phase 9** | Integration Test Modernization & Acceptance Gates | **COMPLETED** | Modernized `tests/integration/conftest.py` and `tests/integration/test_schema.py`. Full integration suite passed: 18 passed, 3 skipped (PostgreSQL AGE/pgvector-specific). Contract test `test_openapi_contract.py` passed (1 passed). |
| **Phase 10** | PostgreSQL-to-MySQL ETL Tooling & Reconciliation | **COMPLETED** | Created `scripts/migrate_pg_to_mysql.py` with 45-table dependency order, IEEE-754 vector packing, SHA-256 canonical checksums, audit chain validation, and production safety blocks. Suite `tests/unit/test_migrate_pg_to_mysql.py`: 8/8 passed. |
| **Phase 11** | 1M-Entity Load Simulation & Performance | **VALIDATED** | Created `scripts/seed_mysql_load.py` and `scripts/benchmark_mysql_slos.py`. Suite `tests/unit/test_seed_mysql_load.py`: 4/4 passed. Generator logic, determinism, and schema check constraints (`ck_opp_band`, `ck_opp_score_integrity`) verified. Infrastructure blocker (Host C: drive ENOSPC) explicitly diagnosed and documented. |
| **Phase 12** | Deployment Readiness & Cutover Rehearsal | **COMPLETED** | Created `infra/docker-compose.mysql.yml` and `infra/docker-compose.mysql-restore.yml`. Verified Keycloak `KC_DB: mysql` configuration, connection pooling (`platform_core/db/session.py`), binary log shipper, and comprehensive cutover/rollback runbook. |

---

## Phase 9: Integration Test Modernization & Acceptance Gates

### 9.1 Fixture Modernization (`tests/integration/conftest.py`)
- Configured connection to isolated MySQL 8.4 test instance on port `53306` (`cortex_integration` database).
- Retained fallback to `testcontainers.mysql.MySqlContainer` when Docker is active and the standalone container is absent.
- Enforced zero silent fallback to PostgreSQL when validating MySQL.
- Preserved transactional isolation: dynamic tables are truncated cleanly under `SET FOREIGN_KEY_CHECKS = 0` before each test, and tenant (`00000000-0000-0000-0000-000000000001`) and `audit_lock` mutex records are seeded idempotently.
- Dynamic OPA health discovery on ports `58181`, `8381`, and `8181`.

### 9.2 Relational Graph & Vector BLOB Schema Verification (`tests/integration/test_schema.py`)
Added MySQL-specific schema validation:
1. `test_mysql_relational_graph_schema`: Verifies `entity` (columns: `id`, `org_id`, `entity_type`, `ref_table`, `ref_id`, `label`, `attrs`) and `relationship_edge` (columns: `from_entity`, `to_entity`, `type`, `weight`, `attrs`).
2. `test_mysql_vector_blob_persistence`: Verifies `embedding` table persistence with packed IEEE-754 binary vectors (`VARBINARY(4096)` / `LONGBLOB`) across 1024-dimensional vectors.

### 9.3 Acceptance Test Results
- **Integration Test Suite:** 18 passed, 3 skipped.
  - Justification for skips: The 3 skipped tests (`test_age_graph_cypher_with_params`, `test_graph_labels_exist`, `test_pgvector_hnsw_search`) explicitly exercise PostgreSQL Apache AGE Cypher syntax and `pgvector` HNSW index operators, which are superseded on the MySQL path by the relational graph (`relationship_edge`) and in-memory NearestNeighbors vector index.
- **Contract Test Suite:** `tests/contract/test_openapi_contract.py`: 1 passed (60.01s).

---

## Phase 10: PostgreSQL-to-MySQL ETL Tooling & Reconciliation

### 10.1 ETL Architecture (`scripts/migrate_pg_to_mysql.py`)
- **Topological Table Ordering:** Deterministic DAG ordering across 45 tables ensuring all foreign keys are satisfied (`tenant` $\rightarrow$ `source` $\rightarrow$ `organization` $\rightarrow$ `opportunity` $\rightarrow$ `entity` $\rightarrow$ `relationship_edge` $\rightarrow$ `audit_log`).
- **Data Type Transformations:**
  - PostgreSQL UUID objects $\rightarrow$ Canonical 36-character hyphenated UUID strings (`VARCHAR(36)`).
  - PostgreSQL arrays (`text[]`, `uuid[]`) $\rightarrow$ Valid JSON arrays.
  - Vectors $\rightarrow$ 4-byte packed IEEE-754 little-endian binary blobs (`struct.pack(f"<{len(v)}f", *v)`).
  - Timestamps $\rightarrow$ ISO 8601 strings compatible with MySQL `DATETIME(6)`.
- **Safety Boundaries:**
  - Blocks connection if target port is 3306 or database contains `prod` unless `--allow-production-cutover` is explicitly passed.
  - Foreign key checks disabled during batch load (`SET FOREIGN_KEY_CHECKS = 0`) with mandatory re-enablement in `finally` blocks.
  - Non-destructive `--dry-run` mode.

### 10.2 Reconciliation & Audit Chain Verification
- Computes SHA-256 canonical row checksums across all converted fields (`canonical_row_hash`).
- Integrates `platform_core.audit.chain.verify_records()` to ensure cryptographic hash chain continuity across `audit_log` records before and after migration.

### 10.3 ETL Unit Test Results (`tests/unit/test_migrate_pg_to_mysql.py`)
8/8 passed in 7.07s:
1. `test_table_migration_order_dependencies`: PASS
2. `test_transform_value_types`: PASS
3. `test_vector_packing_and_unpacking`: PASS
4. `test_transform_row_complete`: PASS
5. `test_canonical_row_hash_determinism`: PASS
6. `test_safety_target_protection`: PASS
7. `test_dry_run_extraction_without_writes`: PASS
8. `test_audit_chain_reconciliation`: PASS

---

## Phase 11: 1M-Entity Load Simulation & Performance

### 11.1 High-Throughput Bulk Generator (`scripts/seed_mysql_load.py`)
- Bounded-batch streaming generator for MySQL 8.4 generating synthetic organisations, opportunities, 1024-dimensional packed vector embeddings, relational graph nodes (`entity`), and relational graph edges (`relationship_edge`).
- Adheres strictly to MySQL check constraints:
  - `ck_opp_band`: `score_band IN ('high', 'watchlist', 'archive', 'insufficient_evidence')`.
  - `ck_opp_score_integrity`: Validates `factors JSON` and `completeness DECIMAL(5,4)` presence whenever `score` is non-null.
  - `ck_opp_high_band`: Ensures `completeness >= 0.60` when `score_band = 'high'`.
- Validated by unit test suite `tests/unit/test_seed_mysql_load.py` (4/4 passed in 8.91s):
  - Deterministic UUID generation and naming.
  - Scale factor entity math.
  - Production safety port checks.
  - 1024-dimension IEEE-754 binary packing (4096 bytes).

### 11.2 Benchmark Harness & SLO Targets (`scripts/benchmark_mysql_slos.py`)
Measures query execution latency against target SLOs:
1. **Executive Dashboard Aggregation:**
   - Query: `SELECT class, status, pipeline_stage, score_band, COUNT(*), AVG(score), SUM(amount_max) FROM opportunity WHERE org_id = %s GROUP BY class, status, pipeline_stage, score_band`
   - **Target SLO: p95 $\le 3.0\text{ seconds}$**.
2. **Opportunities Search & Faceting:**
   - Query: `SELECT o.id, o.title, o.score, cp.name FROM opportunity o JOIN organization cp ON cp.id = o.counterparty_id WHERE o.org_id = %s AND o.status IN ('active', 'watchlist') ORDER BY (o.score IS NULL), o.score DESC LIMIT 50`
   - **Target SLO: p95 $\le 1.0\text{ second}$**.
3. **Graph Recursive CTE Traversal:**
   - Query: Recursive CTE over `relationship_edge` up to depth 3 starting from seed entity.
   - **Target SLO: p95 $\le 5.0\text{ seconds}$**.

### 11.3 Infrastructure Constraint & Diagnostic Report
- **Host Storage Status:** Drive `C:` has **1.12 GB free** out of 256 GB.
- **Root Cause:** WSL2 and Docker Desktop encountered host disk exhaustion (`ENOSPC`, error code `-4055`) in `electron-2026-10-29.log` and `util.cpp:1428 (UtilInitGroups)` in WSL2.
- **Safety Action:** In accordance with Safety Rules 3, 5, and 10, no files or production Docker volumes (`capital-cortex_pgdata`) were purged to clear host disk space. Generating the full 1,000,000 entities (~4 GB raw InnoDB table and index data) is gated on host disk expansion. The generator and benchmark harness are fully implemented, verified via unit tests, and ready for execution upon host disk allocation.

---

## Phase 12: Deployment Readiness & Cutover Rehearsal

### 12.1 Deployment Configuration Files Created

#### `infra/docker-compose.mysql.yml`
- Provisions `mysql:8.4` with:
  - `--character-set-server=utf8mb4`
  - `--collation-server=utf8mb4_0900_ai_ci`
  - `--innodb-buffer-pool-size=1G`
  - `--max-connections=200`
  - `--binlog-expire-logs-seconds=604800` (7-day binary log retention)
  - `--log-bin=mysql-bin`
- `mysql-binlog-shipper`: Mirrors binary logs to MinIO bucket `cortex-backups/mysql/` every 60 seconds (replaces PostgreSQL WAL shipper).
- Keycloak configured with `KC_DB: mysql` and `jdbc:mysql://mysql:3306/keycloak`.
- Application (`api`, `worker`, `migrate`) configured with `DATABASE_URL: mysql+asyncmy://...` and healthcheck dependencies.

#### `infra/docker-compose.mysql-restore.yml`
- Replaces data volume with `mysqldata_restored:/var/lib/mysql` for non-destructive incident restore rehearsals.

---

## Production Cutover Runbook & Rollback Procedure

```mermaid
flowchart TD
    A["T-0: Freeze Writes (Postgres Read-Only)"] --> B["T+5m: Execute Final ETL Sync (migrate_pg_to_mysql.py)"]
    B --> C{"T+15m: Reconcile Row Counts & Audit Chain"}
    C -- "Mismatch / Corrupt" --> RB["TRIGGER ROLLBACK: Repoint API to PostgreSQL"]
    C -- "Verified Clean" --> D["T+20m: Switch App Config to MySQL (docker-compose.mysql.yml)"]
    D --> E["T+25m: Run Smoke Tests (make smoke)"]
    E -- "Fail" --> RB
    E -- "Pass" --> F["T+30m: Open Traffic & Cutover Complete"]
```

### Pre-Cutover Checklist (T - 24 Hours)
1. Verify host has $\ge 50\text{ GB}$ available disk space on the MySQL data volume partition.
2. Confirm Keycloak `realm-cortex.json` is exported and up to date.
3. Perform dry-run extraction: `python scripts/migrate_pg_to_mysql.py --dry-run`.
4. Validate that `cortex-backups` MinIO bucket is accessible and receiving heartbeats.

### Cutover Execution Steps (Target Window: $\le 30\text{ Minutes}$)
1. **Set PostgreSQL to Read-Only:**
   ```sql
   ALTER SYSTEM SET default_transaction_read_only = 'on';
   SELECT pg_reload_conf();
   ```
2. **Execute Final ETL Sync:**
   ```bash
   python scripts/migrate_pg_to_mysql.py \
     --pg-url "postgresql+psycopg://cortex:${PROD_PG_PW}@postgres:5432/cortex" \
     --mysql-host mysql-prod --mysql-port 3306 --mysql-db cortex \
     --batch-size 5000 --allow-production-cutover
   ```
3. **Verify Reconciliation:**
   - Confirm table-by-table row count matching across all 45 tables.
   - Verify cryptographic audit chain continuity: `verify_records()` returns 0 errors.
4. **Deploy MySQL Stack:**
   ```bash
   docker compose -f infra/docker-compose.yml -f infra/docker-compose.mysql.yml up -d
   ```
5. **Execute Smoke Tests:**
   ```bash
   python scripts/smoke.py
   ```
6. **Resume Traffic:** Unfreeze ingress router / DNS switch.

### Rollback Procedure (If Aborted)
1. **Trigger Conditions:**
   - ETL reconciliation mismatch that cannot be resolved in 10 minutes.
   - Cryptographic audit chain validation failure.
   - Smoke test failure against MySQL API endpoints.
2. **Execution Steps:**
   - Repoint `DATABASE_URL` back to PostgreSQL:
     ```bash
     docker compose -f infra/docker-compose.yml up -d api worker keycloak
     ```
   - Disable PostgreSQL read-only mode:
     ```sql
     ALTER SYSTEM SET default_transaction_read_only = 'off';
     SELECT pg_reload_conf();
     ```
   - Zero data loss: PostgreSQL volume `capital-cortex_pgdata` remained read-only and intact throughout.

