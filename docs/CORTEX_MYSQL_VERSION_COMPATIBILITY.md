# Capital Cortex: MySQL Version Compatibility

**Date:** 2026-11-07, 22:30–23:00 IST.
**For:** Project Lead, DBA, DevOps.
**Evidence:** server-settings capture, kept outside this repository (they contain machine-specific paths).

## 1. Conclusion

| Version | Status | Basis |
|---|---|---|
| **MySQL 8.4 LTS (8.4.13)** | **Supported and tested.** The whole test cycle runs on it: unit, integration, runtime, drift. | Local test server `capital-cortex-mysql-test`; CI service image `mysql:8.4` |
| MySQL 8.0.19 – 8.0.x | **Expected to work, NOT TESTED.** No feature used is missing from 8.0.19+, but nothing has been executed on 8.0. | Static scan (§3) |
| MySQL 8.0.0 – 8.0.18 | **Not supported.** Settings writes use the `AS new ... ON DUPLICATE KEY` row alias, which needs 8.0.19. `CHECK` constraints are parsed but **silently not enforced** before 8.0.16, which would disable the provenance, band and score-integrity guarantees. `JSON_OVERLAPS` and `LATERAL` don't exist. | Static scan (§3) |
| MySQL 5.7, MariaDB | **Not supported.** | No `JSON_TABLE`, window/CTE support differs; MariaDB's JSON is a `LONGTEXT` alias |
| MySQL 9.x Innovation | Not tested; not recommended for production (short support window). | – |

**Recommendation:** run production on **MySQL 8.4 LTS**, the version every test ran on. MySQL 8.0 reached end of life in April 2026, so a new deployment on 8.0 has no upstream security fixes. If DevOps or the DBA can only provide 8.0, **the test cycle must be re-run on that exact version first**; this register will not accept an 8.4 result as evidence for 8.0. The production version is still unknown (blocker **B2**).

## 2. Tested environment (measured 2026-11-07)

| Item | Value |
|---|---|
| Server | MySQL Community Server 8.4.13 (GPL) |
| Character set / collation | `utf8mb4` / `utf8mb4_0900_ai_ci` (server default and every application column in `cortex`, `cortex_unit`, `cortex_integration`, `cortex_demo`) |
| Exception | `cortex_integration.alembic_version` table uses `utf8mb4_unicode_ci`. It is never joined, so there is no "illegal mix of collations" risk; it can be aligned the next time that test schema is rebuilt |
| Time zone | `+00:00` global and session. The datetime fixes (M1, M9, H6) **depend on this**; production must keep `default-time-zone='+00:00'` |
| `sql_mode` | `ONLY_FULL_GROUP_BY, STRICT_TRANS_TABLES, NO_ZERO_IN_DATE, NO_ZERO_DATE, ERROR_FOR_DIVISION_BY_ZERO, NO_ENGINE_SUBSTITUTION` (8.4 default). Production must not relax it: strict mode turns silent truncation into errors |
| Isolation | `REPEATABLE-READ` (InnoDB default). The audit chain serialises with `SELECT … FOR UPDATE` on `audit_lock` |
| `lower_case_table_names` | 0 (Linux). Must be 0 in production too; it can only be set at initialisation |
| `group_concat_max_len` | 1024 (default). Covered by tests in `test_mysql_module_coverage_*` |
| FULLTEXT | `innodb_ft_min_token_size`=3, `ngram_token_size`=2 (relevant to PERF-1 option C) |
| Buffer pool | 512 MB (test server only; production sizing is INFRA-1) |
| Driver stack | asyncmy 0.2.17 (application), PyMySQL 1.2.3 (tools), SQLAlchemy 2.0.55, Alembic 1.20.1 |
| Pool | `pool_pre_ping=True`, `pool_recycle=3600` (below the server's `wait_timeout` of 28 800 s, measured) |
| Schema revision | `m0004_reconcile_legacy_layouts` on `cortex`, `cortex_unit`, `cortex_integration` and `cortex_demo` (drift check, 0 of 3 drift) |

## 3. Version-sensitive features used by the application

| Feature | Where | Minimum version |
|---|---|---|
| Enforced `CHECK` constraints (98) | `scripts/schema_mysql.sql`, migrations | **8.0.16** |
| `INSERT ... AS new ON DUPLICATE KEY UPDATE` row alias | `l7_governance/settings_service.py` | **8.0.19** |
| `INDEX` optimizer hint (ignored by older servers; performance only) | `routers/opportunities.py` | 8.0.20 |
| `JSON_OVERLAPS` | `l6_agency/tool_registry.py` (programme search), `routers/opportunities.py` (geo filter) | **8.0.17** |
| `LEFT JOIN LATERAL` | `l4_reasoning/ml_scorer.py` (training rows) | 8.0.14 |
| Expression defaults `DEFAULT (UUID())`, `DEFAULT (JSON_ARRAY())` | schema | 8.0.13 |
| `JSON_TABLE` | `routers/dashboards.py` (geo), `routers/opportunities.py`, `routers/proposals.py`, `l3_memory/interaction_ingest.py` | 8.0.4 |
| `FOR UPDATE SKIP LOCKED` | `l3_memory/memory_manager.py` (TTL job) | 8.0.1 |
| `utf8mb4_0900_ai_ci` | all tables | 8.0.1 |
| Generated columns (5) | `document.v_latest_doc` and others (partial-uniqueness emulation) | 5.7 |
| `INSERT … ON DUPLICATE KEY UPDATE x = VALUES(x)` (29 sites) | upserts | works on 8.0 and 8.4; **deprecated since 8.0.20** (warning 1287). Must move to the row-alias form (`AS new … new.x`, 8.0.19+) before any MySQL 9.x upgrade |
| `WITH RECURSIVE` | **verification scripts only** (`verify_mysql_runtime.py`, `benchmark_mysql_slos.py`, `rehearse_data_migration.py`) | 8.0.1 |

**Correction to the 2026-11-07 technical proof report §3:** application graph traversal does **not** use recursive CTEs. `cortex/l2_representation/graph_traversal.py` runs a bounded per-hop BFS (indexed `IN` lookups on `from_entity`/`to_entity`, frontier cap 20 000). Recursive CTEs are used only by the scripts above.

Not used (checked): `JSON_VALUE`, `JSON_SCHEMA_VALID`, `MEMBER OF`, `INTERSECT`/`EXCEPT`, window functions, `GET_LOCK`, `SET PERSIST`, `REGEXP_*`, invisible columns.

## 4. 8.4-specific operational notes

- **Authentication:** 8.4 disables `mysql_native_password` by default. asyncmy and PyMySQL both support `caching_sha2_password`. Over a non-TLS connection that plugin needs RSA key exchange or a cached login; **production must use TLS** (SEC-P), which removes the issue.
- `default_authentication_plugin` was removed in 8.4. Don't copy an 8.0 `my.cnf` that sets it, or the server won't start.
- Trigger creation needs `SUPER` or `log_bin_trust_function_creators=1` when binary logging is on (it must be on for PITR). The CI and test servers use root for this. **The DBA must decide how the production migration role is allowed to create the audit and outbox triggers** (INFRA-1).

## 5. Still to do

| ID | Item | Owner | Dependency |
|---|---|---|---|
| VC-1 | Confirm the production server version (8.4 LTS recommended) | DevOps / DBA | B2 |
| VC-2 | If production will be 8.0, run unit, integration, runtime and drift on that exact 8.0.x | Engineering | VC-1, a test host with ≥ 4 GB free |
| VC-3 | Compare the production server variables with §2 (time zone, `sql_mode`, collation, `lower_case_table_names`, binlog, trigger privilege) | DBA | B2 (blocker VER-6) |
| VC-4 | Replace `VALUES(col)` with the row-alias form (not needed for 8.4; needed before 9.x) | Engineering | none (low priority) |
