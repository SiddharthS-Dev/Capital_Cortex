# Capital Cortex: PostgreSQL 16 → MySQL 8.4 Technical Proof Report

**Date:** 2026-11-07 (session 22:25–00:00 IST).
**For:** Project Lead, DevOps, DBA, Engineering.
**Builds on:** the earlier 2026-11-07 technical proof (architecture, defect history), which stays valid except for the correction in §6.

**Companions:**
- `CORTEX_MYSQL_TEST_EVIDENCE.md` (T1–T12)
- `CORTEX_MYSQL_BLOCKER_REGISTER.md`
- `CORTEX_MYSQL_PERFORMANCE_REPORT.md`
- `CORTEX_MYSQL_VERSION_COMPATIBILITY.md`
- `CORTEX_MYSQL_SECURITY_READINESS.md`
- `CORTEX_MYSQL_PRODUCTION_MIGRATION_RUNBOOK.md`
- `CORTEX_MYSQL_ROLLBACK_RUNBOOK.md`

## 1. Summary

- **All 22 MySQL compatibility defects are verified at test level.** H8 and H11 now have value-level tests. M6 now has its run-level test plus an integrity test. A mutation check shows the new tests fail with the fix reverted.
- **Local validation is green:**
  - unit 596/0/0 on the final code;
  - ruff clean;
  - integration 20 passed + 3 justified skips;
  - runtime PASS;
  - no drift on 4 databases;
  - Vitest, ESLint, `tsc` clean;
  - **production build succeeds**;
  - **E2E 6/0/2**.
- **PERF-2 is fixed on measured evidence:** 6.6× at 200k opportunities, identical payload. **PERF-1 is not measured** (host memory) and needs a Project Lead decision.
- **Rollback:** the current code **cannot run on PostgreSQL** (8 of 21 fail), but the **pre-migration release passes 21/21** on PostgreSQL. Rollback must be by release (ARCH-3).
- **Production: not started, not approved.** B1, B2, INFRA-1, SEC-P, SEC-1/2, ARCH-1/3 and B3 are open. CI has never run (GIT-1 postponed).

## 2. Defects (H1–H12, M1–M10)

| Group | Status | New evidence this session |
|---|---|---|
| H1–H7, H9, H10, H12 | PASS (test level, 11-07 U2) | re-confirmed in T3 |
| **H8** tool registry | **PASS, value level** | `eligibility_check` gap lists field names; `investor_search` matches stages by element (`"series"` is no longer a false match); `terms_compare` peer median = 0.07 over 3 probe peers; `checklist_map` coverage equals MySQL `JSON_OVERLAPS` for every item (T1, T2) |
| **H11** data room / proposal | **PASS, value level** | the package manifest stores `dd_tags` as a JSON `ARRAY` (not a string), in the database and in the zip; proposal DD items map documents to exactly the right checklist item (T1, T2) |
| M1–M5, M7–M10 | PASS (11-07 U2) | re-confirmed in T3 |
| **M6** retention | **PASS, run level** | archived object = original document; cold key `s3://…/signals/<id>.json`; row `raw` cleared; dry run writes nothing; legal-hold flag and targeted holds are not archived (T1) |

## 3. Code changed this session

| File | Change | Why |
|---|---|---|
| `cortex/l5_strategy/pipeline_engine.py` | MySQL `weighted_pipeline`: one grouped scan, exact `Decimal` roll-up | PERF-2: the CTE was inlined into 5 `UNION ALL` branches (6 table scans) |
| `cortex/l8_actuation/api/routers/dashboards.py` | `_mix_mysql`: one covering-index scan for the active count, funnel, class mix and band mix (MySQL branch) | PERF-2: 4 scans, each reading full rows through the wrong index |
| `tests/unit/test_mysql_h8_h11_values.py` (new), `test_mysql_perf2_dashboard.py` (new), `test_mysql_medium_defects.py` (+1 test) | tests | VER-3, VER-1, PERF-2 |
| `docs/…` | the 10 documents of the brief | – |

PostgreSQL code paths are unchanged. No schema or migration change. No existing test expectation was changed.

## 4. Schema and data

| Check | Result |
|---|---|
| Revisions | `m0004_reconcile_legacy_layouts` on `cortex`, `cortex_unit`, `cortex_integration`, `cortex_demo` (T4) |
| Drift (tables, columns, indexes, FKs, uniques, CHECKs, triggers) | none (T4) |
| Constraints in action | integration T5 (provenance, evidence, outcome label, band, audit immutability, outbox trigger) |
| JSON / datetime / boolean | value-level tests (T1) + 11-07 suites |
| Audit chain | 1061 records verified (T7) |
| Collation | uniform `utf8mb4_0900_ai_ci`, except `cortex_integration.alembic_version` (harmless) |
| Production data migration | **NOT RUN** (B1/B2); ETL tooling verified on rehearsal databases earlier (cutover runbook §B) |

## 5. Versions

Tested on **MySQL 8.4.13 only**. The feature floor is 8.0.17 (enforced `CHECK` needs 8.0.16, `JSON_OVERLAPS` 8.0.17). 8.0 is **not tested**, and MySQL 8.0 is past end of life. Recommendation: 8.4 LTS. See the version doc.

## 6. Correction to the 11-07 report

§3 there says graph traversal uses recursive CTEs. **The application uses a bounded per-hop BFS** (`l2_representation/graph_traversal.py`). Recursive CTEs appear only in the verification and benchmark scripts. The runtime check "traversed via Recursive CTE" (T7) therefore tests MySQL capability, not the application's traversal code; the application's traversal is covered by the integration suite (T5).

## 7. Milestones

| Milestone | Status |
|---|---|
| 1. Code implementation complete | **Yes, for the MySQL target.** Open: PERF-1 (decision), FE-3 (advisory), RB-3 (decision on PostgreSQL capability) |
| 2. Local technical validation complete | **Substantially.** Open: PERF-1 measurement, `smoke.py` on the full stack, 2 admin E2E flows, CI (GIT-1) |
| 3. Production infrastructure ready | **No** (B1, B2, INFRA-1, SEC-P) |
| 4. Production migration executed | **No** (needs 3 + B3) |
| 5. Production acceptance complete | **No** |
