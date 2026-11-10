# Capital Cortex — MySQL 8.4 Final Test Report

> **Historical record (dated 2026-10-30).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


**Date:** 2026-10-30 · **Branch:** `feature/changes-login` · **Host:** Windows 11, Docker Desktop 29.6.1, Python 3.12 venv, Node 24.18

All results below come from fresh runs in this session unless marked *earlier today*. Nothing was rerun until it
passed by changing a test. Two tests were **added** for the two defects found, and no assertion was removed or weakened.

## Update 2026-10-31: final results on the fully fixed code

| Suite | Result | Command / notes |
|---|---|---|
| **Unit (all)** | **299 passed, 0 failed, 0 skipped** (298 s) | `$env:KEYCLOAK_TEST_URL="http://localhost:8380"; pytest tests/unit`; 294 + 5 new regression tests (line endings, vector memory, vector equivalence, single-scan facets, audit snapshot) |
| **Integration** | **20 passed, 0 failed, 3 skipped** (about 1,240 s) | Per file via the runner, against `cortex_integration`; every file exit 0; skips are PostgreSQL-only |
| Smoke, demo stack | 10/10 | `CORTEX_MYSQL_DEMO_START.ps1 -Verify` after a cold Docker start |
| **Smoke, isolated production stack** | **10/10**; 0 PostgreSQL references in API/worker logs | `docker-compose.yml` + `docker-compose.mysql.yml`, project `capital-cortex-stacktest`, alternate ports |
| Keycloak lifecycle | refresh 200, logout 204, refresh after logout 400, forged token 401 | MySQL-backed Keycloak |
| Keycloak user migration | export 9 users → import into a new DB: 9 users, 7 password + 1 OTP, 10 clients | `kc.sh export --users realm_file` / `kc.sh import` |
| **1M application benchmark** | 0 server errors; vector p50 77 ms; list p50 32 s under 8 clients | `scripts/benchmark_mysql_app_paths.py`; full table in `CORTEX_MYSQL_BLOCKER_CLOSURE_REPORT.md` |
| Shell scripts | `sh -n` OK, 0 CR bytes, `eol=lf` pinned | The earlier "CRLF" finding was a false positive |

## Environment under test

| Component | Where | Version / state |
|---|---|---|
| MySQL | `capital-cortex-mysql-test`, 127.0.0.1:53306 | 8.4.13, strict `sql_mode`; databases `cortex_demo` (demo), `cortex_integration` (integration tests), `cortex` (unit tests) |
| Keycloak | `capital-cortex-keycloak-demo`, 127.0.0.1:8380 | 26.0, backed by the MySQL `keycloak` database |
| OPA | `capital-cortex-opa-demo`, 127.0.0.1:8381 | 0.70.0, project policies + `config/roles.yaml` |
| Redis | `capital-cortex-redis-demo`, 127.0.0.1:56379 | 7.4 |
| API / worker | native uvicorn (8300) / `python -m cortex.worker` | `DATABASE_URL=mysql+asyncmy://…/cortex_demo` |
| Web | native Vite dev server, 5373 | proxies `/v1` to the API |

## Results

| Suite | Result | How it was run |
|---|---|---|
| **Unit tests (all)** | **294 / 294 passed** | `pytest tests/unit` (foreground): 288 passed; the 6 failures were all `test_mysql_keycloak.py` connecting to the *test* Keycloak on 58480, which is not running. That file was rerun against the running MySQL-backed Keycloak with `KEYCLOAK_TEST_URL=http://localhost:8380`: **10 / 10 passed**. 294 = the 292 earlier tests + 2 regression tests added tonight |
| ETL / reconciliation / schema versioning | 43 / 43 passed (inside the 294) | `test_migrate_pg_to_mysql.py`, `test_migrate_reconciliation.py`, `test_mysql_schema_versioning.py` |
| **Integration (MySQL)** | **20 passed, 0 failed, 3 skipped** | Rerun after tonight's fixes, file by file in the foreground, against `cortex_integration`; every file exit 0, no testcontainers fallback, 445 s. Per file: `CORTEX_MYSQL_INTEGRATION_PROGRESS.md`. The 3 skips are PostgreSQL-only (AGE Cypher, AGE labels, pgvector HNSW), conditional on the MySQL dialect, each with passing MySQL coverage |
| **Project smoke test** (`scripts/smoke.py`) | **10 / 10 application checks passed** | Real OIDC login (code + PKCE + TOTP) with MFA evidence in the token, audience, `/v1/me`, audit verify, an OPA **deny** (403), service-account ping, bus → worker → audit, chain re-verify. Its 11th step polls Grafana/Tempo, which the demo does not run (connection refused); that is not an application check |
| **Demo workflow check** | **29 / 29 passed** | Logs in like the SPA as `dev-analyst` (PKCE, redirect `localhost:5373`) and as `smoke-auditor` (TOTP). Covers: `/me`, `/meta`, opportunities list + facets + detail, executive / pipeline / runway dashboards, graph stats / neighbourhood (depth 2) / 2-hop paths, relationships, contacts, meetings, organizations, outcomes, forecasts, forecast snapshots, alerts, recommendations, scoring profiles, sources, milestones, calendar, recall, copilot vector retrieval (5 matches) and the expected-empty case, audit verify, audit list |
| **GET route sweep** | **50 routes, 0 server errors** | Every parameterless or ID-mappable GET route, as analyst and as auditor. 20 routes with a bare `{id}` were not swept; their tables are empty in the seed, except contact detail, opportunity detail and source runs, which were called directly: all 200 |
| Frontend type-check | exit 0 (38 s) | `npx tsc --noEmit -p tsconfig.json` (avoids rewriting the tracked `tsconfig.tsbuildinfo`) |
| Frontend production build | exit 0 (130 s) | `npx vite build` to the git-ignored `dist/`. Warning only: chunks over 1.2 MB |
| Frontend dev server | serves `/`, `config.js`; `/v1/meta` proxied (401 without a token, as designed) | `npx vite --port 5373` |
| **Start script** | exit 0, cold start and idempotent rerun | `CORTEX_MYSQL_DEMO_START.ps1 -Verify` started the API, worker and web from stopped; the second run detected everything running and changed nothing |
| PostgreSQL usage in the MySQL profile | 0 references | `grep -ci "postgres|psycopg|55432"` over the API and worker logs |
| Runtime verification (`scripts/verify_mysql_runtime.py`) | passed (*earlier today*) | asyncmy: `/healthz`, transactional write/read, graph edge, 1024-dim BLOB round-trip, audit chain, reconnect |
| ETL physical rehearsal | PASSED (*earlier today*, synthetic) | 48/48 tables reconciled with checksums read back from MySQL, 0 orphans; 17 tables populated |
| MySQL schema history | verified (*earlier today*) and tonight | `alembic -n mysql upgrade head` on a scratch DB (twice, idempotent) and on the new `cortex_demo` |

## Defects found and fixed tonight

| Defect | Symptom | Root cause | Fix | Regression test |
|---|---|---|---|---|
| Contacts list | `GET /v1/contacts` → 500 `TypeError: can't compare offset-naive and offset-aware datetimes` | MySQL `DATETIME` returns naive values; `sparkline()` compared them with an aware `now` (PostgreSQL `timestamptz` was aware) | `cortex/l3_memory/warmth.py`: `sparkline()` treats naive values as UTC, as `raw_sum()` already did | `tests/unit/test_phase2_agents.py::test_sparkline_accepts_naive_mysql_datetimes` |
| Source run history | `GET /v1/sources/{id}/runs` → 500 `Unknown column 'id' in 'field list'` | A conditional spliced into adjacent string literals sent MySQL `SELECT id, `trigger` AS `trigger`` with no `FROM` | `cortex/l8_actuation/api/routers/sources.py`: one statement for both dialects; the PostgreSQL text is identical to the original | `tests/unit/test_mysql_router_sql.py::test_source_runs_route_mysql` |
| Production MySQL compose stack could not start | Merged config: `migrate` and `keycloak` `depends_on: postgres (service_healthy)` | Compose merges `depends_on` across files; in MySQL mode `postgres` is a stub that exits with its healthcheck disabled | `infra/docker-compose.mysql.yml`: `depends_on: !override` (MySQL only) for both. Merged config verified: no service depends on `postgres`; the base PostgreSQL compose still validates | `tests/unit/test_mysql_schema_versioning.py::test_mysql_compose_runs_mysql_history_and_provisions_keycloak_db` (extended) |

## Not tested

| Item | Why |
|---|---|
| Browser click-through of the SPA | No browser automation available (the DevTools MCP failed to connect). The SPA's exact OIDC flow and all its API calls were exercised over HTTP; rehearse the UI by hand (demo guide, step 4) |
| Write flows from the UI (create opportunity, approvals, proposals, data room) | Covered by the integration suite on MySQL (phase 1–3 flows), not re-driven through the UI |
| 1M-record benchmark | Not run; see the readiness report |
| Real production-data rehearsal | No authorised dump exists |
| Observability (Grafana/Tempo/Prometheus) | Not started: no images locally and 1.2 GB free disk |

Raw evidence files (smoke output, workflow JSON, route sweep JSON, per-run integration logs) are in this session's temporary
folder. The durable record is this report and `CORTEX_MYSQL_INTEGRATION_PROGRESS.md`.
