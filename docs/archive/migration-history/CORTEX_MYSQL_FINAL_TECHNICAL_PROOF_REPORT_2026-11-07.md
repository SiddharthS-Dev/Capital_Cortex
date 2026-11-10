# Capital Cortex — PostgreSQL 16 → MySQL 8.4 Technical Proof Report, 2026-11-07

> **Historical record (dated 2026-11-07).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


**For:** Project Lead, DevOps, DBA, developers.
**Companion documents:**
- `CORTEX_MYSQL_TEST_CASE_EVIDENCE_2026-11-07.md`: every test and run, with commands and logs.
- `CORTEX_MYSQL_FINAL_BLOCKER_REGISTER_2026-11-07.md`: owners and next actions.
- `CORTEX_MYSQL_TEAMS_HANDOVER_SUMMARY_2026-11-07.md`: short version.

**Statuses:**
- **PASS:** executed with evidence.
- **FAIL:** executed and failed.
- **BLOCKED:** resource or external dependency.
- **NOT RUN:** not attempted.

## 1. Executive summary

- **Developer-side validation: PASS on 2026-11-07, between 18:36 and 18:58 IST.** Results:
  - Unit suite **584 passed / 0 failed / 0 skipped** on `cortex_unit`.
  - Integration suite **20 passed / 0 failed / 3 skipped by design** (PostgreSQL-only AGE/pgvector checks) on `cortex_integration`.
  - Runtime verification on `cortex` **passed**, and removed its own test rows.
  - **No schema drift**: `cortex`, `cortex_integration` and `cortex_unit` are all at `m0004_reconcile_legacy_layouts`.
- **Defects:**
  - **High (H1–H12):** all 12 fixed. 10 are verified at test level, including route tests for H3, H4, H9 and H7. H8 and H11 are verified at decode level only.
  - **Medium (M1–M10):** 9 of 10 verified. **M6** is fixed, but its new run-level test hasn't run yet.
- **Coverage:** all 8 modules that previously had no MySQL test now have one (46 tests), and every one passed.
- **Not yet revalidated:** one new test (M6) and a formatting-only change to two files, both made after the last run. Re-running them is **BLOCKED**: the workstation is at 88–97 % RAM with 31 containers, mostly AIOT and DAPRO, which must not be stopped.
- **Not complete:**
  - PERF-1 and PERF-2;
  - the frontend production build;
  - browser E2E (last run 2026-11-04: 1 failure, caused by PERF-2);
  - CI (never run; waits on GIT-1, which is postponed);
  - credential rotation (SEC-1/2).
- **Production cutover: BLOCKED, not approved.** It needs B1, B2, INFRA-1, SEC-P, ARCH-1 and ARCH-3, then the **B3** go/no-go.

## 2. Migration scope

The scope is the Capital Cortex backend's move from PostgreSQL 16 (with Apache AGE and pgvector) to MySQL 8.4 (InnoDB, utf8mb4). It covers:
- the application (FastAPI, layers L1–L8, `platform_core`);
- Alembic migrations (`migrations_mysql`, m0001–m0004);
- the seed and demo data;
- the ETL `scripts/migrate_pg_to_mysql.py`;
- backup and restore (`scripts/backup_mysql.py`, AES-256-GCM);
- the runtime and drift tooling;
- Keycloak on MySQL;
- the CI workflow.

**Out of scope until approved:** production cutover, production credentials, and removal of the PostgreSQL code (ARCH-4).

## 3. Architecture changes (PostgreSQL → MySQL)

| Area | PostgreSQL 16 | MySQL 8.4 implementation |
|---|---|---|
| Driver and session | asyncpg/psycopg | asyncmy (`mysql+asyncmy`). Aware datetimes are bound as UTC (M1). One session layer serves both dialects (`platform_core/db/session.py`) |
| JSON | `jsonb` (decoded by the driver) | `JSON` (returned as text). Decoded centrally by `json_obj`; `row()` decodes booleans (M8) and emits ISO datetimes with an offset (M9) |
| Timestamps | `timestamptz` | `DATETIME(6)` holding UTC; offset added on output (M9, M10) |
| Booleans | `boolean` | `TINYINT(1)`, mapped back to `bool` through `BOOL_COLUMNS`, which a test keeps in step with the schema (M8) |
| Upsert / ignore | `ON CONFLICT DO NOTHING/UPDATE` | `insert_or_skip_duplicate` (skips only 1062; other constraint errors raise: M2), plus `ON DUPLICATE KEY UPDATE` |
| JSON merge | `jsonb \|\|` | Python shallow merge (`merge_run_output`), because `JSON_MERGE_PATCH` drops null keys (M4) |
| Graph | Apache AGE (Cypher) | relational `entity` / `relationship_edge` tables with recursive CTEs |
| Vectors | pgvector HNSW | packed IEEE-754 BLOB plus an in-memory exact index (`platform_core/db/vector.py`). The production strategy is decision ARCH-2 |
| Search | `tsvector` | `FULLTEXT` + `LIKE` (PERF-1 decision open) |
| Audit chain | advisory lock | `SELECT … FOR UPDATE` mutex; hash chain verified (R1) |
| Identity | Keycloak on PostgreSQL | Keycloak on MySQL (separation is decision ARCH-1) |

## 4. MySQL compatibility defects

### 4.1 High (H1–H12)

| ID | Area | Status | Evidence (test IDs) |
|---|---|---|---|
| H1 | idempotency replay | PASS | H1-01 |
| H2 | financial approval role lists and authorization | PASS | H2-01 to H2-04 |
| H3 | recommendation edit (PATCH) | PASS, route level | H3-01 to H3-05, HX-01 |
| H4 | recommendation approval | PASS, route level | H4-01 to H4-07, HX-01 |
| H5 | agent run stance and confidence | PASS | H5-01 |
| H6 | dashboard deadline with naive datetime | PASS | H6-01, IT-01 |
| H7 | contact e-mails, timeline sort | PASS, route level | HX-01, JX-06, DR-10 |
| H8 | tool registry JSON fields | PASS at decode level; value-level test **NOT RUN** (VER-3) | HX-01 |
| H9 | ML scorer, active-model branch | PASS, route level | H9-01 to H9-07 |
| H10 | memory `ttl_job` archive | PASS, function level | H10-01 |
| H11 | data-room and proposal `dd_tags` | PASS at decode level; value-level test **NOT RUN** (VER-3) | HX-01; exercised without value assertions by IT-06 |
| H12 | demo seed safety | PASS | H12-01, IT-20 |

### 4.2 Medium (M1–M10)

The brief asked for M1, M2, M3, M5, M6 and M7 to be checked against existing evidence. The result: M1, M2, M3, M5 and M7 each have a dedicated database test in `test_mysql_medium_defects.py`, and they **passed in run U2**. M6 had no run-level test until today.

| ID | Defect | Fix location | Status | Evidence |
|---|---|---|---|---|
| M1 | non-UTC offsets stored as wall-clock time | MySQL bind hook in `platform_core/db/session.py` | PASS | M1-01, AL-03 |
| M2 | `INSERT IGNORE` hid FK, CHECK and NOT NULL errors | `insert_or_skip_duplicate` at 6 sites | PASS | M2-01, M2-02, AL-04, II-05, DR-04 |
| M3 | ingestion race → 1062 | `l1_perception/ingestion.py` | PASS | M3-01 |
| M4 | `JSON_MERGE_PATCH` drops null keys | `merge_run_output` | PASS | M4-01, M4-02 |
| M5 | special characters in a JSON-path key | `l7_governance/refs.py` | PASS | M5-01 |
| M6 | retention double-encodes `signal.raw` | `retention.py`: `json_obj` before `json.dumps` | **BLOCKED**: fix in code; test M6-01 written but not executed | VER-1 |
| M7 | settings version increment not atomic | `settings_service.py` | PASS | M7-01 |
| M8 | booleans as 0/1 in the API | `jsonutil.row` + `BOOL_COLUMNS` | PASS | M8-01, M8-02, M8M9-01 |
| M9 | datetimes without an offset in the API | `jsonutil.jsonable` | PASS | M9-01, M8M9-01 |
| M10 | calendar/ICS timezone | `routers/calendar.py` | PASS | M10-01 |

## 5. Schema and migration evidence

| Check | Result | Date | Evidence |
|---|---|---|---|
| Alembic head | `m0004_reconcile_legacy_layouts` on `cortex`, `cortex_integration`, `cortex_unit` | 2026-11-07 | D1 |
| Drift (tables, columns, indexes, FKs, uniques, CHECKs, triggers) | **0 of 2 databases drift** from `cortex_unit` | 2026-11-07 | D1 |
| m0002 (legal hold), m0003 (list indexes), m0004 (legacy reconcile) | applied; the m0004 ENUM correction on `cortex` was done 2026-11-05 under backup `20261105T093537Z` | 2026-11-05 / 07 | 2026-11-05 report, D1 |
| `cortex_demo` | m0004, no drift | **2026-11-04 only**: re-check BLOCKED (VER-5) | closure register |
| Constraints in action | provenance, evidence, outcome label, band, audit immutability, outbox trigger | 2026-11-07 PASS | IT-11 to IT-17 |
| Production schema configuration | **NOT RUN** (VER-6; needs B2) | – | – |

## 6. Runtime validation

`scripts/verify_mysql_runtime.py` on `cortex`, 2026-11-07 18:44 IST: **PASS**. The checks covered:
- MySQL 8.4.13 over asyncmy, with 50 tables;
- `/healthz` 200 and a live probe;
- a transactional write and read;
- recursive-CTE graph traversal;
- a 1024-dim vector BLOB round trip;
- the audit-chain mutex, with 1060 records verified;
- a simulated restart.

**Cleanup verified:** the run removed its own 6 rows. Its 1 audit record is kept, because the audit log is append-only. Details are in evidence §4.

## 7. Unit tests

| Run | Result | Date | Note |
|---|---|---|---|
| U1 | 582 passed / **2 failed** | 2026-11-07 18:36 | 2 stale expectations in tests added on 2026-11-06. **No application defect** (evidence §5) |
| U2 | **584 passed / 0 failed / 0 skipped** | 2026-11-07 18:58 | after the 2 test corrections |

The MySQL-specific files in U2 hold 94 tests:
- `test_mysql_json_datetime_compat.py`: 16;
- `test_mysql_route_regressions.py`: 19;
- `test_mysql_medium_defects.py`: 14 (15 now, with M6-01);
- `test_mysql_module_coverage_l8.py`: 18;
- `test_mysql_module_coverage_memory_drafts.py`: 28.

## 8. Integration tests

I1, 2026-11-07 18:49: **20 passed / 0 failed / 3 skipped** (AGE ×2 and pgvector HNSW, which are PostgreSQL-only by design).

The 2026-11-03 figure of "21 passed" is explained in evidence §3.5. It can't be reproduced; 23 tests are collected (20 + 3), and no test was lost.

## 9. Route-level tests

H3 (5), H4 (7) and H9 (7) route tests, plus the H7 follow-up route test: **all PASS** (U2). They cover:
- success;
- invalid body (422);
- missing record (404);
- authorization (403);
- MySQL storage semantics (JSON document, SQL NULL, trigger invalidation).

## 10. The eight modules

| Module | Tests | Status |
|---|---|---|
| Memory consolidation | 6 | PASS |
| Interaction ingest | 6 | PASS |
| Recall | 5 | PASS |
| Drafts (incl. outbox routes) | 11 | PASS |
| Compliance report | 4 | PASS |
| Entities routes | 5 | PASS |
| Forecasts routes | 4 | PASS |
| Alerts service | 5 | PASS |

The tests cover the same categories as the route tests, plus:
- database constraints;
- MySQL-specific behaviour (`GROUP_CONCAT` length, UTC comparisons, JSON/boolean decoding, duplicate vs constraint errors).

## 11. Frontend and E2E

| Check | Status | Last executed |
|---|---|---|
| Vitest (6), ESLint, `tsc -b --noEmit` | PASS (historical); **NOT RUN today** | 2026-11-04 15:08 |
| Production build (`vite build`) | **BLOCKED** (esbuild out of memory ×2) | 2026-11-04 |
| Browser E2E | **FAIL**: 5 passed / 1 failed (Phase 1 "Key figures" over its 5 s budget, PERF-2) / 2 admin-only skips; rerun **BLOCKED** | 2026-11-04 15:35 |

`apps/web/src` and `apps/web/e2e` haven't changed since 2026-11-04 23:14.

## 12. Performance

| ID | Finding | Status |
|---|---|---|
| PERF-2 | `GET /v1/dashboards/executive` ~1.7 s server-side (3.6 s under load). Its ~8 sequential steps include 3 forecast scenarios. The dominant step hasn't been measured | **NOT RUN**: profiling needs the API and memory headroom |
| PERF-1 | Search 6.1 s warm / 13.4 s cold against a < 2 s target (`cortex_bench_1m`). FULLTEXT-only 1.2 s; first page 0.26 s | **NOT RUN**: n-gram prototype `scripts/perf1_search_options.py` exists (measures timing, recall and precision against current results) but has never been executed. **Decision: Project Lead** |

Recommendation for PERF-1: run the prototype, then decide between:
- **A:** FULLTEXT only;
- **B:** A plus FULLTEXT on the counterparty name;
- **C:** n-gram FULLTEXT;
- **D:** keep the current behaviour.

Base the decision on measured recall and precision. No search semantics will change without approval.

## 13. Security

| Item | Status |
|---|---|
| `.env` git-ignored and untracked | PASS (inspection, 2026-11-07) |
| No committed credential fallbacks in runtime or scripts (SEC-3/4) | PASS (2026-11-03, tests in `test_mysql_compose_security.py`; part of U2) |
| `scripts/smoke.py` reads credentials only from the environment or `.env` (rotation prerequisite) | PASS (inspection, 2026-11-07) |
| Evidence logs contain none of the 14 `.env` secret values | PASS (scan, 2026-11-07) |
| **SEC-1/2**: credentials in the public GitHub history | **NOT RUN**: rotation awaits approval (see the blocker register) |
| Secret scan (gitleaks) | **NOT RUN**: tool not installed |
| SEC-P: production TLS, secret store, backup key | **BLOCKED** (DevOps) |

**Credential types exposed** (no values are reproduced here):
- PostgreSQL dev password;
- Keycloak dev admin;
- 3 Keycloak client secrets;
- a dev user password;
- the smoke TOTP seed.

## 14. Build and CI

| Check | Status |
|---|---|
| Ruff lint | PASS (2026-11-07) |
| Ruff format | PASS: 235 files formatted (2026-11-07) |
| Backend production start-up, worker health | **BLOCKED** (services not started) |
| CI (`.github/workflows/ci.yml`: lint, unit, mysql-schema, integration, contract, eval, build-scan-smoke, deploy) | **NOT RUN**: never executed; needs a push, and GIT-1 is postponed |

## 15. Remaining blockers and owners

See `CORTEX_MYSQL_FINAL_BLOCKER_REGISTER_2026-11-07.md`. In summary:
- **Engineering:**
  - VER-1 to VER-5;
  - PERF-2;
  - PERF-1 measurement;
  - FE-1, FE-2, E2E, SVC;
  - RB-1.
- **Workstation owner:** ENV-1, ENV-2, OPS-1.
- **DevOps:** CI-1, CI-2, B1, B2, INFRA-1, SEC-P.
- **Project Lead:**
  - PERF-1 decision;
  - ARCH-1 to ARCH-4;
  - B3.
- **Owner decision:**
  - GIT-1 (postponed);
  - SEC-1/2 rotation approval.

## 16. Production readiness

| Gate | Status |
|---|---|
| Application on MySQL (unit, integration, runtime, schema) | PASS (local, 2026-11-07) |
| All High and Medium defects verified | 19 of 22 at test level; H8/H11 decode-level only; M6 test pending (BLOCKED) |
| Performance targets (PERF-1, PERF-2) | NOT RUN / decision pending |
| Frontend build and E2E | BLOCKED / FAIL (2026-11-04) |
| CI green | NOT RUN |
| Credential rotation | NOT RUN (approval) |
| Production backup, environment, TLS, secrets (B1, B2, INFRA-1, SEC-P) | BLOCKED (DevOps) |
| Architecture decisions (ARCH-1 to ARCH-4) and rollback release (RB-1) | BLOCKED (Project Lead) |
| **Go/no-go (B3)** | **NOT APPROVED** |

**Verdict:** the MySQL application is functionally verified on the local test server. **The migration is not production-complete.** Cutover stays pending until the external approvals and infrastructure above are in place.

## 17. External approvals required

- **DevOps:**
  - B1 authorised production PostgreSQL backup;
  - B2 production MySQL environment and access;
  - INFRA-1 (sizing, PITR, monitoring, Keycloak HTTPS);
  - TLS;
  - secret store;
  - backup encryption key custody;
  - a dedicated test database server;
  - a CI runner.
- **Project Lead:**
  - B3 go/no-go;
  - PERF-1 search semantics;
  - ARCH-1 Keycloak database;
  - ARCH-2 vector strategy;
  - ARCH-3 rollback window and pinned release;
  - ARCH-4 PostgreSQL code removal timing.
- **Owner:**
  - SEC-1/2 rotation;
  - GIT-1 (postponed).

The cutover and rollback procedure is in `CORTEX_MYSQL_CUTOVER_RUNBOOK.md` and `CORTEX_PRODUCTION_MIGRATION_ACTION_PLAN.md` (repository root). This report doesn't alter them.
