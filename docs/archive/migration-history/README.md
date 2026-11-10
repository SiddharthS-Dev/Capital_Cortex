# Migration history archive

Dated reports written during the PostgreSQL 16 to MySQL 8.4 migration of Capital Cortex, kept as historical records.
Each file starts with a note giving its date. They are superseded: for the current state use
`docs/CORTEX_DOCUMENTATION_INDEX.md`, and for a summary of how the migration progressed use
`docs/CORTEX_MYSQL_MIGRATION_HISTORY.md`.

Machine-specific paths were replaced with placeholders (`<repo>`, `<workspace>`, `<home>`). References to raw test logs
(`docs/evidence/...`) and to working papers that are not in the repository cannot be followed here; the raw logs are
summarised in `docs/CORTEX_MYSQL_EVIDENCE_INDEX.md`.

| Date | Report | Title |
|---|---|---|
| 2026-10-26 | [CORTEX_MYSQL_MIGRATION_BASELINE_INVENTORY.md](CORTEX_MYSQL_MIGRATION_BASELINE_INVENTORY.md) | Cortex MySQL Migration: Comprehensive Baseline Inventory Report |
| 2026-10-26 | [CORTEX_MYSQL_MIGRATION_FEASIBILITY_REPORT.md](CORTEX_MYSQL_MIGRATION_FEASIBILITY_REPORT.md) | Cortex PostgreSQL-to-MySQL Migration Feasibility Analysis Report |
| 2026-10-26 | [CORTEX_MYSQL_MIGRATION_IMPLEMENTATION_PLAN.md](CORTEX_MYSQL_MIGRATION_IMPLEMENTATION_PLAN.md) | Cortex PostgreSQL-to-MySQL Migration Implementation Plan |
| 2026-10-26 | [CORTEX_MYSQL_MIGRATION_VERIFICATION_REPORT.md](CORTEX_MYSQL_MIGRATION_VERIFICATION_REPORT.md) | Cortex PostgreSQL-to-MySQL Migration Verification & Readiness Report |
| 2026-10-26 | [CORTEX_MYSQL_SCHEMA_MAPPING.md](CORTEX_MYSQL_SCHEMA_MAPPING.md) | Cortex PostgreSQL to MySQL 8.4 Schema Mapping Specification |
| 2026-10-27 | [CORTEX_MYSQL_PHASE4_EXECUTION_REPORT.md](CORTEX_MYSQL_PHASE4_EXECUTION_REPORT.md) | Cortex PostgreSQL-to-MySQL Migration — Phase 4 Execution Report: Graph Subsystem Migration |
| 2026-10-27 | [CORTEX_MYSQL_PHASE5_EXECUTION_REPORT.md](CORTEX_MYSQL_PHASE5_EXECUTION_REPORT.md) | Cortex PostgreSQL-to-MySQL Migration — Phase 5 Execution Report: Vector Subsystem Migration |
| 2026-10-27 | [CORTEX_MYSQL_PHASE6_EXECUTION_REPORT.md](CORTEX_MYSQL_PHASE6_EXECUTION_REPORT.md) | Cortex PostgreSQL-to-MySQL Migration — Phase 6 Execution Report: Triggers, Invariants, and Mutex Migration |
| 2026-10-27 | [CORTEX_MYSQL_PHASE7_EXECUTION_REPORT.md](CORTEX_MYSQL_PHASE7_EXECUTION_REPORT.md) | Cortex MySQL Migration — Phase 7: Application SQL Sanitization Across API Routers and Core Services |
| 2026-10-29 | [CORTEX_MYSQL_PHASE13_VERIFICATION_REPORT.md](CORTEX_MYSQL_PHASE13_VERIFICATION_REPORT.md) | Capital Cortex — Phase 13: MySQL 8.4 End-to-End Deployment Verification Report |
| 2026-10-29 | [CORTEX_MYSQL_PHASES_9_12_EXECUTION_REPORT.md](CORTEX_MYSQL_PHASES_9_12_EXECUTION_REPORT.md) | Inspironics MERIS — Capital Cortex™ |
| 2026-10-30 | [CORTEX_MYSQL_CURRENT_STATE_AND_REMAINING_WORK_REPORT.md](CORTEX_MYSQL_CURRENT_STATE_AND_REMAINING_WORK_REPORT.md) | Capital Cortex — MySQL 8.4 Migration: Current State & Remaining Work |
| 2026-10-30 | [CORTEX_MYSQL_FINAL_IMPLEMENTATION_REPORT.md](CORTEX_MYSQL_FINAL_IMPLEMENTATION_REPORT.md) | Capital Cortex — MySQL 8.4 Final Implementation Report |
| 2026-10-30 | [CORTEX_MYSQL_FINAL_READINESS_REPORT.md](CORTEX_MYSQL_FINAL_READINESS_REPORT.md) | Capital Cortex — MySQL 8.4 Final Readiness Report |
| 2026-10-30 | [CORTEX_MYSQL_FINAL_TEST_REPORT.md](CORTEX_MYSQL_FINAL_TEST_REPORT.md) | Capital Cortex — MySQL 8.4 Final Test Report |
| 2026-10-30 | [CORTEX_MYSQL_INTEGRATION_PROGRESS.md](CORTEX_MYSQL_INTEGRATION_PROGRESS.md) | Capital Cortex — MySQL Integration Suite Progress |
| 2026-10-30 | [CORTEX_MYSQL_LIVE_DEMO_GUIDE.md](CORTEX_MYSQL_LIVE_DEMO_GUIDE.md) | Capital Cortex on MySQL 8.4 — Live Demo Guide |
| 2026-10-30 | [CORTEX_MYSQL_PHASE14_REHEARSAL_REPORT.md](CORTEX_MYSQL_PHASE14_REHEARSAL_REPORT.md) | Capital Cortex — Phase 14: Full ETL Rehearsal, Data Reconciliation & Cutover Readiness Report |
| 2026-10-31 | [CORTEX_MYSQL_BLOCKER_CLOSURE_REPORT.md](CORTEX_MYSQL_BLOCKER_CLOSURE_REPORT.md) | Capital Cortex — MySQL 8.4 Blocker Closure Report |
| 2026-10-31 | [CORTEX_MYSQL_GIT_REVIEW_REPORT.md](CORTEX_MYSQL_GIT_REVIEW_REPORT.md) | Capital Cortex — Git Review Before Committing the MySQL Work |
| 2026-11-02 | [CORTEX_B1_BACKUP_READINESS_REPORT.md](CORTEX_B1_BACKUP_READINESS_REPORT.md) | B1 — Production PostgreSQL Backup Readiness |
| 2026-11-02 | [CORTEX_B2_PRODUCTION_ACCESS_REPORT.md](CORTEX_B2_PRODUCTION_ACCESS_REPORT.md) | B2 — Production PostgreSQL Access |
| 2026-11-02 | [CORTEX_B3_CUTOVER_READINESS_REPORT.md](CORTEX_B3_CUTOVER_READINESS_REPORT.md) | B3 — Production Cutover Readiness |
| 2026-11-02 | [CORTEX_DATABASE_ARCHITECTURE_REPORT.md](CORTEX_DATABASE_ARCHITECTURE_REPORT.md) | Capital Cortex — Database Architecture Report

*Read-only audit, 2026-11-02. No code, schema or data was changed. The only database access was `SELECT`s against `information_schema` on the local **test** MySQL (`capital-cortex-mysql-test`).*

## 1. Repository discovery

/ Item / Value / Evidence /
/---/---/---/
/ Repository root / `<repo>` / `git rev-parse --show-toplevel` /
/ Branch / `feature/changes-login`, HEAD `f2c447a` ("Update base and JSON API perception adapters") / `git branch`, `git log -1` /
/ Working tree / **Uncommitted:** about 80 modified and 70 untracked files (`git status --short` = 152 lines). Includes the whole MySQL migration (`migrations_mysql/`, `scripts/schema_mysql.sql`, `infra/docker-compose.mysql*.yml`, `platform_core/db/compat.py`, `mysql_schema.py`, tests) / `git status --short` /
/ Runtime database / **MySQL 8.4** (`image: mysql:8.4`, verified server `8.4.13`), InnoDB, `utf8mb4` / `utf8mb4_0900_ai_ci` / `infra/docker-compose.mysql.yml`, `SELECT VERSION()` /
/ Migration source / rollback / **PostgreSQL 16 + Apache AGE 1.5.0 + pgvector 0.8.0** (base `infra/docker-compose.yml`) / compose /
/ Configuration / `platform_core/config/settings.py:31` `database_url = mysql+asyncmy://…@127.0.0.1:53306/cortex` (local test default). `ENV=staging/prod/production` refuses to start without an explicit `DATABASE_URL` (`_explicit_database` validator). The engine logs the URL with the password hidden (`platform_core/db/session.py`) / code /
/ Drivers / SQLAlchemy `[asyncio]` 2.0 with **asyncmy** (runtime) and aiomysql; PyMySQL (ETL/tools); psycopg 3 (PostgreSQL source) / `pyproject.toml` /
/ ORM / **No ORM models** (0 `DeclarativeBase`/`Mapped`). Raw SQL through `text()`: **464 sites** in `cortex/` and `platform_core/`. 50 modules branch on `is_mysql_session` (MySQL/PostgreSQL dual paths) / `git grep` /
/ Migrations, PostgreSQL / Alembic `migrations/versions`: `0001_initial`, `0002_phase1`, `0003_phase2`, `0004_phase3`, `0005_load_indexes` / files /
/ Migrations, MySQL / Alembic `alembic -n mysql`, `migrations_mysql/versions`: `m0001_mysql_baseline` (loads `scripts/schema_mysql.sql`), `m0002_legal_hold_columns`, `m0003_opportunity_list_indexes` (online `ALGORITHM=INPLACE, LOCK=NONE`) / files /
/ Init scripts / `scripts/schema_mysql.sql` (DDL at head); `infra/mysql/` (creates the `keycloak` database); `seed/generate.py`, `seed/purge.py` / files /
/ Compose services / `infra/docker-compose.mysql.yml` overlay:<br>- `mysql` (8.4; `--log-bin-trust-function-creators=1`, ROW binlog; every secret required `:?`; `127.0.0.1` by default)<br>- `migrate`, `api`, `worker`, `web`, `keycloak` (on MySQL), `redis`, `minio`, `opa`, `vault`, observability<br>- `docker-compose.mysql-private.yml` removes the host port for production<br>- `-test`, `-demo` and `-restore` variants exist / files /

## 2. Totals

/ Metric / Static DDL (`schema_mysql.sql`) / Live `cortex_integration` (8.4.13) /
/---/---/---/
/ Tables (excluding `alembic_version`) / 49 / 49 /
/ Columns / 754 / 759 (see §6, drift) /
/ Foreign keys / 117, all without `ON DELETE` (= NO ACTION) / 117, `delete_rule = NO ACTION` ×117 /
/ CHECK constraints / 98 (22 of them provenance checks, 34 `IN (...)` status domains) / 98 /
/ UNIQUE constraints / 26 / 26 /
/ Secondary indexes / 66 declared / 123 non-unique (adds InnoDB's automatic FK indexes) /
/ FULLTEXT / 1 (opportunity title/description) / — /
/ Triggers / 4: `trg_audit_no_update`, `trg_audit_no_delete` (append-only `audit_log`), `trg_outbox_invalidate`, `trg_recommendation_invalidate` / 4 /
/ Views / routines / events / 0 / 0 /
/ Primary keys / 47 × `VARCHAR(36)` UUID with `DEFAULT (UUID())`; `audit_log.seq BIGINT`; `audit_lock.id INT` / — /
/ JSON / ENUM / generated / binary columns / 95 / 3 / 5 / 2 / — /
/ Timestamps / `DATETIME(6)` (UTC), `DATE` / — /

## 3. Design

- **Multi-tenant in one database.**
  - `tenant(id, name, created_at)`.
  - **47 tables carry `org_id VARCHAR(36) NOT NULL` with an FK to `tenant`**. Every query is org-scoped.
  - Contrast with Meris, which uses one database per tenant.
- **Provenance is enforced by the schema.**
  - `source_ref` JSON and `inference_id` → `inference`.
  - 22 `ck_*_provenance` CHECKs: a row must cite a source or an inference.
- **Audit:**
  - `audit_log` is an append-only SHA-256 hash chain (`seq`, `prev_hash`, `hash`), protected by 2 triggers (SIGNAL on UPDATE/DELETE).
  - Writers serialise on `audit_lock` with `SELECT … FOR UPDATE`.
  - The chain head is read with `FOR UPDATE`, because of the REPEATABLE READ defect fixed in B8.
- **Graph (replaces Apache AGE):**
  - `entity` (`entity_type`, `ref_table`, `ref_id`, `label`, `attrs`) and `relationship_edge` (`from_entity`, `to_entity`, `type`, `weight`).
  - Breadth-first traversal runs in the application.
- **Vectors (replace pgvector):**
  - `embedding.vector VARBINARY(4096)` holds a 1,024-dimension float32 little-endian vector, keyed by (`entity_type`, `entity_id`, `model`, `chunk_index`) plus `text_hash`.
  - Exact cosine runs in NumPy over a per-tenant in-memory matrix (`platform_core/db/vector.py`).
- **Authentication:**
  - The app database has **no user or credential tables**. Identities are in **Keycloak**, which keeps its own `keycloak` database on the same MySQL server.
  - RBAC comes from Keycloak roles (`config/roles.yaml`) plus OPA.
  - Actor columns hold Keycloak subjects or usernames as strings (`requested_by`, `approver_id`, `recorded_by`, …).
  - `approval_decision` records `roles`, `grants`, `mfa` and `auth_time` as evidence.
- **Background jobs:**
  - Redis Streams bus plus an APScheduler worker (`python -m cortex.worker`).
  - Per-domain ledgers in the database: `source_run`, `agent_run`, `retention_run`, `outbox`, `alert_delivery`.
  - Idempotency comes from `api_idempotency`, and partial-unique emulation from generated `v_*` columns (`v_active_org`, `v_latest_doc`).
- **Governance:**
  - `approval` uses signed one-time tokens (`token_jti`, `token_expires_at`, `token_used_at`) bound to a `content_hash`.
  - `outbox` and `recommendation` invalidation triggers.
  - `legal_hold` columns plus a `legal_hold` table, with `retention_run`.
- **Search:**
  - FULLTEXT on opportunities, used together with `LIKE '%q%'`, which scans the whole table.
  - m0003 adds the indexes `ix_opp_recent`, `ix_opp_completeness` and `ix_opp_facets`.

## 4. Relationships (summary)

- **Hub tables:**
  - `tenant` (47 inbound FKs);
  - `inference` (provenance, about 25 inbound);
  - `opportunity` (meeting, interaction, milestone, document, dataroom_package, agent_run, proposal, factor_history, recommendation, outbox, outcome).
- **Self-references:**
  - `organization.merged_into`, `entity.merged_into`;
  - `document.previous_version_id`, `agent_run.parent_run_id`.
- **Many-to-many relationships are not stored in junction tables.** Opportunity tags, sectors, evidence and claims are JSON arrays. `relationship_edge` holds graph links.
- **Cascades:** none. Every FK is NO ACTION; deletes are done by the application (retention honours legal hold).

## 5. Migration state (evidence: `CORTEX_MYSQL_FINAL_STATUS_SUMMARY.md`, 2026-11-02)

- **PostgreSQL→MySQL migration completion:** about **77%** overall; demo 95%, production 42%.
- **ETL:** `scripts/migrate_pg_to_mysql.py` (checksum reconciliation, TLS-verified connections, no password on the CLI).
- **Real-data rehearsal on a development copy:** 48/48 tables reconciled, 0 mismatches.
- **Not done:**
  - production backup, access and approval (B1/B2/B3);
  - search p95 target at 200k;
  - the work is not committed.

## 6. Findings from this audit (new, verified)

1. **Schema drift in the `cortex` test database (the new default `DATABASE_URL`).**
   - Its `alert_delivery` has `recipient, attempts, last_attempt_at, error, payload` and **no `target` or `detail`**.
   - The application writes `alert_delivery (org_id, alert_id, channel, target, status, detail)` (`cortex/l8_actuation/alerts.py:296`), and `scripts/schema_mysql.sql` matches the application.
   - `cortex_integration` has both column sets (15 columns). `cortex_demo`, `cortex_bench_1m` and `cortex_pgcopy_rehearsal` match the DDL (10 columns).
   - **Cause:** `m0001_mysql_baseline` uses `CREATE TABLE IF NOT EXISTS`, so it doesn't reconcile a table created earlier with another shape.
   - **Not fixed** (read-only audit).
2. **Schema revision drift:**
   - `cortex_bench_1m` is at `m0003`;
   - `cortex`, `cortex_demo`, `cortex_integration` and `cortex_pgcopy_rehearsal` are at `m0002`;
   - the stack-test MySQL is at `m0001`.

## 7. Per-table inventory (generated from `scripts/schema_mysql.sql`)

"ON DELETE RESTRICT (default)" means no clause was declared, which InnoDB applies as NO ACTION. Migration history gives the first MySQL revision that names the table and the PostgreSQL revision that created it. |
| 2026-11-02 | [CORTEX_MYSQL_FINAL_STATUS_SUMMARY.md](CORTEX_MYSQL_FINAL_STATUS_SUMMARY.md) | Capital Cortex — MySQL Migration Status |
| 2026-11-02 | [CORTEX_PRODUCTION_DB_DISCOVERY_REPORT.md](CORTEX_PRODUCTION_DB_DISCOVERY_REPORT.md) | Capital Cortex — Production Database Discovery Report |
| 2026-11-03 | [CORTEX_ENTERPRISE_SECURITY_IMPLEMENTATION_REPORT.md](CORTEX_ENTERPRISE_SECURITY_IMPLEMENTATION_REPORT.md) | Capital Cortex: Enterprise Security Implementation Report |
| 2026-11-03 | [CORTEX_MYSQL_BLOCKER_REGISTER_2026-11-03.md](CORTEX_MYSQL_BLOCKER_REGISTER_2026-11-03.md) | Capital Cortex — MySQL Migration Blocker Register |
| 2026-11-03 | [CORTEX_MYSQL_BLOCKER_RESOLUTION_REPORT.md](CORTEX_MYSQL_BLOCKER_RESOLUTION_REPORT.md) | Capital Cortex — MySQL Migration Blocker Resolution Report |
| 2026-11-03 | [CORTEX_MYSQL_PHASE2_EXECUTION_REPORT.md](CORTEX_MYSQL_PHASE2_EXECUTION_REPORT.md) | Cortex PostgreSQL-to-MySQL Migration — Phase 2 Execution Report: Isolated Test Environment Setup |
| 2026-11-03 | [CORTEX_MYSQL_PHASE3_EXECUTION_REPORT.md](CORTEX_MYSQL_PHASE3_EXECUTION_REPORT.md) | Cortex PostgreSQL-to-MySQL Migration — Phase 3 Execution Report: Database Driver & Connection Session Plumbing |
| 2026-11-03 | [CORTEX_MYSQL_PHASE8_EXECUTION_REPORT.md](CORTEX_MYSQL_PHASE8_EXECUTION_REPORT.md) | Cortex PostgreSQL-to-MySQL Migration — Phase 8 Execution Report: Keycloak Database Migration Scope |
| 2026-11-03 | [CORTEX_TEST_EXECUTION_REPORT.md](CORTEX_TEST_EXECUTION_REPORT.md) | Capital Cortex: Test Execution Report |
| 2026-11-04 | [CORTEX_E2E_ROOT_CAUSE_REPORT.md](CORTEX_E2E_ROOT_CAUSE_REPORT.md) | Capital Cortex: E2E Panel Timeouts — Root Cause Report |
| 2026-11-04 | [CORTEX_MYSQL_BLOCKER_CLOSURE_REGISTER.md](CORTEX_MYSQL_BLOCKER_CLOSURE_REGISTER.md) | Capital Cortex: MySQL Migration Blocker Closure Register |
| 2026-11-04 | [CORTEX_MYSQL_COMPLETE_OPEN_BLOCKER_AUDIT.md](CORTEX_MYSQL_COMPLETE_OPEN_BLOCKER_AUDIT.md) | Capital Cortex: Complete Open Blocker Audit (PostgreSQL 16 → MySQL 8.4) |
| 2026-11-04 | [CORTEX_MYSQL_FINAL_COMPLETION_REPORT.md](CORTEX_MYSQL_FINAL_COMPLETION_REPORT.md) | Capital Cortex: MySQL 8.4 Migration — Final Completion Report |
| 2026-11-04 | [CORTEX_MYSQL_INTEGRATION_ROOT_CAUSE_REPORT.md](CORTEX_MYSQL_INTEGRATION_ROOT_CAUSE_REPORT.md) | Capital Cortex: MySQL Integration Suite — Root Cause Report |
| 2026-11-04 | [CORTEX_MYSQL_PRODUCTION_READINESS_REPORT.md](CORTEX_MYSQL_PRODUCTION_READINESS_REPORT.md) | Capital Cortex: MySQL Production Readiness Report |
| 2026-11-05 | [CORTEX_MYSQL_STATUS_REPORT_2026-11-05.md](CORTEX_MYSQL_STATUS_REPORT_2026-11-05.md) | Capital Cortex — MySQL Migration Status, 2026-11-05 |
| 2026-11-07 | [CORTEX_MYSQL_FINAL_ACCEPTANCE_REPORT.md](CORTEX_MYSQL_FINAL_ACCEPTANCE_REPORT.md) | Capital Cortex: MySQL Migration Final Acceptance Report |
| 2026-11-07 | [CORTEX_MYSQL_FINAL_BLOCKER_REGISTER_2026-11-07.md](CORTEX_MYSQL_FINAL_BLOCKER_REGISTER_2026-11-07.md) | Capital Cortex — MySQL 8.4 Final Blocker Register, 2026-11-07 |
| 2026-11-07 | [CORTEX_MYSQL_FINAL_EXECUTION_PLAN.md](CORTEX_MYSQL_FINAL_EXECUTION_PLAN.md) | Capital Cortex: MySQL 8.4 Migration, Final Execution Plan |
| 2026-11-07 | [CORTEX_MYSQL_FINAL_TECHNICAL_PROOF_REPORT_2026-11-07.md](CORTEX_MYSQL_FINAL_TECHNICAL_PROOF_REPORT_2026-11-07.md) | Capital Cortex — PostgreSQL 16 → MySQL 8.4 Technical Proof Report, 2026-11-07 |
| 2026-11-07 | [CORTEX_MYSQL_STATUS_REPORT_2026-11-07.md](CORTEX_MYSQL_STATUS_REPORT_2026-11-07.md) | Capital Cortex — MySQL Migration Test Completion, 2026-11-07 |
| 2026-11-07 | [CORTEX_MYSQL_TEAMS_HANDOVER_SUMMARY_2026-11-07.md](CORTEX_MYSQL_TEAMS_HANDOVER_SUMMARY_2026-11-07.md) | Capital Cortex — MySQL 8.4 Migration: Handover Summary (2026-11-07) |
| 2026-11-07 | [CORTEX_MYSQL_TEST_CASE_EVIDENCE_2026-11-07.md](CORTEX_MYSQL_TEST_CASE_EVIDENCE_2026-11-07.md) | Capital Cortex — MySQL 8.4 Test Case Evidence, 2026-11-07 |
| 2026-11-08 | [CORTEX_MYSQL_HANDOVER_REPORT.md](CORTEX_MYSQL_HANDOVER_REPORT.md) | Capital Cortex: MySQL 8.4 Handover Report |
| 2026-11-08 | [CORTEX_MYSQL_PUSHED_CODE_FINAL_AUDIT.md](CORTEX_MYSQL_PUSHED_CODE_FINAL_AUDIT.md) | Capital Cortex: PostgreSQL to MySQL Pushed-Code Final Audit |
| 2026-11-08 | [CORTEX_MYSQL_REMEDIATION_REPORT.md](CORTEX_MYSQL_REMEDIATION_REPORT.md) | Capital Cortex: MySQL 8.4 Remediation Report |
