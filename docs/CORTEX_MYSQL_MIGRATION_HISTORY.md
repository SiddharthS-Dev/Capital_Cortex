# Capital Cortex: PostgreSQL to MySQL 8.4 Migration History

How the migration from PostgreSQL 16 (with Apache AGE and pgvector) to MySQL 8.4 progressed, and where each part is
documented. Current behaviour is described by the documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`; the dated
reports listed here are kept in `docs/archive/migration-history/` as historical records. Dates and titles below are
taken from the reports themselves. **Production cutover has not happened.**

## Where each topic is documented

| Topic | Current document | Historical reports |
|---|---|---|
| Original PostgreSQL architecture | `docs/DECISIONS.md` (D-100) | [Database architecture report](archive/migration-history/CORTEX_DATABASE_ARCHITECTURE_REPORT.md), [baseline inventory](archive/migration-history/CORTEX_MYSQL_MIGRATION_BASELINE_INVENTORY.md) |
| Feasibility and plan | `docs/CORTEX_ARCHITECTURE_DECISION_REGISTER.md` | [Feasibility](archive/migration-history/CORTEX_MYSQL_MIGRATION_FEASIBILITY_REPORT.md), [implementation plan](archive/migration-history/CORTEX_MYSQL_MIGRATION_IMPLEMENTATION_PLAN.md), [verification](archive/migration-history/CORTEX_MYSQL_MIGRATION_VERIFICATION_REPORT.md) |
| MySQL 8.4 target schema and type mapping | `docs/CORTEX_MYSQL_DATABASE_DESIGN.md`, `scripts/schema_mysql.sql` | [Schema mapping](archive/migration-history/CORTEX_MYSQL_SCHEMA_MAPPING.md), [phase 3](archive/migration-history/CORTEX_MYSQL_PHASE3_EXECUTION_REPORT.md) |
| SQL dialect changes and backend modules | `docs/CORTEX_POSTGRESQL_DEPENDENCY_CLOSURE.md`, `docs/CORTEX_MYSQL_COMPATIBILITY_AUDIT.md` | [Phase 7](archive/migration-history/CORTEX_MYSQL_PHASE7_EXECUTION_REPORT.md), [pushed-code audit](archive/migration-history/CORTEX_MYSQL_PUSHED_CODE_FINAL_AUDIT.md) |
| Alembic migrations | `docs/CORTEX_MYSQL_DATABASE_DESIGN.md` (migration history) | [Migration safety reports](archive/migration-history/CORTEX_MYSQL_REMEDIATION_REPORT.md) |
| Graph and vector storage | `docs/CORTEX_MYSQL_DATABASE_DESIGN.md` | [Phase 4](archive/migration-history/CORTEX_MYSQL_PHASE4_EXECUTION_REPORT.md), [phase 5](archive/migration-history/CORTEX_MYSQL_PHASE5_EXECUTION_REPORT.md) |
| Database triggers and invariants | `docs/CORTEX_MYSQL_DATABASE_DESIGN.md` | [Phase 6](archive/migration-history/CORTEX_MYSQL_PHASE6_EXECUTION_REPORT.md) |
| API and frontend | `docs/API.md`, `docs/openapi.json` | [Integration progress](archive/migration-history/CORTEX_MYSQL_INTEGRATION_PROGRESS.md), [E2E root cause](archive/migration-history/CORTEX_E2E_ROOT_CAUSE_REPORT.md) |
| Ingestion and source registry | `docs/DECISIONS.md` (D-034) | [Blocker closure register](archive/migration-history/CORTEX_MYSQL_BLOCKER_CLOSURE_REGISTER.md) |
| Data migration and reconciliation | `CORTEX_MYSQL_CUTOVER_RUNBOOK.md`, `docs/CORTEX_MYSQL_MIGRATION_SAFETY_VERIFICATION.md` | [Phase 14 rehearsal](archive/migration-history/CORTEX_MYSQL_PHASE14_REHEARSAL_REPORT.md) |
| Security and authentication | `docs/CORTEX_MYSQL_SECURITY_READINESS.md`, `docs/SECURITY_CREDENTIAL_ROTATION_RUNBOOK.md` | [Phase 8 (Keycloak)](archive/migration-history/CORTEX_MYSQL_PHASE8_EXECUTION_REPORT.md), [enterprise security](archive/migration-history/CORTEX_ENTERPRISE_SECURITY_IMPLEMENTATION_REPORT.md) |
| Docker and infrastructure | `docs/RUNBOOK.md`, `infra/docker-compose.mysql.yml` | [Phase 2](archive/migration-history/CORTEX_MYSQL_PHASE2_EXECUTION_REPORT.md), [phase 13](archive/migration-history/CORTEX_MYSQL_PHASE13_VERIFICATION_REPORT.md) |
| Testing and validation | `docs/CORTEX_MYSQL_TEST_EVIDENCE.md`, `docs/CORTEX_MYSQL_EVIDENCE_INDEX.md` | [Test case evidence](archive/migration-history/CORTEX_MYSQL_TEST_CASE_EVIDENCE_2026-11-07.md), [final test report](archive/migration-history/CORTEX_MYSQL_FINAL_TEST_REPORT.md) |
| Performance | `docs/CORTEX_MYSQL_PERFORMANCE_REPORT.md`, `docs/CORTEX_PERFORMANCE_AUDIT.md` | — |
| Backup and restore | `docs/RUNBOOK.md` section 8.0 | [B1 backup readiness](archive/migration-history/CORTEX_B1_BACKUP_READINESS_REPORT.md) |
| Rollback | `docs/CORTEX_MYSQL_ROLLBACK_RUNBOOK.md` | — |
| Production readiness, deployment and cutover | `docs/CORTEX_PRODUCTION_MIGRATION_ACTION_PLAN.md`, `docs/CORTEX_MYSQL_PRODUCTION_MIGRATION_RUNBOOK.md`, `docs/CORTEX_PRODUCTION_READINESS_CHECKLIST.md` | [B2](archive/migration-history/CORTEX_B2_PRODUCTION_ACCESS_REPORT.md), [B3](archive/migration-history/CORTEX_B3_CUTOVER_READINESS_REPORT.md), [discovery](archive/migration-history/CORTEX_PRODUCTION_DB_DISCOVERY_REPORT.md) |
| Open items | `docs/CORTEX_MYSQL_BLOCKER_REGISTER.md` | [Earlier registers](archive/migration-history/CORTEX_MYSQL_FINAL_BLOCKER_REGISTER_2026-11-07.md) |

## Timeline of the reports

| Date | Report |
|---|---|
| 2026-10-26 | [Cortex MySQL Migration: Comprehensive Baseline Inventory Report](archive/migration-history/CORTEX_MYSQL_MIGRATION_BASELINE_INVENTORY.md) |
| 2026-10-26 | [Cortex PostgreSQL-to-MySQL Migration Feasibility Analysis Report](archive/migration-history/CORTEX_MYSQL_MIGRATION_FEASIBILITY_REPORT.md) |
| 2026-10-26 | [Cortex PostgreSQL-to-MySQL Migration Implementation Plan](archive/migration-history/CORTEX_MYSQL_MIGRATION_IMPLEMENTATION_PLAN.md) |
| 2026-10-26 | [Cortex PostgreSQL-to-MySQL Migration Verification & Readiness Report](archive/migration-history/CORTEX_MYSQL_MIGRATION_VERIFICATION_REPORT.md) |
| 2026-10-26 | [Cortex PostgreSQL to MySQL 8.4 Schema Mapping Specification](archive/migration-history/CORTEX_MYSQL_SCHEMA_MAPPING.md) |
| 2026-10-27 | [Cortex PostgreSQL-to-MySQL Migration — Phase 4 Execution Report: Graph Subsystem Migration](archive/migration-history/CORTEX_MYSQL_PHASE4_EXECUTION_REPORT.md) |
| 2026-10-27 | [Cortex PostgreSQL-to-MySQL Migration — Phase 5 Execution Report: Vector Subsystem Migration](archive/migration-history/CORTEX_MYSQL_PHASE5_EXECUTION_REPORT.md) |
| 2026-10-27 | [Cortex PostgreSQL-to-MySQL Migration — Phase 6 Execution Report: Triggers, Invariants, and Mutex Migration](archive/migration-history/CORTEX_MYSQL_PHASE6_EXECUTION_REPORT.md) |
| 2026-10-27 | [Cortex MySQL Migration — Phase 7: Application SQL Sanitization Across API Routers and Core Services](archive/migration-history/CORTEX_MYSQL_PHASE7_EXECUTION_REPORT.md) |
| 2026-10-29 | [Capital Cortex — Phase 13: MySQL 8.4 End-to-End Deployment Verification Report](archive/migration-history/CORTEX_MYSQL_PHASE13_VERIFICATION_REPORT.md) |
| 2026-10-29 | [Inspironics MERIS — Capital Cortex™](archive/migration-history/CORTEX_MYSQL_PHASES_9_12_EXECUTION_REPORT.md) |
| 2026-10-30 | [Capital Cortex — MySQL 8.4 Migration: Current State & Remaining Work](archive/migration-history/CORTEX_MYSQL_CURRENT_STATE_AND_REMAINING_WORK_REPORT.md) |
| 2026-10-30 | [Capital Cortex — MySQL 8.4 Final Implementation Report](archive/migration-history/CORTEX_MYSQL_FINAL_IMPLEMENTATION_REPORT.md) |
| 2026-10-30 | [Capital Cortex — MySQL 8.4 Final Readiness Report](archive/migration-history/CORTEX_MYSQL_FINAL_READINESS_REPORT.md) |
| 2026-10-30 | [Capital Cortex — MySQL 8.4 Final Test Report](archive/migration-history/CORTEX_MYSQL_FINAL_TEST_REPORT.md) |
| 2026-10-30 | [Capital Cortex — MySQL Integration Suite Progress](archive/migration-history/CORTEX_MYSQL_INTEGRATION_PROGRESS.md) |
| 2026-10-30 | [Capital Cortex on MySQL 8.4 — Live Demo Guide](archive/migration-history/CORTEX_MYSQL_LIVE_DEMO_GUIDE.md) |
| 2026-10-30 | [Capital Cortex — Phase 14: Full ETL Rehearsal, Data Reconciliation & Cutover Readiness Report](archive/migration-history/CORTEX_MYSQL_PHASE14_REHEARSAL_REPORT.md) |
| 2026-10-31 | [Capital Cortex — MySQL 8.4 Blocker Closure Report](archive/migration-history/CORTEX_MYSQL_BLOCKER_CLOSURE_REPORT.md) |
| 2026-10-31 | [Capital Cortex — Git Review Before Committing the MySQL Work](archive/migration-history/CORTEX_MYSQL_GIT_REVIEW_REPORT.md) |
| 2026-11-02 | [B1 — Production PostgreSQL Backup Readiness](archive/migration-history/CORTEX_B1_BACKUP_READINESS_REPORT.md) |
| 2026-11-02 | [B2 — Production PostgreSQL Access](archive/migration-history/CORTEX_B2_PRODUCTION_ACCESS_REPORT.md) |
| 2026-11-02 | [B3 — Production Cutover Readiness](archive/migration-history/CORTEX_B3_CUTOVER_READINESS_REPORT.md) |
| 2026-11-02 | [Capital Cortex — Database Architecture Report

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

"ON DELETE RESTRICT (default)" means no clause was declared, which InnoDB applies as NO ACTION. Migration history gives the first MySQL revision that names the table and the PostgreSQL revision that created it.](archive/migration-history/CORTEX_DATABASE_ARCHITECTURE_REPORT.md) |
| 2026-11-02 | [Capital Cortex — MySQL Migration Status](archive/migration-history/CORTEX_MYSQL_FINAL_STATUS_SUMMARY.md) |
| 2026-11-02 | [Capital Cortex — Production Database Discovery Report](archive/migration-history/CORTEX_PRODUCTION_DB_DISCOVERY_REPORT.md) |
| 2026-11-03 | [Capital Cortex: Enterprise Security Implementation Report](archive/migration-history/CORTEX_ENTERPRISE_SECURITY_IMPLEMENTATION_REPORT.md) |
| 2026-11-03 | [Capital Cortex — MySQL Migration Blocker Register](archive/migration-history/CORTEX_MYSQL_BLOCKER_REGISTER_2026-11-03.md) |
| 2026-11-03 | [Capital Cortex — MySQL Migration Blocker Resolution Report](archive/migration-history/CORTEX_MYSQL_BLOCKER_RESOLUTION_REPORT.md) |
| 2026-11-03 | [Cortex PostgreSQL-to-MySQL Migration — Phase 2 Execution Report: Isolated Test Environment Setup](archive/migration-history/CORTEX_MYSQL_PHASE2_EXECUTION_REPORT.md) |
| 2026-11-03 | [Cortex PostgreSQL-to-MySQL Migration — Phase 3 Execution Report: Database Driver & Connection Session Plumbing](archive/migration-history/CORTEX_MYSQL_PHASE3_EXECUTION_REPORT.md) |
| 2026-11-03 | [Cortex PostgreSQL-to-MySQL Migration — Phase 8 Execution Report: Keycloak Database Migration Scope](archive/migration-history/CORTEX_MYSQL_PHASE8_EXECUTION_REPORT.md) |
| 2026-11-03 | [Capital Cortex: Test Execution Report](archive/migration-history/CORTEX_TEST_EXECUTION_REPORT.md) |
| 2026-11-04 | [Capital Cortex: E2E Panel Timeouts — Root Cause Report](archive/migration-history/CORTEX_E2E_ROOT_CAUSE_REPORT.md) |
| 2026-11-04 | [Capital Cortex: MySQL Migration Blocker Closure Register](archive/migration-history/CORTEX_MYSQL_BLOCKER_CLOSURE_REGISTER.md) |
| 2026-11-04 | [Capital Cortex: Complete Open Blocker Audit (PostgreSQL 16 → MySQL 8.4)](archive/migration-history/CORTEX_MYSQL_COMPLETE_OPEN_BLOCKER_AUDIT.md) |
| 2026-11-04 | [Capital Cortex: MySQL 8.4 Migration — Final Completion Report](archive/migration-history/CORTEX_MYSQL_FINAL_COMPLETION_REPORT.md) |
| 2026-11-04 | [Capital Cortex: MySQL Integration Suite — Root Cause Report](archive/migration-history/CORTEX_MYSQL_INTEGRATION_ROOT_CAUSE_REPORT.md) |
| 2026-11-04 | [Capital Cortex: MySQL Production Readiness Report](archive/migration-history/CORTEX_MYSQL_PRODUCTION_READINESS_REPORT.md) |
| 2026-11-05 | [Capital Cortex — MySQL Migration Status, 2026-11-05](archive/migration-history/CORTEX_MYSQL_STATUS_REPORT_2026-11-05.md) |
| 2026-11-07 | [Capital Cortex: MySQL Migration Final Acceptance Report](archive/migration-history/CORTEX_MYSQL_FINAL_ACCEPTANCE_REPORT.md) |
| 2026-11-07 | [Capital Cortex — MySQL 8.4 Final Blocker Register, 2026-11-07](archive/migration-history/CORTEX_MYSQL_FINAL_BLOCKER_REGISTER_2026-11-07.md) |
| 2026-11-07 | [Capital Cortex: MySQL 8.4 Migration, Final Execution Plan](archive/migration-history/CORTEX_MYSQL_FINAL_EXECUTION_PLAN.md) |
| 2026-11-07 | [Capital Cortex — PostgreSQL 16 → MySQL 8.4 Technical Proof Report, 2026-11-07](archive/migration-history/CORTEX_MYSQL_FINAL_TECHNICAL_PROOF_REPORT_2026-11-07.md) |
| 2026-11-07 | [Capital Cortex — MySQL Migration Test Completion, 2026-11-07](archive/migration-history/CORTEX_MYSQL_STATUS_REPORT_2026-11-07.md) |
| 2026-11-07 | [Capital Cortex — MySQL 8.4 Migration: Handover Summary (2026-11-07)](archive/migration-history/CORTEX_MYSQL_TEAMS_HANDOVER_SUMMARY_2026-11-07.md) |
| 2026-11-07 | [Capital Cortex — MySQL 8.4 Test Case Evidence, 2026-11-07](archive/migration-history/CORTEX_MYSQL_TEST_CASE_EVIDENCE_2026-11-07.md) |
| 2026-11-08 | [Capital Cortex: MySQL 8.4 Handover Report](archive/migration-history/CORTEX_MYSQL_HANDOVER_REPORT.md) |
| 2026-11-08 | [Capital Cortex: PostgreSQL to MySQL Pushed-Code Final Audit](archive/migration-history/CORTEX_MYSQL_PUSHED_CODE_FINAL_AUDIT.md) |
| 2026-11-08 | [Capital Cortex: MySQL 8.4 Remediation Report](archive/migration-history/CORTEX_MYSQL_REMEDIATION_REPORT.md) |

Reports without a date in their text are listed by the date their file was last saved.

## Outcome so far

- On 2026-11-07 the final acceptance report recorded the migration as not accepted, pending external owners
  ([report](archive/migration-history/CORTEX_MYSQL_FINAL_ACCEPTANCE_REPORT.md)).
- On 2026-11-08 the remaining code findings from the pushed-code audit were remediated
  ([remediation report](archive/migration-history/CORTEX_MYSQL_REMEDIATION_REPORT.md)).
- On 2026-11-09 the migration was committed as 60 reviewable commits on `feature/changes-login` and pushed to GitHub.
- Still open: the production blockers B1 to B3, PERF-1 and the other items in `docs/CORTEX_MYSQL_BLOCKER_REGISTER.md`.
