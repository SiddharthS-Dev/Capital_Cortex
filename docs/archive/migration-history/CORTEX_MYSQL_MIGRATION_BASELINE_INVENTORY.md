# Cortex MySQL Migration: Comprehensive Baseline Inventory Report

> **Historical record (undated; file last saved 2026-10-26).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


**Document ID:** CRTX-BASE-MYSQL-2026-001  
**Project:** Inspironics MERIS — Capital Cortex™ Module  
**Source Platform:** PostgreSQL 16.x (Apache AGE 1.5.0, pgvector 0.8.0, pg_trgm, pgcrypto)  
**Target Platform:** MySQL 8.4 Community Edition (InnoDB, `utf8mb4_0900_ai_ci`)  
**Created Date:** October 2026  
**Status:** Baseline Established & Verified (Phase 0 Complete)  

---

## 1. Executive Summary

This inventory establishes the verified baseline of all database dependencies, schema objects, raw SQL queries, graph operations, vector retrieval workflows, and operational configurations in the Capital Cortex module. It serves as the authoritative blueprint for executing the safe, complete migration to MySQL 8.4 Community Edition without data loss or feature degradation.

### Key Metrics Summary
- **Relational Tables:** 50 tables (48 domain tables + 2 graph mirror tables: `entity` and `relationship_edge`).
- **ORM Models:** 0 (100% of data access is raw SQL via `session.execute(text(...))`).
- **Raw SQL Queries Across Repository:** >250 distinct queries across 21 routers, 8 pipeline layers, 12 background jobs, and test suites.
- **`RETURNING` Clauses:** 60+ occurrences requiring UUID client-side pre-generation.
- **`CAST(... AS uuid)` and `::uuid`:** 110+ occurrences requiring transition to string-bound parameters matching `VARCHAR(36)`.
- **`ON CONFLICT` Clauses:** 25+ occurrences requiring translation to `ON DUPLICATE KEY UPDATE` or pre-check.
- **Array Columns (`text[]`, `uuid[]`):** 16 columns across 11 tables requiring conversion to MySQL `JSON` columns.
- **Array Operations (`= ANY(...)`, `&&`, `unnest`, `cardinality`):** 40+ occurrences requiring translation to `IN (...)`, `JSON_OVERLAPS()`, `JSON_TABLE()`, and `JSON_LENGTH()`.
- **`NULLS LAST` / `NULLS FIRST`:** 18 occurrences requiring translation to `ORDER BY (col IS NULL) ASC, col DESC`.
- **`GROUPING SETS`:** 2 queries (`pipeline_engine.py` and `opportunities.py`) requiring translation.
- **Full-Text Search (`tsvector`, `@@`, `websearch_to_tsquery`):** 2 operational query locations (`copilot.py` and `opportunities.py`).
- **Advisory Locks (`pg_advisory_xact_lock`):** 1 location (`platform_core/audit/chain.py`) requiring replacement with a dedicated row-level lock (`audit_lock`).
- **Apache AGE Dependencies:** 4 files (`platform_core/db/age.py`, `cortex/l2_representation/graph_writer.py`, `cortex/l2_representation/graph_traversal.py`, `cortex/l8_actuation/api/routers/graph.py`).
- **pgvector Dependencies:** 3 files (`platform_core/db/vector.py`, `cortex/l2_representation/pipeline.py`, `cortex/l5_strategy/copilot.py`).
- **Identity Provider:** Keycloak 26 connected to PostgreSQL via JDBC.

---

## 2. Architecture & Database Engine Baseline

### 2.1 Engine Initialization & Connection Pooling
- **File:** `platform_core/db/session.py`
- **Current Driver:** `psycopg[binary]>=3.2.3` via `postgresql+psycopg://...`
- **Configuration:** `create_async_engine(s.database_url, pool_size=10, max_overflow=20, pool_pre_ping=True)`
- **Session Management:** `async_sessionmaker(expire_on_commit=False)` with transaction helper `session_scope()` using `async with session.begin(): yield session`.
- **Settings Source:** `platform_core/config/settings.py` (`database_url: str = "postgresql+psycopg://..."`).
- **Migration Strategy:**
  - Add `asyncmy>=0.2.9` and `pymysql>=1.1.1` to dependencies.
  - Update `get_engine()` to support `mysql+asyncmy://...` with `pool_recycle=3600`, `pool_pre_ping=True`.
  - Maintain identical transaction boundary semantics (`session_scope()` and FastAPI `Depends(get_session, scope="function")`).

### 2.2 Migrations Engine
- **File:** `migrations/env.py`, `alembic.ini`
- **Current Behavior:** Converts `DATABASE_URL` synchronous dialect from `+asyncpg` to `+psycopg` for offline/online migrations.
- **Migration Strategy:**
  - Update `_url()` in `migrations/env.py` to support `mysql+pymysql://` for synchronous Alembic operations.
  - Provide dedicated MySQL migration scripts or dialect-aware migrations.

---

## 3. Complete Schema Inventory (50 Tables)

All tables inherit common columns: `id (UUID/VARCHAR(36))`, `org_id (UUID/VARCHAR(36))`, `created_at (TIMESTAMP)`, `updated_at (TIMESTAMP)`, `is_demo (BOOLEAN)`.

| # | Table Name | Source Migration | Core Business Function | Special Types / Constraints | Knowledge Table (I1) |
|---|---|---|---|---|:---:|
| 1 | `tenant` | 0001 | Platform organization tenancy | `id PRIMARY KEY` | No |
| 2 | `inference` | 0001 | Declared AI/rule inferences | `basis_refs jsonb NOT NULL` | No |
| 3 | `source` | 0001, 0002 | Data ingestion adapters | `config jsonb`, unique adapter key | No |
| 4 | `source_run` | 0002 | Ingestion execution history | Ingestion stats counters | No |
| 5 | `signal` | 0001 | Raw & normalized ingested signals | `raw jsonb`, `content_hash` | Yes |
| 6 | `organization` | 0001, 0002 | Companies, institutions, agencies | `sectors text[]`, `profile jsonb` | Yes |
| 7 | `entity_merge_candidate` | 0002 | Deduplication review queue | Pair unique constraint on IDs | No |
| 8 | `investor` | 0001 | Investor profiles & criteria | `stages text[]`, `geos text[]` | Yes |
| 9 | `fund` | 0001 | Venture/PE funds | Vintage, target fund size | Yes |
| 10 | `grant_program` | 0001 | Government/foundation grant programs | `eligibility jsonb`, deadlines | Yes |
| 11 | `financial_instrument` | 0001 | 11 capital instrument definitions | `class capital_class`, `terms jsonb` | Yes |
| 12 | `scoring_profile` | 0001 | Multi-factor weighting configurations | `weights jsonb`, `thresholds jsonb` | No |
| 13 | `opportunity` | 0001, 0002 | Core capital fundraising opportunities | `class capital_class`, `pipeline_stage`, `geography text[]`, `factors jsonb`, `search tsvector` | Yes |
| 14 | `contact` | 0001, 0003 | Individuals and stakeholders | `emails text[]`, consent tracking | Yes |
| 15 | `meeting` | 0001 | Interactions & meetings | `contact_ids uuid[]`, `commitments jsonb` | Yes |
| 16 | `relationship` | 0001, 0003 | Bounded relationships between nodes | Pair unique constraint, history JSON | Yes |
| 17 | `interaction` | 0003 | Detailed communications / touchpoints | `weight`, `direction`, `external_id` | Yes |
| 18 | `milestone` | 0001, 0003 | Deadlines & action items | `due_at`, status lifecycle | Yes |
| 19 | `document` | 0001, 0004 | Data room files and artifacts | `classification`, `dd_tags text[]`, `legal_hold` | Yes |
| 20 | `document_access` | 0004 | Document view/download audit logs | Action, actor, detail JSON | No |
| 21 | `dataroom_package` | 0004 | Curated document bundles | `document_ids uuid[]`, manifest JSON | No |
| 22 | `share_link` | 0004 | External secure data room share links | Token hash, expiration lifecycle | No |
| 23 | `proposal` | 0001, 0004 | Term sheets & applications | `sections jsonb`, `artefacts text[]` | Yes |
| 24 | `proposal_version` | 0004 | Proposal snapshot history | Content hash, version counter | No |
| 25 | `proposal_export` | 0004 | Generated documents (docx/pdf/etc) | Storage key, SHA-256 checksum | No |
| 26 | `board_report` | 0004 | Quarterly/monthly board packets | `recipients text[]`, distribution JSON | No |
| 27 | `factor_history` | 0004 | ML scoring input feature logs | Opportunity factors snapshot | No |
| 28 | `agent_run` | 0001, 0003 | Council agent execution logs | Tokens, cost, trace, input JSON | No |
| 29 | `recommendation` | 0001, 0003 | Governed agent recommendations | `evidence jsonb`, `reasoning jsonb` | Yes |
| 30 | `approval` | 0001, 0003 | Human-in-the-loop governance gates | Content hash, token, required votes | No |
| 31 | `approval_decision` | 0003 | Individual approver votes/records | `roles text[]`, `grants text[]`, MFA flag | No |
| 32 | `outbox` | 0001, 0003 | Governed actuation outbox | `payload jsonb`, immutability trigger | No |
| 33 | `alert_rule` | 0001 | Automation alert configurations | `rule_expr jsonb`, `channels text[]` | No |
| 34 | `alert` | 0001 | Active and resolved system alerts | Severity, snoozed lifecycle | Yes |
| 35 | `alert_delivery` | 0003 | Multi-channel delivery attempts | Channel, recipient, attempt count | No |
| 36 | `financial_snapshot` | 0001 | Periodic cash, revenue, burn metrics | Unique per period and org | Yes |
| 37 | `forecast` | 0001 | Runway and zero-cash projections | `series jsonb`, `assumptions jsonb` | Yes |
| 38 | `outcome` | 0001 | Won/lost deal tracking | Outcome classification, amount | Yes |
| 39 | `ml_model` | 0003 | Scorer weights & training metadata | Metrics JSON, training parameters | No |
| 40 | `memory` | 0001, 0003 | Warm/cold agent reflection memory | Key, value JSON, expiration | Yes |
| 41 | `legal_hold` | 0004 | Regulatory preservation locks | Target table & ID, release tracking | No |
| 42 | `retention_run` | 0004 | Data cleanup audit history | Purged row counts, retention policy | No |
| 43 | `setting` | 0004 | Dynamic administrative settings | Key-value settings with version | No |
| 44 | `api_idempotency` | 0001 | API duplicate request prevention | Unique (org_id, principal, key) | No |
| 45 | `embedding` | 0001 | pgvector embedding storage | `vector vector(1024)`, chunk_index | No |
| 46 | `entity` | 0001 | CKG relational mirror vertices | `attrs jsonb`, `entity_type`, `ref_id` | Yes |
| 47 | `relationship_edge` | 0001, 0002 | CKG relational mirror edges | `from_entity`, `to_entity`, `type`, `weight` | Yes |
| 48 | `audit_log` | 0001 | Cryptographic SHA-256 hash chain | `prev_hash`, `hash`, append-only trigger | No |
| 49 | `audit_lock` *(new)* | Target | Mutex for atomic audit log appends | Single-row table with `FOR UPDATE` | No |
| 50 | `alembic_version` | Infra | Schema version tracking | `version_num VARCHAR(32)` | No |

---

## 4. PostgreSQL-Specific SQL Constructs & Migration Strategies

### 4.1 `RETURNING` Elimination (60+ occurrences)
- **Problem:** MySQL 8.4 does not support `INSERT ... RETURNING id` or `UPDATE ... RETURNING ...`.
- **Strategy:**
  1. For `INSERT`: Client-side UUID pre-generation in Python (`id = str(uuid.uuid4())`) before executing `INSERT INTO ... (id, ...)`.
  2. For `UPDATE ... RETURNING`: Perform follow-up `SELECT` query within the same transaction or check `cursor.rowcount`.
- **Key Affected Files:**
  - `cortex/l2_representation/graph_writer.py`
  - `cortex/l7_governance/outbox.py`, `approval_service.py`, `drafts.py`, `retention.py`, `settings_service.py`
  - `cortex/l8_actuation/proposals.py`, `proposal_builder.py`, `dataroom.py`, `board_reports.py`, `alerts.py`
  - `cortex/l6_agency/orchestrator.py`, `agent_runtime.py`
  - `cortex/l3_memory/relationship_service.py`, `memory_manager.py`
  - `cortex/l8_actuation/api/routers/*.py` (all 21 routers)

### 4.2 `CAST(... AS uuid)` and `::uuid` Removal (110+ occurrences)
- **Problem:** MySQL does not support the `uuid` data type or `CAST(expr AS uuid)`.
- **Strategy:**
  - Store UUIDs as `VARCHAR(36)` in MySQL.
  - Bind parameters directly as string `:id` or `:ids`. Remove `CAST(:id AS uuid)` completely from all SQL strings.

### 4.3 `ON CONFLICT` Translation (25+ occurrences)
- **Problem:** MySQL uses `INSERT INTO ... ON DUPLICATE KEY UPDATE` instead of PostgreSQL's `ON CONFLICT (...) DO UPDATE / DO NOTHING`.
- **Strategy:**
  - `ON CONFLICT (col1, col2) DO NOTHING` $\rightarrow$ `INSERT IGNORE INTO ...` or `ON DUPLICATE KEY UPDATE col1 = col1`.
  - `ON CONFLICT (col1, col2) DO UPDATE SET col3 = EXCLUDED.col3` $\rightarrow$ `ON DUPLICATE KEY UPDATE col3 = VALUES(col3)`.
  - Conditional unique indexes (e.g. `WHERE external_key IS NOT NULL`) are emulated via virtual generated columns or standard MySQL nullable unique constraints.

### 4.4 PostgreSQL Native Arrays (`text[]`, `uuid[]`)
- **Problem:** MySQL 8.4 does not support array types.
- **Strategy:**
  - Store as `JSON` columns in MySQL with default `'[]'`.
  - Replace `= ANY(:param)` with `col IN (:params)` (using expanding SQLAlchemy parameters).
  - Replace `&&` (array overlap) with `JSON_OVERLAPS(col, CAST(:param AS JSON))`.
  - Replace `unnest(col)` with `JOIN JSON_TABLE(col, '$[*]' COLUMNS (val VARCHAR(255) PATH '$')) jt`.
  - Replace `cardinality(col)` with `JSON_LENGTH(col)`.

### 4.5 Sorting: `NULLS LAST` and `NULLS FIRST` (18 occurrences)
- **Problem:** MySQL does not support `NULLS LAST` / `NULLS FIRST` in `ORDER BY`.
- **Strategy:**
  - `ORDER BY col DESC NULLS LAST` $\rightarrow$ `ORDER BY (col IS NULL) ASC, col DESC`.
  - `ORDER BY col ASC NULLS LAST` $\rightarrow$ `ORDER BY (col IS NULL) ASC, col ASC`.

### 4.6 Grouping Sets Aggregations
- **Problem:** `pipeline_engine.py:47` and `opportunities.py:155` use `GROUP BY GROUPING SETS (...)`.
- **Strategy:**
  - Replace with structured `UNION ALL` rollups or `GROUP BY ... WITH ROLLUP` with post-aggregation handling.

### 4.7 Full-Text Search
- **Problem:** PostgreSQL uses `tsvector`, `to_tsvector()`, `websearch_to_tsquery()`, and `@@`.
- **Strategy:**
  - In MySQL, define `FULLTEXT(title, description)` indexes and query via `MATCH(title, description) AGAINST (:q IN BOOLEAN MODE)` or fallback to `LIKE :q`.

### 4.8 Concurrency & Advisory Locks
- **Problem:** `platform_core/audit/chain.py` uses `SELECT pg_advisory_xact_lock(:k)` to serialize SHA-256 hash chaining.
- **Strategy:**
  - Create table `audit_lock (id INT PRIMARY KEY, dummy TINYINT)` with initial row `(1, 1)`.
  - Replace advisory lock query with: `SELECT id FROM audit_lock WHERE id = 1 FOR UPDATE`. This guarantees transaction-scoped mutex locking that automatically releases on commit or rollback.

---

## 5. Subsystem-Specific Inventories

### 5.1 Graph Subsystem (CKG)
- **Current State:** Dual-writes to Apache AGE (`ckg` graph) and MySQL-compatible relational mirror tables (`entity` and `relationship_edge`).
- **Dependencies Identified:**
  - `platform_core/db/age.py`: Apache AGE driver & Cypher execution.
  - `cortex/l2_representation/graph_writer.py`: calls `age.cypher()`, `upsert_vertex()`, `upsert_edge()`.
  - `cortex/l2_representation/graph_traversal.py`: queries AGE catalog tables `ckg._ag_label_vertex` and `ckg._ag_label_edge`.
  - `cortex/l8_actuation/api/routers/graph.py`: routes `neighbourhood`, `provenance`, `paths`, `stats`, and raw `cypher`.
- **Migration Scope:**
  - Decommission `age.py` calls.
  - Rewrite `graph_traversal.py` to query `entity` and `relationship_edge` directly using bidirectional BFS.
  - Rewrite `graph.py` `/v1/graph/stats` to aggregate from `entity` and `relationship_edge`.
  - Replace `/v1/graph/query?template=provenance` with recursive traversal over `relationship_edge`.
  - Deprecate `/v1/graph/query?template=cypher` in favor of structured templates.

### 5.2 Vector Subsystem & AI Retrieval
- **Current State:** 1024-dimensional float32 embeddings (`hash-tf-1024-v1`) generated in Python via deterministic Blake2b hashing (`platform_core/embeddings.py`).
- **pgvector Dependency:** `vector(1024)` column in `embedding` table; cosine distance operator `<=>` queried exclusively in `cortex/l5_strategy/copilot.py:91`.
- **Migration Scope:**
  - Store vector as binary float32 buffer (`VARBINARY(4096)` or `BLOB`) in MySQL `embedding` table.
  - Use `platform_core/embeddings.py` `cosine(a, b)` and `scikit-learn` in-memory NearestNeighbors for similarity ranking.
  - Preserve exact numerical results ($10^{-5}$ tolerance) without adding external vector database sidecars.

### 5.3 Authentication & Keycloak Integration
- **Current State:** Keycloak 26 connected to PostgreSQL (`jdbc:postgresql://postgres:5432/keycloak`).
- **Migration Scope:**
  - Reconfigure Keycloak to use MySQL (`KC_DB: mysql`, `KC_DB_URL: jdbc:mysql://mysql:3306/keycloak`).
  - Pre-create database `keycloak` in MySQL with proper character set (`utf8mb4`).
  - Retain existing realm configuration (`infra/keycloak/realm-cortex.json`).

---

## 6. Complete API Router Inventory (21 Routers)

All 21 routers located in `cortex/l8_actuation/api/routers/` have been surveyed for PostgreSQL constructs:

| # | Router Module | Route Prefix | Key PostgreSQL Constructs to Remediate |
|---|---|---|---|
| 1 | `opportunities.py` | `/v1/opportunities` | `GROUPING SETS`, `unnest(geography)`, `&&`, `ILIKE`, `NULLS LAST`, `tsvector @@` |
| 2 | `entities.py` | `/v1/entities` | `RETURNING id`, `CAST(:ids AS uuid[])`, `ON CONFLICT DO NOTHING` |
| 3 | `graph.py` | `/v1/graph` | AGE catalog queries, Cypher template, `SET LOCAL statement_timeout` |
| 4 | `scoring.py` | `/v1/scoring` | `NULLS LAST`, `CAST(:id AS uuid)`, JSON payload extraction |
| 5 | `pipeline.py` | `/v1/pipeline` | Pipeline aggregation queries, stage casts |
| 6 | `dashboards.py` | `/v1/dashboards` | `unnest(geography)`, `interval '30 days'`, `NULLS LAST` |
| 7 | `agents.py` | `/v1/agents` | `RETURNING id`, `CAST(:inp AS jsonb)`, status filters |
| 8 | `proposals.py` | `/v1/proposals` | `RETURNING id`, `CAST(:opp AS uuid)`, `CAST(:ids AS uuid[])` |
| 9 | `dataroom.py` | `/v1/dataroom` | `RETURNING id`, `cardinality()`, `CAST(:ids AS uuid[])`, `ILIKE` |
| 10 | `board_reports.py` | `/v1/board-reports` | `RETURNING id`, `CAST(:ids AS uuid[])`, `NULLS LAST` |
| 11 | `alerts.py` | `/v1/alerts` | `RETURNING id`, `cardinality()`, `ON CONFLICT (org_id, name)` |
| 12 | `approvals.py` | `/v1/approvals` | `RETURNING id`, `NULLS LAST`, `FOR UPDATE` locking |
| 13 | `relationships.py` | `/v1/relationships` | `ILIKE`, `NULLS LAST`, `m.contact_ids` array matching |
| 14 | `settings.py` | `/v1/settings` | `ON CONFLICT (org_id, key) DO UPDATE`, `RETURNING version` |
| 15 | `admin.py` | `/v1/admin` | Keycloak user sync & admin role assignments |
| 16 | `sources.py` | `/v1/sources` | Ingestion run tracking, `ON CONFLICT` adapter updates |
| 17 | `signals.py` | `/v1/signals` | `content_hash` unique constraints, raw JSON storage |
| 18 | `documents.py` | `/v1/documents` | Storage keys, tag indexing, access logging |
| 19 | `outcomes.py` | `/v1/outcomes` | Result classification, deal outcome reporting |
| 20 | `audit.py` | `/v1/audit` | Audit log reading, SHA-256 chain verification |
| 21 | `feed.py` | `/v1/feed` | Signal RSS/Atom feed polling and normalization |

---

## 7. Operational Scripts & Docker Compose Inventory

| File / Component | Current PostgreSQL Dependency | Target MySQL Architecture |
|---|---|---|
| `infra/docker-compose.yml` | `capital-cortex/postgres:16-age1.5.0-pgvector0.8.0` | `mysql:8.4` Community container with InnoDB buffer pool |
| `infra/docker-compose.mysql-test.yml` | Isolated test stack for verification | Port 53306, volume `capital-cortex_mysql_test_data` |
| `scripts/backup.py` | `pg_basebackup` & WAL replication to MinIO | `mysqldump` / MySQL enterprise backup & binlog shipping |
| `scripts/restore_drill.py` | PostgreSQL WAL replay drill | MySQL point-in-time recovery drill |
| `infra/postgres/archive-wal.sh` | WAL gzip & archiving | MySQL binlog archiving script |
| `infra/postgres/init/01-extensions.sql` | `pgcrypto`, `vector`, `age`, `pg_trgm` | MySQL database initialization (`cortex`, `keycloak`) |
| `tests/integration/conftest.py` | `testcontainers.postgres.PostgresContainer` | MySQL testcontainer / isolated MySQL service |

---

## 8. Baseline Verification Sign-off

- [x] All 50 tables, columns, indexes, and constraints cataloged.
- [x] All raw SQL query patterns surveyed and mapped to MySQL equivalents.
- [x] CKG graph write and traversal paths cataloged.
- [x] pgvector retrieval path verified and isolated.
- [x] Advisory lock and data integrity triggers verified.
- [x] Safety boundaries confirmed: Zero changes to PostgreSQL containers, data volumes, or pre-existing Git modifications.

**Phase 0 Status: COMPLETE — Baseline Established.**
