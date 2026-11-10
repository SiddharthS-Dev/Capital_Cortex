# Capital Cortex — MySQL 8.4 Final Implementation Report

> **Historical record (dated 2026-10-30).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


**Dates:** 2026-10-30 → 31 · **Branch:** `feature/changes-login` · Companion reports: `CORTEX_MYSQL_FINAL_TEST_REPORT.md`,
`CORTEX_MYSQL_FINAL_READINESS_REPORT.md`, `CORTEX_MYSQL_CURRENT_STATE_AND_REMAINING_WORK_REPORT.md` (the audit record).

## Update 2026-10-31: changes made while closing blockers

| File | Change | Why |
|---|---|---|
| `platform_core/audit/chain.py` | MySQL: read the chain head with `FOR UPDATE` | Duplicate `seq` (500) under concurrent writes: REPEATABLE READ snapshot |
| `platform_core/db/vector.py` | `fit()` decodes BLOBs straight to float32; search = one matrix-vector product with precomputed norms (scikit-learn removed from this path); fetch `ORDER BY e.entity_id` | Memory 9× → about 1×; search 2.57 s → 77 ms; cold build 577 s → 143 s at 200k |
| `cortex/l8_actuation/api/routers/opportunities.py` | MySQL facets from one `GROUP BY` | Was 5 full scans per list request |
| `infra/docker-compose.mysql.yml` | `--log-bin-trust-function-creators=1` | `migrate` failed with error 1419 (binary logging on) |
| `.gitattributes` (new) | `*.sh`, `*.envsh` → `eol=lf` | `core.autocrlf=true` would write CRLF on checkout |
| `scripts/seed_mysql_load.py` | Real per-row embeddings, `org_id`, 50k chained audit rows | The benchmark data was unrepresentative |
| `scripts/benchmark_mysql_app_paths.py` (new) | Application-path benchmark (in-process and HTTP, concurrency, CPU and memory) | The old harness timed raw SQL only |
| `CORTEX_MYSQL_DEMO_START.ps1` | `-AllowLowDisk`; 45 s worker readiness poll | Start blocked at < 1 GB; false worker warning |
| Tests | `test_mysql_invariants_and_mutex.py`, `test_mysql_vector.py` (2), `test_mysql_router_sql.py`, `test_mysql_schema_versioning.py` (bytes check + new test + binlog assert) | Regression tests for each fix |

Operations: `docker builder prune -af` (approved; 3.825 GB). Created the isolated databases `cortex_bench_1m` and the stack-test project. Nothing was deleted.

## 1. Capabilities used

| Looked for | Found | Used |
|---|---|---|
| Project `CLAUDE.md` / `.claude/` | None in the repo | — |
| User-level instructions | `~/.claude/CLAUDE.md`: graphify (only on `/graphify`), CodeGraph (only where `.codegraph/` exists), Context7 for library docs | CodeGraph not applicable (no `.codegraph/` index); no library-API questions arose that needed Context7 |
| Skills / plugins | ECC skill set (e.g. mysql-patterns, fastapi-patterns, database-migrations, security-review), Anthropic skills | Not loaded: the work was repo-specific verification and fixing, done directly against the code |
| Subagents | Available | Not used, to avoid parallel writers on the same files |
| Browser automation (DevTools MCP) | Configured, but **failed to connect** | Unavailable; the UI was verified over HTTP only (see the test report) |
| Project automation | `make.ps1`, `scripts/smoke.py`, `scripts/verify_mysql_runtime.py`, `seed/generate.py` | Used as-is; the demo is built on these rather than new tooling |

## 2. Approach

The full MySQL compose stack (`docker-compose.mysql.yml`) needs an API image rebuild and Vault, MinIO and observability
images that aren't local, and C: had 1.2–5.7 GB free. So the demo runs the **API, worker and web natively** from the repo
against **containerised MySQL, Keycloak, OPA and Redis**, reusing the isolated test MySQL and existing images. No images
were built or pulled, and no data was deleted.

## 3. Changes made tonight (demo preparation)

| File | Change | Why |
|---|---|---|
| `infra/docker-compose.mysql-demo.yml` (new) | Keycloak 26 on 8380 (MySQL `keycloak` database), OPA on 8381 (project policies), Redis on 56379, joined to the test MySQL network | The ports the API defaults and `apps/web/public/config.js` already expect, so no frontend config edits were needed |
| `CORTEX_MYSQL_DEMO_START.ps1` (new) | Idempotent, non-destructive start: prerequisites, disk check, containers, `cortex_demo` + `alembic -n mysql`, seed only if empty, API / worker / web, health waits, URLs, troubleshooting | Repeatable demo start |
| `cortex/l3_memory/warmth.py` | `sparkline()` treats naive datetimes as UTC (as `raw_sum()` already did) | **Defect:** `GET /v1/contacts` returned 500 on MySQL |
| `cortex/l8_actuation/api/routers/sources.py` | `source_runs()`: one SQL statement for both dialects | **Defect:** MySQL received a `SELECT` without `FROM` (500) |
| `infra/docker-compose.mysql.yml` | `depends_on: !override` (MySQL only) for `migrate` and `keycloak` | **Defect:** the production MySQL stack waited on a disabled `postgres` and could never start |
| `tests/unit/test_phase2_agents.py` | + `test_sparkline_accepts_naive_mysql_datetimes` | Regression |
| `tests/unit/test_mysql_router_sql.py` | + `test_source_runs_route_mysql` | Regression |
| `tests/unit/test_mysql_schema_versioning.py` | Compose test parses `!override` and asserts MySQL-only dependencies | Regression |
| Database `cortex_demo` (test MySQL :53306) | Created; schema via `alembic -n mysql`; seeded with `seed.generate --opportunities 200 --seed 7` | Deterministic synthetic demo data (200 opportunities, 932 entities, 931 edges, 200 embeddings) |
| Reports | `CORTEX_MYSQL_LIVE_DEMO_GUIDE.md`, `…_FINAL_TEST_REPORT.md`, `…_FINAL_READINESS_REPORT.md`, `…_CUTOVER_RUNBOOK.md`, `…_GIT_REVIEW_REPORT.md`, this file | Deliverables |

## 4. Changes made earlier in this effort (2026-10-30, audit phase)

`scripts/migrate_pg_to_mysql.py` (4 missing tables, fail-closed reconciliation, MySQL read-back checksums, orphan checks,
UTC conversion, preflight), `scripts/rehearse_data_migration.py` (keeps `audit_lock`, shows empty tables),
`platform_core/db/mysql_schema.py` (DELIMITER-aware splitter), `migrations_mysql/` + `alembic.ini [mysql]` (MySQL
schema history), the `docker-compose.mysql.yml` `migrate` command, `infra/mysql/init/01-keycloak.sh`, `infra/api/Dockerfile`,
`tests/integration/conftest.py`, and tests `test_migrate_reconciliation.py` and `test_mysql_schema_versioning.py`.
Details: `CORTEX_MYSQL_CURRENT_STATE_AND_REMAINING_WORK_REPORT.md`.

## 5. Pre-existing migration work (before this effort; reused, not rewritten)

PostgreSQL / MySQL dual-path SQL across about 49 files (`is_mysql_session`), `scripts/schema_mysql.sql` (49 tables, 4 triggers),
`platform_core/db/vector.py` (float32 BLOB vectors + in-memory cosine index), the relational graph traversal,
`platform_core/audit/chain.py` (MySQL `audit_lock` mutex), the Keycloak MySQL test setup, the ETL baseline, and the MySQL unit
and integration tests.

## 6. Feature matrix

| Feature | Status |
|---|---|
| MySQL connection, sessions, transactions | Implemented and verified |
| Schema + versioning (`alembic -n mysql`) | Implemented and verified |
| API routers on MySQL | Implemented and verified (2 defects fixed tonight; 50 GET routes, 0 errors) |
| Graph (relational, replacing AGE) | Implemented and verified (stats, neighbourhood, paths; integration test). Not equivalent to Cypher: no ad-hoc graph query language |
| Vectors (BLOB + cosine) | Implemented and verified (copilot retrieval). Not measured at scale; no HNSW-style index |
| Audit chain, append-only triggers, mutex | Implemented and verified |
| Keycloak on MySQL | Verified (demo login, unit suite); the production realm data move is a runbook step (C8), not executed |
| OPA authorization | Verified (allow and deny) |
| Worker / bus / scheduler | Verified (bus → worker → audit) |
| Frontend | Builds; served; API proxied. Browser click-through not automated |
| ETL + reconciliation | Implemented and verified on synthetic data |
| Production compose stack | Fixed, config-validated, never started |
| Real-data rehearsal, 1M benchmark, production cutover | Not done (blocked or pending; see the readiness report) |
| Not required for the demo | MinIO, Vault, observability stack, Mailpit |

## 7. Left running for the demo

Running: containers `capital-cortex-mysql-test`, `capital-cortex-keycloak-demo`, `capital-cortex-opa-demo` and
`capital-cortex-redis-demo`; native API (8300), worker and Vite (5373), started by `CORTEX_MYSQL_DEMO_START.ps1`
(logs and PIDs in `%TEMP%\capital-cortex-demo`).
Kept, untouched, from earlier work: databases `cortex_migrate_check` (scratch) and `cortex_rehearsal` on the test MySQL, and
the stopped disposable rehearsal PostgreSQL container `cortex-pg-rehearsal`.

## 8. Production safety

`capital-cortex_pgdata` was never mounted, started or modified. No production container exists on this host. No
`docker system prune`, `docker volume prune`, `docker compose down -v` or `docker volume rm` was run. No commits, pushes,
resets, stashes or branch switches.
