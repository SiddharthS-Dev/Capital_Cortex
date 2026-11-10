# Capital Cortex — MySQL 8.4 Final Readiness Report

> **Historical record (dated 2026-10-30).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


**Date:** 2026-10-30 · **Branch:** `feature/changes-login` · Evidence: `CORTEX_MYSQL_FINAL_TEST_REPORT.md`

## Update 2026-11-03 (supersedes everything below where it differs)

| Measure | Value | Basis |
|---|---|---|
| **Overall MySQL migration** | **80%** (was 77%) | Same ten equal-weight areas as `CORTEX_MYSQL_FINAL_STATUS_SUMMARY.md`. Raised: schema 85→92, tests 80→92, Docker 70→75, auth 90→92, backup 60→62 |
| **Application runtime on MySQL** | **95%** | Every service (API, worker, scheduler, jobs, Keycloak) runs on MySQL with no PostgreSQL connection. The dev default database `cortex` still has one drifted ENUM (MB-11). PostgreSQL branches are kept for rollback (MB-23) |
| **Demo readiness** | **97%** — READY | Smoke 10/10 after a restart on the current code. Not done: a browser click-through |
| **Production readiness** | **42%** — NOT READY | 5 of 12 gates (unchanged): no production backup, access, staging, monitoring or approval, and the work is uncommitted |

**Performance (MB-19).** Not re-measured today; the latest evidence is the interleaved 2026-11-02 run at 200k opportunities (p50/p95/p99, ms):

| Scenario | Before | After |
|---|---|---|
| Radar list | 41,052 / 58,415 / 63,891 | 10,600 / 18,694 / 19,315 |
| Recent list | 22,269 / 27,252 / 28,762 | 7,868 / 9,250 / 9,579 |
| Search | 33,252 / 45,774 / 48,606 | 23,967 / 28,102 / 29,221 |

The 2 s target is **not met**. What remains needs product decisions, not more indexing:
- facets aggregate the whole table on every call;
- `LIKE '%q%'` search scans everything.

**Is Cortex MySQL-first?**
- **Yes for runtime:** default config, every service, all tests.
- **PostgreSQL is still required** as the source for migration tooling and as the rollback stack.
- **No production data has been migrated.**
- **Cutover is not authorised.**

**Branch and commit plan (MB-22; nothing committed).** 175 entries. Proposed: a new branch `feature/mysql-migration` from the current HEAD, with commits in this order:
1. Schema and migrations: `scripts/schema_mysql.sql`, `migrations_mysql/`, `platform_core/db/*`, `platform_core/audit/chain.py`.
2. Dual-path application SQL (`cortex/*`, `seed/*`).
3. Infra and security: `infra/docker-compose.mysql*.yml`, `infra/mysql/`, `.env.example`, `.gitattributes`, `make.ps1`, `Makefile`.
4. Tooling: `scripts/migrate_pg_to_mysql.py`, `secure_connect.py`, `backup_mysql.py`, `check_mysql_schema_drift.py`, benchmarks, `rehearse_data_migration.py`, `verify_mysql_runtime.py`.
5. Tests.
6. Reports and runbook.

Also:
- **Separate branch:** the funding-ingestion work (`cortex/l1_perception/*`, `config/adapters/*`, `apps/web/src/pages/{Sources,Radar}.tsx`, `AppShell.tsx`, `tests/unit/test_live_ingestion.py`).
- **Leave out (generated):** `dd_out.txt`, `dd_err.txt`, `postgresql_dependency_*.csv`, both `rehearsal_reconciliation_report.json`, and `package-lock.json` (check with the web owner first).
- **Secrets scan:** the only hits are the documented dev-realm values (D-013); `.env` is git-ignored and untracked.

## Update 2026-10-31 (supersedes the verdicts below where they differ)

| | Verdict |
|---|---|
| **Demo readiness** | **DEMO READY.** Disk risk resolved (C: 14.6–16 GB free); demo restarted on the fixed code; smoke 10/10. The remaining limitations are the empty screens and the word-overlap vector search listed below |
| **Production migration readiness** | **PARTIALLY READY.** Code and stack now verified (unit 299/299, integration 20 pass + 3 PostgreSQL-only skips, isolated production stack smoke 10/10, 1M benchmark with 0 errors), but blocked by **no authorised real-data dump** and an **unknown production location**; 4 decisions pending |

Details for all 24 blockers: `CORTEX_MYSQL_BLOCKER_CLOSURE_REPORT.md`.
- **Fixed since the verdicts below:** the audit-chain duplicate sequence under concurrency; vector memory, fetch and search; single-scan facets; the production stack's binlog trigger privilege.
- **Proven since then:** the production stack runs end to end, and the Keycloak user export/import procedure works.
- **Corrected:** the earlier "3 shell scripts have CRLF" finding was a false positive (Git Bash `grep` quirk). LF is now pinned by `.gitattributes`.

**Decisions needed for production:**
1. Opportunity facets and search at 200k+ (32–37 s under 8 concurrent clients).
2. Separate Keycloak and app MySQL instances, or schedule batch windows.
3. Vector index capacity (143 s cold build, about 2.7 GB per API process at 200k).
4. Commit and branch plan.

## Verdicts (2026-10-30)

| | Verdict |
|---|---|
| **Demo readiness** | **DEMO READY WITH DOCUMENTED LIMITATIONS** |
| **Production migration readiness** | **PARTIALLY READY** |

A working demo does **not** mean the production migration is complete.

### Demo limitations to manage

1. **Disk space (highest risk).** C: had **1.2 GB free** at the last check. Docker Desktop stopped every container earlier
   today when the disk filled. Free at least 5 GB before the demo. Reclaiming Docker images or build cache deletes them
   and needs your decision; nothing was deleted.
2. **The UI was not click-tested in a browser** in this session (no browser automation available). Its login flow and
   every API call it makes were verified over HTTP. Rehearse the click-through once by hand.
3. Seeded data has no alerts, approvals, proposals, board reports, forecast runs or data-room documents; those pages are empty.
4. MinIO and the observability stack are not running: no file uploads or exports, no Grafana.
5. Vector search uses the default local word-overlap embedder (`hash-tf-1024-v1`): it matches shared words, not meaning.
6. Privileged users (`dev-admin`) must enrol TOTP at first login; use `dev-analyst` and `smoke-auditor`, or enrol tonight.

## Acceptance criteria (section 21)

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | MySQL 8.4 starts | **Met** | 8.4.13 healthy via `docker-compose.mysql-test.yml`; start script |
| 2 | Application connects to MySQL | **Met** | `/readyz` 200 (MySQL + Redis); `DATABASE_URL=mysql+asyncmy://…/cortex_demo` |
| 3 | Schema available | **Met** | `alembic -n mysql upgrade head` → `m0001_mysql_baseline`; 49 tables + 4 triggers |
| 4 | FastAPI starts | **Met** | "Application startup complete"; started by the script from cold |
| 5 | Frontend builds and runs | **Met** | `tsc --noEmit` exit 0; `vite build` exit 0; dev server on 5373 proxies the API |
| 6 | Keycloak authentication | **Met** | Real code + PKCE login for `dev-analyst` (password) and `smoke-auditor` (password + TOTP); Keycloak runs on MySQL; Keycloak unit suite 10/10 |
| 7 | OPA authorization | **Met** | Allows (analyst reads) and denies (auditor → `system:ping` 403) both verified |
| 8 | Main APIs work | **Met** | Workflow check 29/29; GET sweep 50 routes, 0 errors |
| 9 | Primary workflows with demo data | **Met** (read paths), integration-tested (write paths) | 200 opportunities through the real pipeline; dashboards, radar, detail, relationships, recall; phase 1–3 write flows in the integration suite |
| 10 | Graph where exposed | **Met** | `/v1/graph/stats`, neighbourhood depth 2, 2-hop paths; integration `test_neighbourhood_and_paths_match_cypher` |
| 11 | Vector search where exposed | **Met**, with the limit noted above | Copilot retrieval returned 5 matches from the MySQL BLOB vector search; the no-overlap question correctly returned none |
| 12 | Audit functionality | **Met** | Chain verified (35 records); append-only triggers verified; bus → worker → audit |
| 13 | No PostgreSQL connection in the MySQL profile | **Met** | 0 PostgreSQL references in the API and worker logs; no PostgreSQL container running for Capital Cortex |
| 14 | Repeatable startup + troubleshooting | **Met** | `CORTEX_MYSQL_DEMO_START.ps1` (cold start and idempotent rerun, exit 0); `CORTEX_MYSQL_LIVE_DEMO_GUIDE.md` |
| 15 | Production database / volume untouched | **Met** | `capital-cortex_pgdata` not mounted, started or modified; no production container exists on this host; no prune / `down -v` / `volume rm` run |

## Production migration: why "partially ready"

| Area | State |
|---|---|
| Application code on MySQL | Done and verified: unit, integration, smoke and workflow tests (2 API defects fixed tonight) |
| Schema versioning | Done: `migrations_mysql/` (`alembic -n mysql`) |
| ETL + reconciliation | Done and fail-closed; physical rehearsal passed on **synthetic** data |
| Production compose stack (`docker-compose.mysql.yml`) | Three start-up blockers fixed (PostgreSQL migrations on MySQL; missing Keycloak database; `depends_on` a disabled `postgres`); the merged config validates. **Never started**: needs an API image rebuild and Vault, MinIO and observability images (not possible tonight at 1.2 GB free) |
| **Real-data rehearsal** | **Blocked**: no authorised, sanitised PostgreSQL dump |
| **1M-record benchmark** | **Not run**: the harness doesn't exercise the app's real vector search (an in-memory index per tenant, about 4 GB at 1M) or graph BFS; it needs extending first, plus disk space |
| Production PostgreSQL location | **Unknown**: not on this host |
| Git | 80 modified / 55 untracked, uncommitted; 3 shell scripts carry CRLF line endings in the working copy (see the Git review) |
| Cutover | Approval-gated runbook: `CORTEX_MYSQL_CUTOVER_RUNBOOK.md` |

### Remaining blockers, in order

1. Free disk space on C: (demo-critical).
2. Review and commit the work on a dedicated branch (`CORTEX_MYSQL_GIT_REVIEW_REPORT.md`).
3. Obtain an authorised, sanitised production dump and run the real-data rehearsal.
4. Extend and run the scale benchmark (vector search + graph).
5. Start the production MySQL compose stack once in staging (image rebuild).
6. Confirm the production PostgreSQL location, then a business go/no-go for cutover.
