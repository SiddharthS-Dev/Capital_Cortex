# Cortex PostgreSQL-to-MySQL Migration — Phase 4 Execution Report: Graph Subsystem Migration

> **Historical record (undated; file last saved 2026-10-27).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


**Document ID:** CRTX-EXEC-MYSQL-2026-004  
**Project:** Inspironics MERIS — Capital Cortex™ Module  
**Source Platform:** PostgreSQL 16.x (Apache AGE 1.5.0, pgvector 0.8.0, pg_trgm, pgcrypto)  
**Target Platform:** MySQL 8.4 Community Edition (InnoDB, `utf8mb4_0900_ai_ci`)  
**Execution Date:** October 27, 2026  
**Status:** **PHASE 4 COMPLETED & VERIFIED (GATE PASSED)**  
**Reference Documents:**
- `CORTEX_MYSQL_MIGRATION_FEASIBILITY_REPORT.md` (CRTX-MIG-MYSQL-2026-001)
- `CORTEX_MYSQL_MIGRATION_VERIFICATION_REPORT.md` (CRTX-VERIF-MYSQL-2026-002)
- `CORTEX_MYSQL_MIGRATION_IMPLEMENTATION_PLAN.md` (CRTX-PLAN-MYSQL-2026-001)
- `CORTEX_MYSQL_PHASE2_EXECUTION_REPORT.md` (CRTX-EXEC-MYSQL-2026-002)
- `CORTEX_MYSQL_PHASE3_EXECUTION_REPORT.md` (CRTX-EXEC-MYSQL-2026-003)

---

## 1. Executive Summary

Phase 4 of the Cortex PostgreSQL-to-MySQL migration has been successfully completed. The Cortex graph subsystem has been decoupled from all Apache AGE runtime dependencies (`LOAD '$libdir/plugins/age'`, `ag_catalog.cypher`, `agtype`, and internal catalog tables `ckg._ag_label_*`). All graph operations—including vertex and edge ingestion, neighbourhood exploration, bidirectional shortest-path discovery, provenance tracing, label queries, and stats aggregations—now execute natively against the relational `entity` and `relationship_edge` tables on MySQL 8.4 Community Edition.

Key highlights:
1. **Zero Active Runtime AGE Dependencies:** Full repository scan confirmed **0** active runtime imports of `platform_core.db.age` in `cortex/`. All write and traversal operations use parameterized SQL targeting relational tables.
2. **Relational Graph Topology Verification:** Validated that `entity` and `relationship_edge` tables in MySQL 8.4 contain complete graph topology, directionality, metadata (`attrs`, `source_ref`), and foreign key relationships.
3. **Bounded Bidirectional BFS Preserved:** The shortest-path finder (`paths`) and neighbourhood query (`neighbourhood`) maintain exact algorithmic parity, cycle detection, edge direction agnosticism, and frontier caps (`FRONTIER_CAP = 20_000`) without memory explosion.
4. **Public API Contract Compatibility:** All graph endpoints (`GET /v1/graph/query` with `neighbourhood`, `provenance`, `label`, `cypher` templates, `GET /v1/graph/paths`, and `GET /v1/graph/stats`) produce identical response schemas (`{nodes: [...], edges: [...]}`).
5. **Targeted MySQL Test Evidence:** 8 dedicated graph test cases in [`tests/unit/test_mysql_graph.py`](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/tests/unit/test_mysql_graph.py) passed against the isolated MySQL 8.4 instance in **1.88s**.
6. **Safety & Zero Disruption:** Volume `capital-cortex_pgdata` remains 100% untouched; all 9 external host containers remain online; 0 git commits created.

---

## 2. Graph Dependency Inventory

### 2.1 Graph Entity and Relationship Schema

| Schema Element | Relational Table | Identifier Strategy | Key Columns & Data Types | Invariant / Index Support |
|---|---|---|---|---|
| **Vertices / Nodes** | `entity` | UUID string (`varchar(36)`) | `id` (PK), `org_id`, `entity_type` (e.g. `Organization`, `Contact`, `Fund`, `Opportunity`, `Signal`), `ref_table`, `ref_id` (domain ID), `label` (title/name), `attrs` (JSON properties), `source_ref` (JSON provenance) | Indexed on `(org_id, ref_table, ref_id)`, `(org_id, entity_type)`, `(ref_id)`. |
| **Edges / Relationships** | `relationship_edge` | UUID string (`varchar(36)`) | `id` (PK), `org_id`, `from_entity` (FK $\rightarrow$ `entity.id`), `to_entity` (FK $\rightarrow$ `entity.id`), `type` (e.g. `OFFERS`, `KNOWS`, `MANAGES`, `DERIVED_FROM`, `PART_OF`), `attrs` (JSON), `source_ref` (JSON) | Foreign keys to `entity(id)`. Indexed on `(org_id, from_entity)`, `(org_id, to_entity)`, `(from_entity, to_entity, type)`. |

### 2.2 Relationship Types and Directionality

| Edge Type | Typical Source Entity | Typical Target Entity | Business Meaning & Invariant |
|---|---|---|---|
| `OFFERS` | `Organization` | `Opportunity` | Counterparty offers capital instrument |
| `DERIVED_FROM` | `Opportunity` / `Organization` | `Signal` | Invariant I5: Provenance continuity back to perception |
| `KNOWS` | `Organization` | `Contact` | Warm introduction / network relationship |
| `MANAGES` | `Fund` | `Contact` / `Opportunity` | Fund management and allocations |
| `PART_OF` | `Contact` | `Organization` | Affiliation / Employment relationship |
| `RELATES_TO` | `Contact` | `Organization` | Interaction linkage |

### 2.3 Traversal Operations Inventory

| Operation | Implementation Function | Traversal Strategy | Cycle & Frontier Handling |
|---|---|---|---|
| **ID Resolution** | [`graph_traversal.find()`](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/cortex/l2_representation/graph_traversal.py#L18) | Single-row lookup on `ref_id = :id OR id = :id` | Returns domain ID $\rightarrow$ internal entity ID mapping |
| **Neighbourhood** | [`graph_traversal.neighbourhood()`](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/cortex/l2_representation/graph_traversal.py#L98) | Level-by-level BFS up to depth 2 | Visited set `vids` prevents duplicate hops and cyclic revisits; `limit` caps edges per hop |
| **Shortest Paths** | [`graph_traversal.paths()`](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/cortex/l2_representation/graph_traversal.py#L116) | Bidirectional BFS expanding from both endpoints | `parent` map tracks predecessor and prevents cycles; `FRONTIER_CAP = 20_000` bounds memory; meeting vertices detected when frontiers intersect |
| **Provenance** | Router [`query(template="provenance")`](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/cortex/l8_actuation/api/routers/graph.py#L94) | Directed 3-hop upstream walk on `type = 'DERIVED_FROM'` | Fixed 3-level loop terminating early on empty frontier |
| **Label Filter** | Router [`query(template="label")`](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/cortex/l8_actuation/api/routers/graph.py#L122) | Query `entity WHERE entity_type = :lbl` and related edges | Parameterized multi-id query capped by `limit` |
| **Graph Stats** | Router [`stats()`](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/cortex/l8_actuation/api/routers/graph.py#L159) | Group-by aggregations on `entity_type` and `type` | Fast aggregate index scan |

---

## 3. Files Changed and Technical Modifications

### 3.1 [`cortex/l2_representation/graph_traversal.py`](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/cortex/l2_representation/graph_traversal.py)
- **Removed:** All references to `ckg._ag_label_vertex`, `ckg._ag_label_edge`, `ag_catalog.graphid[]`, `ag_catalog.agtype`, and `platform_core.db.age`.
- **Implemented:**
  - `find(s, ids)`: Parameterized query over `entity WHERE ref_id = :id OR id = :id`.
  - `_edges(s, frontier, cap)`: Parameterized union query over `relationship_edge WHERE from_entity IN (...) UNION ALL ... WHERE to_entity IN (...)`.
  - `materialise(s, vids, eids)`: Constructs API node/edge payloads directly from `entity.attrs`, `entity.label`, and `relationship_edge.source_ref`.
  - Maintained bidirectional BFS pathfinder with frontier cap and cycle protection.

### 3.2 [`cortex/l2_representation/graph_writer.py`](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/cortex/l2_representation/graph_writer.py)
- **Removed:** Direct Cypher queries (`age.cypher`, `MATCH ... DELETE`, `MERGE ...`).
- **Implemented:**
  - `_entity(s, ...)`: Client-side UUID generation (`str(uuid.uuid4())`), `SELECT id FROM entity`, followed by `INSERT` or `UPDATE`.
  - `_edge(s, ...)`: Client-side UUID generation and `INSERT INTO relationship_edge ... ON DUPLICATE KEY UPDATE`.
  - `upsert_vertex(s, ...)` and `upsert_edge(s, ...)`: Relational write operations targeting `entity` and `relationship_edge`.

### 3.3 [`cortex/l8_actuation/api/routers/graph.py`](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/cortex/l8_actuation/api/routers/graph.py)
- **Cypher Console:** Maintained `template="cypher"` endpoint for administrative compliance. In MySQL 8.4 mode, it safely records an audit log and returns an explicit deprecation notice with empty graph structures without executing arbitrary Cypher or raw SQL.
- **Provenance Template:** Implemented as a directed relational BFS query over `relationship_edge WHERE type = 'DERIVED_FROM'`.
- **Stats Endpoint:** Groups by `entity_type` and `relationship_edge.type` using standard MySQL aggregations.

### 3.4 [`tests/unit/test_mysql_graph.py`](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/tests/unit/test_mysql_graph.py)
- Created dedicated test suite validating all graph storage and traversal operations against the isolated MySQL 8.4 container.

---

## 4. Test Evidence & Validation

The test suite [`tests/unit/test_mysql_graph.py`](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/tests/unit/test_mysql_graph.py) was executed using `.venv\Scripts\pytest -v`:

```text
============================= test session starts =============================
platform win32 -- Python 3.12.15, pytest-9.1.1, pluggy-1.7.0
rootdir: <repo>
configfile: pyproject.toml
plugins: anyio-4.15.1, hypothesis-6.170.11, asyncio-1.4.1, cov-7.1.0, respx-0.23.1, schemathesis-4.32.5
asyncio: mode=Mode.AUTO
collected 8 items

tests/unit/test_mysql_graph.py::test_entity_and_edge_upsert_and_find PASSED [ 12%]
tests/unit/test_mysql_graph.py::test_neighbourhood_traversal PASSED      [ 25%]
tests/unit/test_mysql_graph.py::test_shortest_paths_and_bidirectional_bfs PASSED [ 37%]
tests/unit/test_mysql_graph.py::test_cycle_detection PASSED              [ 50%]
tests/unit/test_mysql_graph.py::test_duplicate_relationship_upsert PASSED [ 62%]
tests/unit/test_mysql_graph.py::test_empty_and_missing_handling PASSED   [ 75%]
tests/unit/test_mysql_graph.py::test_materialise_contract PASSED         [ 87%]
tests/unit/test_mysql_graph.py::test_provenance_and_label_templates PASSED [100%]

======================== 8 passed, 1 warning in 1.88s =========================
```

Combined MySQL test run (`test_mysql_session.py` + `test_mysql_graph.py`):
```text
======================== 17 passed, 1 warning in 4.00s ========================
```

Full unit test suite check:
- Baseline unit test suite (`pytest -m "not integration and not contract"`): **189 tests PASSED in 266s**.
- API endpoint test suite (`tests/unit/test_api.py`): **26 tests PASSED in 6.93s**.

---

## 5. AGE Dependency Audit & Status

| Code Area | Current Status | Notes |
|---|---|---|
| **`cortex/l2_representation/`** | **0 AGE dependencies** | Migrated to `entity` and `relationship_edge` |
| **`cortex/l8_actuation/api/routers/graph.py`** | **0 AGE dependencies** | Migrated; Cypher console deprecated safely |
| **`cortex/l3_memory/`** | **0 AGE dependencies** | Writes through relational `graph_writer.py` |
| **`platform_core/db/age.py`** | **Isolated** | Retained for backward compatibility with existing Postgres integration tests (`test_graph_traversal.py`) |
| **`seed/purge.py`** | **Conditional** | Contains demo purge cypher query for Postgres; relational tables cleaned via `TABLES` list |

---

## 6. Safety & Preservation Verification

1. **PostgreSQL Volume & Cluster:**
   - Volume `capital-cortex_pgdata` verified untouched (`docker volume inspect capital-cortex_pgdata`).
   - Active database configuration in [`.env`](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/.env) continues to reference PostgreSQL 16.
2. **Host Containers:**
   - All 9 active external containers (`apm-platform-*`, `caleido-*`) remain online and healthy with continuous uptime.
3. **Git Working Tree:**
   - Branch: `feature/changes-login`.
   - All pre-existing user modifications strictly preserved. Zero commits or git pushes created.

---

## 7. Completion Gate Verdict

| Gate Requirement | Status |
|---|---|
| Decouple graph subsystem from Apache AGE runtime queries | **PASS** |
| Verify relational graph representation (`entity`, `relationship_edge`) in MySQL 8.4 | **PASS** |
| Verify neighbourhood BFS traversal and shortest paths | **PASS** |
| Verify cycle handling, missing entity safety, and empty graphs | **PASS** |
| Verify public API response format compatibility | **PASS** |
| All MySQL graph tests execute and pass on isolated container (port 53306) | **PASS** |
| PostgreSQL database, volume, and external services completely unaffected | **PASS** |

### Verdict
**`PHASE 4 PASSED — GRAPH SUBSYSTEM MIGRATION COMPLETE`**

*Execution has stopped at the Phase 4 completion gate. Awaiting explicit user authorization before proceeding to Phase 5 (Vector Subsystem Migration).*
