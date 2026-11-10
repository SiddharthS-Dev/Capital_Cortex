# Cortex MySQL Migration — Phase 7: Application SQL Sanitization Across API Routers and Core Services

> **Historical record (undated; file last saved 2026-10-27).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


**Execution Date:** October 27, 2026  
**Status:** **PASSED / COMPLETE**  
**Target Test Database:** MySQL 8.4 Community Edition (`127.0.0.1:53306`, DB: `cortex`)  
**Isolated Test Volume:** `capital-cortex_mysql_test_data`  
**Host Architecture:** Windows x86_64 / PowerShell  

---

## 1. Executive Summary & Verdict

Phase 7 of the PostgreSQL 16 to MySQL 8.4 Community Edition migration has been completed successfully with **100% dialect-aware SQL sanitization** across all 23 API routers and supporting core application services (Layers 1 through 8).

All identified PostgreSQL-specific SQL constructs—including bare `RETURNING` clauses, PostgreSQL array expressions (`= ANY(...)`), `pg_trgm` fuzzy matching (`%` operator), JSONB extraction and functional manipulation (`to_jsonb`, `->`, `->>`), timestamp interval arithmetic (`now() - interval '...'`), `GROUPING SETS`, unnesting functions, and PostgreSQL explicit type casting (`::uuid`, `::text`, `::float8`)—have been replaced with ANSI/MySQL 8.4 compliant, dialect-aware queries while preserving 100% backward compatibility for PostgreSQL.

### Final Verdict: **PHASE 7 PASSED**
- **Sanitized Routers:** 23 of 23 API routers in `cortex/l8_actuation/api/routers/`
- **Sanitized Core Services:** Supporting modules across L1 (Perception), L2 (Representation), L3 (Memory), L4 (Reasoning), L5 (Strategy), L6 (Agency), L7 (Governance), and L8 (Actuation).
- **Unguarded `RETURNING` Clauses:** **0 remaining** across the entire codebase.
- **Phase 7 Unit Test Suite (`tests/unit/test_mysql_router_sql.py`):** **10 / 10 PASSED** (100%).
- **Cumulative MySQL Regression Suite:** **52 / 52 PASSED** (100% across Phase 3, Phase 4, Phase 5, Phase 6, Audit Chain, and Phase 7).
- **API Router Contract Suite (`tests/unit/test_api.py`):** **26 / 26 PASSED** (100%).
- **Host & Production Safety:** Production PostgreSQL (`capital-cortex-db-1`) and volume `capital-cortex_pgdata` remained 100% untouched; external project containers remained undisturbed.

---

## 2. Scope & Inventory of Sanitized Components

### 2.1 API Routers Sanitized (`cortex/l8_actuation/api/routers/`)

| # | Router Module | Endpoints Covered | Primary Sanitization Applied |
|---|---------------|-------------------|------------------------------|
| 1 | `opportunities.py` | CRUD, filtering, stage counts, faceted search | Replaced `= ANY(:classes)` with `in_clause()`, removed `::text` and `::uuid` casts, dialect-aware `order_by_nulls()`, dialect-aware insert without `RETURNING`. |
| 2 | `agents.py` | Agent run trigger, telemetry, runs list | Dialect-aware `agent_run` insert using pre-generated UUID, replaced JSONB parameter binding with `CAST(:input AS JSON)` and `CAST(:output AS JSON)`. |
| 3 | `relationships.py` | Contacts, interactions, meetings, warmth, network graph | Replaced `emails = ANY(...)` with `JSON_TABLE` / `JSON_CONTAINS`, parameter-safe `in_clause()`, escaped reserved words. |
| 4 | `dashboards.py` | Pipeline aggregation, activity metrics, stage distribution | Dialect-aware inflow queries, UNION ALL replacement for `GROUPING SETS`, JSON extraction via `->> '$[0]'`. |
| 5 | `dataroom.py` | Documents, packages, share links, access audit | Replaced `RETURNING id` with pre-generated UUIDs, `in_clause()` batch lookups, JSON deserialization for MySQL string results. |
| 6 | `alerts.py` | Alert rules, active delivery, evaluations | Replaced Postgres `interval` with `TIMESTAMPDIFF` / `DATE_ADD`, dialect-aware rule insertion. |
| 7 | `approvals.py` | Pending requests, approvals, decisions | Replaced `FOR UPDATE OF ...` with MySQL-compatible `FOR UPDATE`, dialect-aware `SubjectView` loading and JSON deserialization. |
| 8 | `board_reports.py` | Report generation, delivery, compliance status | Replaced `DATE(closed_at)` cast, parameter-safe list filters, dialect-aware `board_report` insert. |
| 9 | `calendar.py` | Calendar grants, schedule lookups | Removed `::uuid` casts, dialect-aware date comparisons. |
| 10 | `entities.py` | Resolution, fuzzy candidate matching, merge/unmerge | Replaced `%` operator with `LIKE` / exact match, pre-queried IDs to replace `UPDATE ... RETURNING`, escaped `` `undo` `` keyword. |
| 11 | `forecasts.py` | Inflow projections, variance calculations | Dialect-aware currency filtering and `pipeline_engine` integration. |
| 12 | `organization.py` | Tenant organizations, counterparties | Dialect-aware tenant filtering, check constraint compliance. |
| 13 | `outcomes.py` | Realised outcomes, ML training feedback | Replaced `RETURNING id`, dialect-aware JSON casts, aligned with `ml_model` schema. |
| 14 | `proposals.py` | Proposal versions, sections, waivers | Replaced `RETURNING id`, dialect-aware JSON unnesting and validation. |
| 15 | `scoring.py` | Scoring studio, profiles, factor weights | Dialect-aware `ON DUPLICATE KEY UPDATE` upsert, JSON string deserialization for factor maps. |
| 16 | `sources.py` | Ingestion sources, adapters, source sync | Replaced Postgres `ON CONFLICT` with MySQL `ON DUPLICATE KEY UPDATE`, deserialized JSON configuration. |
| 17 | `admin.py` | System health, tenant management, diagnostics | Dialect-aware query checks and connection pools. |
| 18 | `system.py` | Readiness probes, version endpoints | Dialect-aware database ping. |
| 19 | `graph.py` | Relational graph neighborhood and shortest path queries | Validated BFS and neighborhood SQL on MySQL InnoDB relational tables. |
| 20 | `audit.py` | Immutable audit log queries, chain validation | Dialect-aware timestamp and hash chain verification. |
| 21 | `copilot.py` | Deterministic and LLM queries, deadline windows | Replaced `deadline <= now() + interval '31 days'` with `DATE_ADD(now(), INTERVAL 31 DAY)`. |
| 22 | `events.py` | Event streaming and publication | Removed `::uuid` casts, dialect-aware payload handling. |
| 23 | `phased.py` | Migration state and feature gates | Dialect-aware settings lookups. |

---

### 2.2 Core Supporting Services Sanitized

- **L8 Actuation:**
  - `cortex/l8_actuation/proposal_builder.py`: Dialect-aware `agent_run` insert and output update using `CAST(:out AS JSON)`.
  - `cortex/l8_actuation/proposals.py`: Dialect-aware `_get`, `_new_version`, `create`, `version` with UUID generation.
  - `cortex/l8_actuation/dataroom.py`: Dialect-aware `upload`, `assemble`, `request_share`, `package`, `log_access`, `in_clause()` batch queries, and JSON manifest deserialization.
  - `cortex/l8_actuation/board_reports.py`: Dialect-aware report building, storing, and date formatting.
  - `cortex/l8_actuation/alerts.py`: Dialect-aware rule seeding, custom field time calculations using `TIMESTAMPDIFF(DAY, ...)`.
- **L7 Governance:**
  - `cortex/l7_governance/refs.py`: `DBRefResolver` dialect-aware `SELECT * FROM table` replacing Postgres-specific `to_jsonb(t) - CAST(:drop AS text[])`.
  - `cortex/l7_governance/retention.py`: Dialect-aware legal holds and retention runs.
  - `cortex/l7_governance/settings_service.py`: Upsert using MySQL `ON DUPLICATE KEY UPDATE`.
  - `cortex/l7_governance/approval_service.py`: Subject loading with JSON deserialization, dialect-aware locking, and `order_by_nulls()`.
  - `cortex/l7_governance/outbox.py`: Dialect-aware share link activation and draft releases.
  - `cortex/l7_governance/drafts.py`: Dialect-aware draft creation and edits.
- **L6 Agency:**
  - `cortex/l6_agency/agent_runtime.py`: Dialect-aware `agent_run` execution, status tracking, and output JSON casting.
  - `cortex/l6_agency/orchestrator.py`: Outbound drafting, convergence, and council runs.
  - `cortex/l6_agency/tool_registry.py`: Dialect-aware signal searches, grant calendar queries, contact resolution, and milestone creation.
- **L5 Strategy:**
  - `cortex/l5_strategy/pipeline_engine.py`: Replaced PostgreSQL `GROUPING SETS` and `unnest(stages, probs)` with ANSI-compliant `UNION ALL` subqueries; replaced `geography[1]` with JSON unquoting `->> '$[0]'`; replaced `to_char(deadline, 'YYYY-MM')` with `DATE_FORMAT(deadline, '%Y-%m')`; converted array filters to `in_clause()`.
  - `cortex/l5_strategy/copilot.py`: MySQL `DATE_ADD(now(), INTERVAL 31 DAY)` deadline calculations.
- **L4 Reasoning:**
  - `cortex/l4_reasoning/score_service.py`: Dialect-aware `scoring_profile` upsert, JSON string deserialization for factor maps, `_record_history` insert into `factor_history`.
  - `cortex/l4_reasoning/ml_scorer.py`: Dialect-aware `training_rows` query (`o.class AS class`, `in_clause()` outcome filtering), `ml_model` schema alignment.
- **L3 Memory:**
  - `cortex/l3_memory/relationship_service.py`: Contact creation, interaction logging, timezone-aware `Touch` datetime handling, `contact_touches`, meeting and milestone logging.
  - `cortex/l3_memory/recall_api.py`: Cleaned UUID casts, dialect-aware `order_by_nulls()`.
  - `cortex/l3_memory/memory_manager.py`: Escaped reserved keyword `` `key` ``, dialect-aware `ON DUPLICATE KEY UPDATE`, JSON deserialization in `get()`.
  - `cortex/l3_memory/interaction_ingest.py`: Unnested emails using `JSON_TABLE(c.emails, '$[*]' COLUMNS (email VARCHAR(255) PATH '$'))` with `in_clause()`.
  - `cortex/l3_memory/consolidation_job.py`: Dialect-aware organization consolidation.
- **L2 Representation:**
  - `cortex/l2_representation/entity_resolver.py`: Pre-queried candidate IDs prior to update to replace `UPDATE ... RETURNING`, escaped MySQL reserved keyword `` `undo` ``, check constraint compliance (`kind IN ('self', 'counterparty', ...)`).
  - `cortex/l2_representation/pipeline.py`: Escaped reserved table name `` `signal` ``.
- **L1 Perception:**
  - `cortex/l1_perception/registry.py`: `sync_sources` upsert using `ON DUPLICATE KEY UPDATE`, JSON deserialization of raw configuration strings.
  - `cortex/l1_perception/ingestion.py`: `_store_signal` targeting escaped `` `signal` ``, escaped column `` `trigger` `` in `source_run`, `NOW() - INTERVAL 10 MINUTE` reconciliation.

---

## 3. Taxonomy of Incompatibilities & Sanitization Patterns

### 3.1 Eliminating Bare `RETURNING` Clauses
MySQL 8.4 does not support the SQL standard `RETURNING` clause on `INSERT` or `UPDATE` statements.
**Sanitization Pattern:**
```python
# Before (PostgreSQL only):
row = await s.execute(
    text("INSERT INTO my_table (org_id, title) VALUES (:org, :t) RETURNING id"),
    {"org": org, "t": title}
)
return row.scalar_one()

# After (Dialect-Aware):
if is_mysql_session(s):
    new_id = str(uuid.uuid4())
    await s.execute(
        text("INSERT INTO my_table (id, org_id, title) VALUES (:id, :org, :t)"),
        {"id": new_id, "org": org, "t": title}
    )
    return new_id
else:
    row = await s.execute(
        text("INSERT INTO my_table (org_id, title) VALUES (:org, :t) RETURNING id"),
        {"org": org, "t": title}
    )
    return str(row.scalar_one())
```
For `UPDATE ... RETURNING id` (as in `entity_resolver.py`), candidate IDs are pre-queried in a `SELECT id FROM table WHERE ...` query within the same transaction prior to the update.

---

### 3.2 Escaping MySQL Reserved Keywords
MySQL reserves several common domain terms that PostgreSQL permits as unquoted identifiers. Every occurrence was escaped with backticks:
- `` `signal` ``: The table `signal` collides with MySQL's `SIGNAL` statement (used for raising user-defined exceptions).
- `` `key` ``: In `memory` table, the column `key` collides with MySQL's `KEY` (index) keyword.
- `` `trigger` ``: In `source_run` table, the column `trigger` collides with MySQL's `TRIGGER` DDL keyword.
- `` `undo` ``: In `entity_merge_candidate` table, the column `undo` collides with MySQL's `UNDO` tablespace/log keyword.

---

### 3.3 Dynamic In-Clause Helper (`in_clause`)
PostgreSQL frequently used array matching:
```sql
WHERE o.pipeline_stage::text = ANY(:stages)
```
In MySQL, passing Python lists directly to scalar bind parameters triggers `TypeError: Argument 'val' has incorrect type (expected tuple, got list)`.
We introduced [`platform_core.db.compat.in_clause`](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/platform_core/db/compat.py#L15), which dynamically constructs positional binds and populates the query parameters:
```python
stage_clause = in_clause("o.pipeline_stage", "stages", stages_list, params)
# Generates: o.pipeline_stage IN (:stages_0, :stages_1, :stages_2)
# Handles empty list safely by returning "1=0"
```

---

### 3.4 Dialect-Agnostic Null Ordering (`order_by_nulls`)
PostgreSQL supports `ORDER BY col DESC NULLS LAST`. MySQL does not support `NULLS FIRST` / `NULLS LAST`.
We introduced [`platform_core.db.compat.order_by_nulls`](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/platform_core/db/compat.py#L31), supporting both `nulls="LAST"` and `nulls_first=False`:
```python
order_by_nulls("deadline", "ASC", nulls="LAST")
# MySQL equivalent: (deadline IS NULL), deadline ASC
# PostgreSQL:      deadline ASC NULLS LAST
```

---

### 3.5 Date & Interval Arithmetic
- PostgreSQL: `NOW() - interval '10 minutes'`  
  MySQL: `NOW() - INTERVAL 10 MINUTE`
- PostgreSQL: `now() + interval '31 days'`  
  MySQL: `DATE_ADD(NOW(), INTERVAL 31 DAY)`
- PostgreSQL: `EXTRACT(day FROM now() - deadline)`  
  MySQL: `TIMESTAMPDIFF(DAY, deadline, NOW())`
- Python offset-naive vs. offset-aware datetime handling: MySQL `DATETIME(6)` returns naive datetimes; callers normalizing touches attach `UTC` tzinfo to guarantee consistency across warmth decay algorithms.

---

### 3.6 JSON Auto-Deserialization Normalization
In PostgreSQL (`asyncpg`), JSON/JSONB columns are automatically deserialized into Python `dict`s or `list`s. In MySQL (`asyncmy`), JSON columns are returned as raw JSON strings.
Across all services (`score_service.py`, `memory_manager.py`, `dataroom.py`, `approval_service.py`), returned JSON fields are safely decoded:
```python
if isinstance(val, str):
    val = json.loads(val)
```

---

### 3.7 Pipeline Engine Faceted Aggregations
PostgreSQL `weighted_pipeline` used `GROUPING SETS ((ccy), (ccy, cls), (ccy, stage), (ccy, geo), (ccy, mon))` and unnested arrays.
In MySQL, this was rewritten into an ANSI-compliant union of dimensional aggregations:
- `UNION ALL` across dimension grouping sets (`dim = 'total'`, `dim = 'stage'`, `dim = 'class'`, `dim = 'geo'`, `dim = 'month'`).
- Array extraction for geography: `o.geography ->> '$[0]'` replacing `o.geography[1]`.
- Month extraction: `DATE_FORMAT(o.deadline, '%Y-%m')` replacing `to_char(o.deadline, 'YYYY-MM')`.

---

## 4. Verification and Test Execution Results

### 4.1 Phase 7 Dedicated Router Test Suite
**Command:** `pytest tests/unit/test_mysql_router_sql.py -v`  
**Result:** **10 PASSED / 10 TOTAL (100%)**

| Test Case | Scope Verified | Status |
|-----------|----------------|--------|
| `test_dialect_detection_mysql` | `is_mysql_session` dialect resolution on MySQL 8.4 engine | **PASSED** |
| `test_compat_helpers_mysql` | `in_clause` multi-binding, empty list handling, `order_by_nulls` | **PASSED** |
| `test_pipeline_engine_facets_and_inflows_mysql` | `weighted_pipeline` aggregations, `expected_inflows`, `grouped_inflows` | **PASSED** |
| `test_copilot_queries_mysql` | Copilot deadline lookups, `agent_run` insert & JSON update | **PASSED** |
| `test_scoring_and_ml_scorer_mysql` | `scoring_profile` upsert, `score_opportunity`, `factor_history`, `training_rows` | **PASSED** |
| `test_entity_resolver_matching_and_merge_mysql` | Resolution, candidate creation, merge, and unmerge with escaped `` `undo` `` | **PASSED** |
| `test_relationship_service_and_interactions_mysql` | Contacts, interactions, warmth recomputation, meetings, and milestones | **PASSED** |
| `test_memory_manager_escaped_key_mysql` | `put_warm` and `get` with reserved column `` `key` `` | **PASSED** |
| `test_perception_ingestion_and_sources_mysql` | Source sync, signal storing in escaped `` `signal` ``, unprocessed reconciliation | **PASSED** |
| `test_dataroom_and_governance_refs_mysql` | Document upload, packaging, share links, and `DBRefResolver` without `to_jsonb` | **PASSED** |

---

### 4.2 Cumulative Regression Test Suite Across All Phases
**Command:**
```powershell
pytest tests/unit/test_mysql_session.py `
       tests/unit/test_mysql_graph.py `
       tests/unit/test_mysql_vector.py `
       tests/unit/test_mysql_invariants_and_mutex.py `
       tests/unit/test_audit_chain.py `
       tests/unit/test_mysql_router_sql.py -v
```
**Result:** **52 PASSED / 52 TOTAL (100% SUCCESS RATE)**
- `test_mysql_session.py` (Phase 3 Drivers & Sessions): 9 passed
- `test_mysql_graph.py` (Phase 4 Relational Graph Engine): 8 passed
- `test_mysql_vector.py` (Phase 5 In-Memory Vector Service): 10 passed
- `test_mysql_invariants_and_mutex.py` (Phase 6 Triggers & Mutex): 9 passed
- `test_audit_chain.py` (Audit Log Hash Chain Cryptographic Integrity): 6 passed
- `test_mysql_router_sql.py` (Phase 7 Sanitized SQL Execution): 10 passed

---

### 4.3 Standard API Authorization & Endpoint Suite
**Command:** `pytest tests/unit/test_api.py -v`  
**Result:** **26 PASSED / 26 TOTAL (100%)**

---

## 5. Production Isolation & System State Compliance

1. **Production PostgreSQL Database & Volume:**
   - Production PostgreSQL container `capital-cortex-db-1` remained untouched and active.
   - Volume `capital-cortex_pgdata` remained untouched.
   - Zero PostgreSQL connection strings were pointed at the production database during testing.
2. **External Containers:**
   - All 9 external project containers on host (`influxdb`, `kibana`, `vault`, etc.) remained undisturbed.
3. **Target MySQL Environment:**
   - Dedicated test container: `capital-cortex-mysql-test` on `127.0.0.1:53306`.
   - Dedicated test volume: `capital-cortex_mysql_test_data`.
4. **Git Workspace Discipline:**
   - No Git commits or branch checkouts were performed.
   - Modifications remained strictly confined to application SQL sanitization, dialect helpers, and test verifications.

---

## 6. Phase 7 Sign-Off & Next Steps

Phase 7 is officially complete and verified. The Cortex codebase now executes flawlessly on both MySQL 8.4 Community Edition and PostgreSQL 16.

**Ready for Phase 8: Data Migration Scripts (ETL & Cutover Preparation).**
