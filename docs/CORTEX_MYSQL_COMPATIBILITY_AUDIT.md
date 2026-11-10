# Capital Cortex: MySQL 8.4 Compatibility Audit

Execution date: **2026-11-03**.
- **Method:** a static census of every PostgreSQL-specific construct in `cortex/` and `platform_core/`, plus tracing of which execution paths can reach it on MySQL.
- **Behavioural evidence:** the full MySQL-backed test run in the 2026-11-03 test run (465 unit tests and 20 integration tests passing against MySQL 8.4.13). Raw-SQL injection safety was audited in the 2026-11-03 security round (the enterprise security review §8).

## How Cortex supports both databases

- **48 modules** branch on `is_mysql_session(session)` (`platform_core/db/compat.py`):
  - 17 routers, 6 `l8_actuation`, 6 `l7_governance`, 5 `l3_memory`, 3 `l6_agency`;
  - 2 each in `l5_strategy`, `l4_reasoning`, `l2_representation` and `l1_perception`;
  - 2 in `platform_core`.
- Shared helpers keep the SQL dialect-neutral: `in_clause` (bound `IN` lists replacing `= ANY(:arr)`) and `order_by_nulls`.
- **The MySQL schema** comes from the Alembic chain `migrations_mysql/` (m0001 → m0004). The demo database is at head, `m0004_reconcile_legacy_layouts` (verified with `alembic -n mysql current`).
- **The PostgreSQL schema** stays in `migrations/` for the rollback window (ARCH-3).

## Census of PostgreSQL-specific constructs (files containing each)

| Construct | Files | On MySQL |
|---|---|---|
| `::uuid` / `::jsonb` / `::text` casts | 15 | only inside PostgreSQL branches |
| `RETURNING` | 29 | PostgreSQL branches; MySQL pre-generates UUIDs and re-selects |
| `ON CONFLICT` | 13 | PostgreSQL branches; MySQL uses `INSERT IGNORE` / `ON DUPLICATE KEY UPDATE` |
| `= ANY(:arr)` | 14 | PostgreSQL branches; MySQL uses `in_clause` |
| `ILIKE` | 3 | PostgreSQL branches; MySQL `LIKE` with the case-insensitive `utf8mb4_0900_ai_ci` collation (same behaviour) |
| `websearch_to_tsquery` / `@@` | 1 | PostgreSQL branch; MySQL uses `MATCH … AGAINST` plus `LIKE` (see PERF-1) |
| `jsonb_*` / `json_build_object` | 4 | PostgreSQL branches; MySQL uses `JSON_*` functions |
| `INTERVAL` string literals | 4 | PostgreSQL branches; MySQL uses `INTERVAL n UNIT` |
| `FILTER (WHERE …)` | 1 | PostgreSQL branch; MySQL uses `SUM(CASE …)` |
| `pg_advisory_*` | 1 | PostgreSQL branch; the MySQL audit append serialises on the `audit_lock` row (`FOR UPDATE`) |
| Apache AGE (`cypher`, `ag_catalog`) | 1: `platform_core/db/age.py` | **no importers**; the MySQL graph uses the relational `entity` / `relationship_edge` tables |
| pgvector (`<=>`, `vector`) | 1: `platform_core/db/vector.py`, constant `COSINE_SEARCH_SQL` | used **only** by a PostgreSQL-only integration test; the MySQL path stores float32 BLOBs and searches in memory |

**Only two files contain PostgreSQL constructs without a dialect branch** (`age.py`, `vector.py`), and neither is reachable from a MySQL execution path.

## Categorised result

### Fully MySQL-compatible (verified by tests executed today)

| Area | Evidence |
|---|---|
| Sessions, transactions and rollback | `test_mysql_session.py`, `test_mysql_invariants_and_mutex.py` |
| UUID handling (CHAR(36), app-generated) | `test_mysql_router_sql.py`; integration `test_api_flow`, `test_pipeline` |
| JSON operations | `test_mysql_router_sql.py`; integration `test_phase2_flow`, `test_phase3_flow` |
| Date/time (UTC; the server runs `--default-time-zone=+00:00`) | integration flows |
| Decimal and numeric precision | integration `test_seed`, `test_pipeline` |
| Upserts and conflict handling | `test_mysql_router_sql.py`, `test_live_ingestion.py` |
| Locking and concurrency (audit chain, scheduler mutex) | `test_mysql_invariants_and_mutex.py`, `test_audit_chain.py` |
| Pagination and sorting (whitelisted sort maps, `order_by_nulls`) | `test_mysql_router_sql.py`; the role-by-endpoint matrix over every route |
| Triggers (audit immutability, outbox and recommendation invalidation) | `test_mysql_m0004_reconcile.py`, `test_check_mysql_schema_drift.py` |
| Graph traversal (relational) | `test_mysql_graph.py`; integration `test_graph_traversal` |
| Vector storage and retrieval (BLOB + exact cosine) | `test_mysql_vector.py` |
| Indexes, foreign keys, constraints; schema drift | `test_check_mysql_schema_drift.py`; the CI `mysql-schema` job definition |
| Keycloak on MySQL (Liquibase schema, realm, users, clients) | 4 schema tests in `test_mysql_keycloak.py` |
| Migration tooling (PostgreSQL → MySQL ETL and reconciliation) | `test_migrate_pg_to_mysql.py`, `test_migrate_reconciliation.py` |

### Requires a fix

No correctness defect was found. One item is functionally correct but too slow, and its fix needs a product decision:
**PERF-1** (search, facets and totals at 200k rows; 6.1 s search). See `CORTEX_PERFORMANCE_AUDIT.md`.

### PostgreSQL-only by design

- `migrations/` and `infra/postgres/` (the AGE and pgvector image);
- `platform_core/db/age.py` (no importers);
- `COSINE_SEARCH_SQL` (test-only);
- the three skipped integration tests;
- the PostgreSQL branches of the 48 dual-path modules;
- the PostgreSQL ETL tools (`migrate_pg_to_mysql.py`, `rehearse_data_migration.py`).

All of these are kept for the rollback window. Removal is ARCH-4.

### Requires an architecture or product decision

- **PERF-1:** search semantics, facet strategy, totals;
- **ARCH-1:** Keycloak database separation;
- **ARCH-2:** vector index capacity;
- **ARCH-3:** rollback window and write loss;
- **ARCH-4:** dual-path code removal.

See `CORTEX_ARCHITECTURE_DECISION_REGISTER.md`.

## Limits of this audit

- **Not every branch is exercised.** Per-branch path coverage was not measured. The census shows that PostgreSQL syntax is confined to PostgreSQL branches, and the suites show that the MySQL branches they exercise are correct.
- **Untested routes:** a MySQL branch reached by no test is covered only by the role matrix (authorization and status codes), not by result assertions.
- **Production data shapes** (the B1 rehearsal) were not available.
