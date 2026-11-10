# Capital Cortex: Complete Open Blocker Audit (PostgreSQL 16 → MySQL 8.4)

> **Historical record (dated 2026-11-04).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


Audit date: **2026-11-04, ~17:40 IST**.

**Method: audit only.** No source, `.env`, Docker, database or test changes were made, and nothing was staged.
- Every defect below was re-checked against the **current source** (file:line).
- Test numbers are **historical**: the last runs, 14:40–15:35 IST today. They could not be re-run: Docker Desktop is down.
- Anything not provable from code or recorded evidence is marked **NOT VERIFIED**.

AIOT and DAPRO were not touched.

## A. Executive summary

**Application migration: NOT COMPLETE. Production cutover: NOT READY, NOT APPROVED.**

| Owner | P0 | P1 | P2 | P3 | Total open |
|---|---|---|---|---|---|
| Workstation owner (you) | 2 | – | – | – | 2 |
| Engineering | – | 6 | 10 | 3 | 19 |
| DevOps | 1 | 2 | 1 | – | 4 |
| Project Lead (decisions) | – | 2 | 3 | – | 5 |
| **Total** | **3** | **10** | **14** | **3** | **30** |

**What is done:**
- All 12 High MySQL defects (H1–H12) are fixed.
- Unit tests 497/497 and integration 20 passed / 3 intentional skips, both historical.
- E2E Phase 2 passed in the last run.

**What blocks completion:**
- The environment: Docker Desktop is being terminated, and the host is out of memory.
- The Phase 1 E2E failure (PERF-2).
- 10 open Medium MySQL defects.
- 8 modules with no MySQL test, and 4 High fixes without a route-level test.
- The frontend build and CI have never been verified on MySQL.
- Project Lead decisions on search, rollback and Keycloak separation.

## B. Master blocker register

| ID | Blocker | Root cause (verified) | Affected files/modules | Impact | Sev. | Owner | Required action | Depends on | Status |
|---|---|---|---|---|---|---|---|---|---|
| ENV-1 | Docker Desktop repeatedly stops | Docker log: `backend process exited: exit status 0x40010004` (= `DBG_TERMINATE_PROCESS`, i.e. **terminated externally**, not a crash) at 10:32 UTC and 11:35 UTC; a later stop ~11:47 UTC left no exit entry. 4 engine outages today. The terminator is **NOT VERIFIED** (manual "End task"/Quit, or another session's tooling). | Docker Desktop; all containers (Cortex, AIOT, DAPRO) | all DB-backed verification impossible; demo MySQL exits 255 each time (`restart: no`) | P0 | Workstation owner + DevOps | find who ends Docker (check the other Claude sessions and Task Manager use); stop it; keep Docker running | – | **OPEN** |
| ENV-2 | Host memory/CPU exhaustion | 15.6 GB RAM; with AIOT + DAPRO + Cortex stacks up: 95–98 % used, 0.2–0.5 GB free; CPU 100 % (VS Code installer `CodeSetup…tmp` running for hours; 24–27 VS Code processes; Chrome; ChatGPT/Spotify relaunch) | workstation | API calls 3.6–5 s (≈20 ms idle); `vite build` OOM ×2; shells failed to launch (exit 107/66); Docker VM boot stalls | P0 | Workstation owner | run only one heavy stack at a time, or add RAM; let the installer finish; keep ChatGPT/Spotify closed | – | **OPEN** |
| ENV-3 | Demo services down | consequence of ENV-1: `capital-cortex-mysql-test` exited 255; Keycloak demo depends on it (stopped by me at 17:20 to end its crash loop; restart with `docker start`); demo API/worker/web processes gone after the 16:29 session loss | demo stack | no E2E/API verification | P0 | DevOps / Engineering | after ENV-1/2: `docker start capital-cortex-mysql-test` (existing volume), then Keycloak, API, worker, web | ENV-1, ENV-2 | **OPEN** |
| ENV-4 | Start script exit code 4 | NOT VERIFIED: output unreadable (shell died); API and worker were healthy afterwards | scratchpad `demo_start_nocompose.ps1` | unknown | P3 | Engineering | rerun with logging once stable | ENV-3 | **NOT VERIFIED** |
| PERF-2 | Executive dashboard slow (E2E Phase 1 fails) | `GET /v1/dashboards/executive` runs ~8 sequential awaits on one session, including **3 full forecast scenarios** (`_runway` → `run_scenarios(base, downside, upside)`) plus `weighted_pipeline`, counts, risks and 2 more queries (`routers/dashboards.py:40, 248–300`). ~1.7 s server-side measured directly; which step dominates is **NOT VERIFIED** (needs profiling) | `routers/dashboards.py`, forecast engine, `pipeline_engine` | Phase 1 "Key figures" misses 5 s | P1 | Engineering | profile per step (`EXPLAIN ANALYZE` + timing); optimise the dominant step (likely forecast reuse/caching per request, or index); measure before and after | ENV-3 | **OPEN** |
| PERF-1 | Search 6–13 s vs 2 s target | `MATCH … AGAINST` OR leading-wildcard `LIKE` on title and the joined counterparty name defeats the FULLTEXT index → full org scan (EXPLAIN, `CORTEX_PERFORMANCE_AUDIT.md`) | `routers/opportunities.py` | slow radar/search at scale | P1 | **Project Lead** decision, then Engineering | choose semantics (see §E) | ENV-3 for measuring | **DECISION** |
| M1–M10 | 10 open Medium MySQL defects | see §C | see §C | data correctness edge cases | P1–P3 | Engineering | fix + MySQL regression test each | ENV-3 for tests | **OPEN** |
| COV-1 | 8 dual-path modules have no MySQL test | see §D | see §D | defects undetected | P2 | Engineering | add MySQL tests | ENV-3 | **OPEN** |
| COV-2 | High fixes without a route/function-level test | H3 (PATCH recommendation: no test), H4 (approve recommendation: no test), H9 (ML scorer active-model branch not hit), H10 (`ttl_job`: no test). H7, H8, H11 exercised by integration flows, but their assertions on the fixed values are NOT VERIFIED | `routers/agents.py`, `ml_scorer.py`, `memory_manager.py` | regressions could return unnoticed | P1 | Engineering | route/function tests on MySQL | ENV-3 | **OPEN** (fixes in place; decode level tested) |
| COV-3 | No live API regression suite against the demo API | only in-process API tests exist | – | deployment-level regressions | P2 | Engineering | small smoke/API suite against `127.0.0.1:8300` | ENV-3 | **OPEN** |
| T-1 | E2E Phase 1 "Key figures" | PERF-2 + ENV-2 (trace: `/v1/me` 3.6 s, `/v1/meta` 5.0 s, dashboard 3.6 s) | `apps/web/e2e/phase1.spec.ts:20` | E2E not green | P1 | Engineering | fix PERF-2, rerun on a stable host; assertion stays 5 s | PERF-2, ENV-2 | **FAIL** (historical) |
| T-2 | Frontend production build | esbuild `fatal error: out of memory` ×2; not a code error (ESLint/tsc pass) | `apps/web` | release artefact unverified | P1 | Workstation owner → Engineering | rerun with ≥4 GB free | ENV-2 | **NOT VERIFIED** |
| T-3 | 8 files fail `ruff format --check` | pre-existing uncommitted formatting in modules I also touched: `memory_manager.py`, `tool_registry.py`, `approval_service.py`, `ml_scorer.py`, `agents.py`, `relationships.py`, `dataroom.py`, `proposals.py`, `seed/generate.py` (8 of these 9 reported) | listed | CI lint job fails | P2 | Engineering (with the owner of the uncommitted work) | `ruff format` on exactly those files, review the diff | none | **OPEN** |
| CI-1 | CI never run on MySQL | workflow edited (unit MySQL service, integration Testcontainer, stack/E2E/backup drill on the MySQL overlay); no runner access from this machine | `.github/workflows/ci.yml` | no CI evidence | P1 | **DevOps** | push branch / trigger workflow; fix findings | T-3 | **NOT VERIFIED** |
| CI-2 | Live-Keycloak tests excluded from CI | `test_mysql_keycloak.py` needs the demo realm + MySQL on 53306 | CI unit job | Keycloak-on-MySQL only verified locally | P2 | DevOps | add a Keycloak service job, or accept local-only (record decision) | CI-1 | **OPEN** |
| RB-1 | PostgreSQL rollback paths broken | `l2_representation/pipeline.py:108-122` embedding INSERT not branched (MySQL syntax on both); `entity_resolver.py:264-268` backticked `undo` | rollback build | current build cannot run on PostgreSQL | P1 | Project Lead (ARCH-3) + Engineering | pin a pre-migration release as the rollback build, or fix the 2 paths | ARCH-3 | **OPEN** |
| ARCH-1 | Keycloak DB on the shared app MySQL | `docker-compose.mysql.yml:90-93` | identity | Keycloak JDBC acquisition timeouts and 500s whenever test suites load the shared demo server (observed today) | P1 (prod) | **Project Lead + DevOps** | decide on a separate instance for production | – | **DECISION** |
| ARCH-2 | Vector strategy | exact in-memory per-tenant index over BLOBs (`platform_core/db/vector.py`) | API RAM/start-up | 143 s cold build, ~2.7 GB/process at 200k vectors | P2 | **Project Lead + architect** | decide A now / HNSW later | – | **DECISION** |
| ARCH-3 | Rollback window and pinned release | one-way ETL, no reverse sync | cutover | post-cutover writes lost on rollback | P1 | **Project Lead + business owner** | decide window (rec. 7–14 days) and the rollback release | RB-1 | **DECISION** |
| ARCH-4 | Removal of the 49 dual-path PG branches | dual maintenance | code | – | P2 | **Project Lead** | approve removal after the ARCH-3 window | B3, ARCH-3 | **DECISION** (deferred) |
| B1 | Production PostgreSQL backup | none authorised | cutover | no safe source snapshot | P1 (prod) | **DevOps → DBA** | authorised dump + checksums | – | **BLOCKED** |
| B2 / INFRA-1 | Production MySQL environment | none provisioned (D-011; Terraform stub) | cutover | – | P1 (prod) | **DevOps** | provision (buffer pool ≥ working set) | – | **BLOCKED** |
| SEC-P | TLS, secret store, backup key | Keycloak `start-dev` over HTTP; Vault dev mode; no backup encryption key | production | – | P1 (prod) | **DevOps + security** | provide TLS, KMS/Vault, key custody | B2 | **FAIL** |
| B3 | Cutover approval | prerequisites open | – | – | gate | **Project Lead + DevOps + DB owner** | – | all above | **NOT APPROVED** |
| SVC-1 | MinIO, Vault, Grafana not verified | not running | dev stack | – | P3 | Engineering | verify at the next dev-stack start | ENV-3 | **NOT VERIFIED** |
| ENV-5 | `.env` `MYSQL_TEST_DATABASE=cortex` points at a legacy pre-m0004 schema | historical config | unit test invocation | 10 false failures without the override | P3 | Workstation owner | set `cortex_unit` in `.env` (owner's call; not changed by me) | – | **OPEN** |

## C. MySQL defect register (all re-verified in current source)

| ID | Defect | Exact location | Technical detail | PostgreSQL behaviour | Impact | Status |
|---|---|---|---|---|---|---|
| M1 | Timezone offset dropped on write | e.g. `routers/alerts.py:197` (snooze `until`), `routers/calendar.py`, `routers/outcomes.py:79`, `l3_memory/relationship_service.py:200,423,570` | an aware `datetime` with a non-UTC offset is bound by asyncmy as its wall-clock time; DATETIME stores no offset; the app sets no session `time_zone` (`platform_core/db/session.py`) | `timestamptz` converts to UTC | an input like `…+05:30` is stored 5 h 30 min off. Inputs in `Z`/UTC (browser `toISOString`) are correct | **OPEN** |
| M2 | `INSERT IGNORE` hides FK/CHECK errors | `entity_resolver.py:173`, `relationship_service.py:213`, `l8_actuation/alerts.py:78`, `alerts.py:364`, `routers/alerts.py:276`, `routers/entities.py:114` | MySQL downgrades FK, CHECK and NOT NULL errors to warnings under IGNORE, not only duplicate keys | `ON CONFLICT DO NOTHING` ignores only the conflict | invalid rows silently dropped and reported as "duplicate" | **OPEN** (`audit/chain.py:81` and `idempotency.py:89` are legitimate uses) |
| M3 | Ingestion race → 1062 | `l1_perception/ingestion.py:73-99` | SELECT-then-INSERT; the unique key `ux_signal_hash (org_id, content_hash)` exists, so a concurrent duplicate raises `IntegrityError 1062` | `ON CONFLICT DO NOTHING RETURNING` | a concurrent ingest of the same item fails the whole run | **OPEN** |
| M4 | `JSON_MERGE_PATCH` drops null keys | `l6_agency/orchestrator.py:539` | RFC 7396 semantics delete keys whose value is null; the merged `output` carries nullable keys (e.g. `convergence_mode`) | jsonb `||` keeps `null` | keys missing instead of null in the council output; consumers using `.get` unaffected; strict schema consumers affected (NOT VERIFIED which) | **OPEN** (Low–Medium) |
| M5 | Unquoted JSON-path key | `l7_governance/refs.py:153` (`CONCAT('$.evidence_pack.', :k)`) | keys with `:`, `-`, `/` or spaces are invalid path members → MySQL error 3143 | `-> :k` takes any text key | the citation check aborts for such evidence keys | **OPEN** |
| M6 | Retention double-encoding | `l7_governance/retention.py:127` (`json.dumps(r.raw)`) | `raw` is JSON text on MySQL, so the cold-tier object is a JSON string literal | jsonb → dict, encoded once | archived signals unreadable as documents | **OPEN** (same class as fixed H10) |
| M7 | Non-atomic settings version | `l7_governance/settings_service.py:164-175` | version read via `get()` (no lock), incremented in Python, written via ODKU | atomic `version = setting.version + 1` | concurrent edits lose a version bump (audit/optimistic-lock semantics) | **OPEN** |
| M8 | Booleans serialised as 0/1 | `platform_core/jsonutil.py` `row()`/`jsonable`; 61 `BOOLEAN` (= `TINYINT(1)`) columns | the driver returns `int`; `jsonable` passes ints through | `bool` | API JSON has `1`/`0` instead of `true`/`false`; frontend strict checks (`=== true`) would misbehave (NOT VERIFIED which) | **OPEN** |
| M9 | Datetimes without offset in API JSON | `jsonable()` → naive `isoformat()` | naive DATETIME → `"2026-11-04T10:00:00"` (no `Z`) | aware → `+00:00` | browsers parse offset-less ISO strings as **local time**: off by the user's UTC offset in the UI | **OPEN** |
| M10 | Naive datetimes in ICS export / calendar | `routers/calendar.py:59,100` (`isoformat()` of DB values) | same as M9 | aware | calendar events shifted for non-UTC users | **OPEN** |
| M11 | `row()` timeline/sort fixed only in relationships | other naive/aware comparisons NOT VERIFIED app-wide | – | – | possible TypeErrors elsewhere | **NOT VERIFIED** |

Recommended order: M9/M8 (one central change in `jsonable`, high visibility), then M3, M2, M6, M1, M7, M5, M10, M4. Each needs a MySQL regression test.

## D. 49-module coverage register

Coverage key:
- **R:** route/function-level MySQL test.
- **I:** exercised by a MySQL integration flow.
- **D:** JSON-decode-level test only.
- **–:** no MySQL test.

Statuses:
- OK
- FIXED (High)
- MED (open Medium, §C)
- PG-BROKEN (PostgreSQL path broken)

Test file names abbreviated: `router_sql` = `test_mysql_router_sql.py`, `compat` = `test_mysql_json_datetime_compat.py`, `i:x` = `tests/integration/test_x.py`.

| # | Module | MySQL coverage | Status |
|---|---|---|---|
| 1 | l1 ingestion | R (router_sql, live_ingestion) | MED (M3) |
| 2 | l1 registry | R (router_sql) | OK |
| 3 | l2 entity_resolver | R (router_sql) | MED (M2) + PG-BROKEN |
| 4 | l2 pipeline | I (api_flow, pipeline) | PG-BROKEN |
| 5 | l3 consolidation_job | – | OK by code review; **untested** |
| 6 | l3 interaction_ingest | – | OK by code review; **untested** |
| 7 | l3 memory_manager | R (router_sql); `ttl_job`: D only | FIXED H10 (no function test) |
| 8 | l3 recall_api | – | OK by code review; **untested** |
| 9 | l3 relationship_service | R (router_sql) | MED (M1, M2) |
| 10 | l4 ml_scorer | R + I (feedback_loop) | FIXED H9 (branch not hit) |
| 11 | l4 score_service | R + I | OK (Medium note: `source_ref` stored as a string inside factors, NOT VERIFIED impact) |
| 12 | l5 copilot | R (router_sql, mysql_vector) | OK |
| 13 | l5 pipeline_engine | R | OK |
| 14 | l6 agent_runtime | unit (backend NOT VERIFIED) | **untested on MySQL** |
| 15 | l6 orchestrator | I (phase2_flow) | MED (M4) |
| 16 | l6 tool_registry | I (phase2/3 flows) + D | FIXED H8 (values not asserted) |
| 17 | l7 approval_service | R (compat, real OPA) + I | FIXED H2 |
| 18 | l7 drafts | – | **untested** |
| 19 | l7 outbox | I (phase2/3) | OK |
| 20 | l7 refs | R (router_sql) | MED (M5) |
| 21 | l7 retention | R + I (phase3) | MED (M6) |
| 22 | l7 settings_service | unit (backend NOT VERIFIED) | MED (M7) |
| 23 | l8 alerts (service) | unit (backend NOT VERIFIED) | MED (M2); **untested on MySQL** |
| 24 | l8 board_reports | I (phase3) | OK |
| 25 | l8 compliance_report | – | **untested** (GROUP_CONCAT 1024-char default limit: NOT VERIFIED) |
| 26 | l8 dataroom | R + I (phase3) | FIXED H11 |
| 27 | l8 proposal_builder | unit (phase3_assets) | **untested on MySQL** |
| 28 | l8 proposals | I (phase3) | FIXED H11 |
| 29 | r/admin | I (phase3) | OK |
| 30 | r/agents | R (H5) + I | FIXED H3/H4/H5 (H3, H4 routes untested) |
| 31 | r/alerts | I (phase2) | MED (M1, M2) |
| 32 | r/approvals | I (phase2/3) | OK |
| 33 | r/board_reports | I (phase3) | OK |
| 34 | r/calendar | I (phase2) | MED (M1, M10) |
| 35 | r/dashboards | I (api_flow, phase3) + D | FIXED H6; PERF-2 |
| 36 | r/dataroom | I (phase3) | OK |
| 37 | r/entities | – | MED (M2); **untested** |
| 38 | r/forecasts | – | **untested** (ODKU with deprecated `VALUES()`, warning only) |
| 39 | r/opportunities | R + I | OK; PERF-1 |
| 40 | r/organization | I (api_flow) | OK |
| 41 | r/outcomes | I (phase2) | MED (M1) |
| 42 | r/proposals | I (phase3) | OK |
| 43 | r/relationships | I (phase2 timeline) + D | FIXED H7 |
| 44 | r/scoring | I (api_flow) | OK |
| 45 | r/sources | R + I | OK |
| 46 | platform_core/audit/chain | R (audit chain, invariants/mutex) | OK |
| 47 | platform_core/idempotency | R (compat: real middleware) | FIXED H1 |
| 48 | seed/generate | R (compat H12) + I (seed) | FIXED H12 |
| 49 | seed/purge | I (seed) | Medium: self-referencing FK order (1451) NOT VERIFIED |

**Totals:**

| Group | Count |
|---|---|
| OK, tested | 16 |
| FIXED High (all with at least decode-level tests) | 11 modules (H1–H12; `r/agents` holds H3, H4 and H5) |
| With an open Medium | 13 (some overlap with the above) |
| **No MySQL test at all** | **8**: consolidation_job, interaction_ingest, recall_api, drafts, compliance_report, entities router, forecasts router, and l8 alerts service (agent_runtime, settings_service and proposal_builder have unit tests on an unverified backend) |
| PostgreSQL path broken | 2 |

**Unintended PostgreSQL runtime dependency in the MySQL runtime: none found.** The MySQL branch is always taken when the session dialect is MySQL. PostgreSQL-only modules (`age.py`, `COSINE_SEARCH_SQL`, PG scripts, `migrations/`) are only reached on the PG dialect or by PG tooling. Remaining PG references in deployment: `infra/docker-compose.yml` default stack, `alembic.ini` default section, Makefile/`make.ps1`, Terraform, `pyproject` (`psycopg`, `testcontainers[postgres]`). CI was moved to MySQL (unverified).

## E. Performance register

| ID | Measurement (historical) | Root cause | Options | Recommendation | Decision owner |
|---|---|---|---|---|---|
| PERF-1 | combined search 6.1 s warm / 13.4 s cold; FULLTEXT-only 1.2 s; first page FULLTEXT-only 0.26 s; target < 2 s (`cortex_bench_1m`, 111k active opps, 512 MB buffer pool) | FULLTEXT OR leading-wildcard LIKE (title + joined counterparty) → no index access path; leading-wildcard LIKE is inherently a scan | A: FULLTEXT only (loses mid-word and counterparty-name matches). B: A + FULLTEXT on `organization.name` (loses mid-word only). C: n-gram FULLTEXT (`WITH PARSER ngram`, token size 2–3) keeps substring-like matching; larger index, possible false positives, migration needed. D: keep (6–13 s). Plus capped totals and cached facets | **Prototype C on `cortex_bench_1m`, measure latency and result parity against the current search, then decide**; capped totals now | **Project Lead** (semantics); DevOps (buffer pool ≥ working set) |
| PERF-2 | `/v1/dashboards/executive` ~1.7 s direct (vs 22 ms `/v1/me`); 3.6 s under load; E2E budget 5 s including page bootstrap | ~8 sequential steps incl. 3 forecast scenarios (§B); dominant step NOT VERIFIED; no N+1 or frontend duplicate request seen in the trace (one dashboard call per load) | profile → optimise the dominant step (e.g. run the 3 scenarios on one shared data load, add the missing index, or parallelise independent reads on separate sessions); never serve stale data | engineering fix; no approval needed unless results become cached/stale | Engineering |

## F. Environment register

| ID | Item | Evidence | Status |
|---|---|---|---|
| ENV-1 | Docker Desktop externally terminated | `Docker Desktop.exe.log`: `exit status 0x40010004` at 10:32 and 11:35 UTC; engine stopped again ~11:47 UTC; Docker not running at audit time | **OPEN** |
| ENV-2 | RAM/CPU | 95–98 % RAM with all stacks; 70.7 % only when Docker was down; CPU 100 % throughout; VS Code installer running | **OPEN** |
| ENV-3a | Demo MySQL | `capital-cortex-mysql-test` exited 255 (restart policy `no`); volume `capital-cortex_mysql_test_data` intact at last inspection; data last verified 15:45 IST (1,026 opps, m0004) | **DOWN** (data NOT re-verified) |
| ENV-3b | Keycloak demo | crash-looped without its DB; stopped at 17:20 (`docker start` to restore) | **STOPPED** |
| ENV-3c | Demo API/worker/web | processes gone after 16:29; worker had also died at 11:38 | **DOWN** |
| ENV-3d | Redis/OPA demo, stack-test MySQL | healthy before the last Docker stop; now down with Docker | **DOWN** |

## G. Testing register (historical, 2026-11-04)

| Suite | Command | Collected | Passed | Failed | Skipped | When | Status now |
|---|---|---|---|---|---|---|---|
| Backend unit | `MYSQL_TEST_DATABASE=cortex_unit KEYCLOAK_TEST_URL=http://localhost:8380 pytest tests/unit` | 497 | 497 | 0 | 0 | 14:51 | not re-runnable (Docker down) |
| MySQL integration | `CORTEX_OPA_URL=http://localhost:8381 pytest -m integration tests/integration` | 23 | 20 | 0 | 3 (PG-only) | 14:58 | not re-runnable |
| E2E | `E2E_BASE_URL=http://localhost:5373 npx playwright test` | 8 | 5 | **1** (phase1 Key figures) | 2 (admin-only) | 15:35 | not re-runnable |
| Vitest | `npx vitest run` | 6 | 6 | 0 | 0 | 15:08 | – |
| ESLint (changed files), `tsc -b --noEmit` | – | – | pass | – | – | 15:08 | – |
| Production build | `npx vite build` | – | – | OOM ×2 | – | 15:10 | **NOT VERIFIED** |
| `ruff format --check` | – | – | – | 8 files | – | 14:3x | **FAIL** |
| CI | – | – | – | – | – | never | **NOT VERIFIED** |
| Backup/restore | demo drills 2026-11-02/03 PASS; CI MySQL drill added, never run | – | – | – | – | – | demo PASS; CI NOT VERIFIED |

Missing coverage: COV-1 (8 modules), COV-2 (H3, H4, H9, H10 paths), COV-3 (no live API suite), CI-2 (Keycloak in CI).

## H. Ownership split

- **Engineering (no approval needed):**
  - PERF-2;
  - M1–M10;
  - COV-1/2/3;
  - T-3 formatting (coordinate with the owner of the uncommitted work);
  - ENV-4;
  - SVC-1;
  - RB-1 fixes, if ARCH-3 chooses to fix rather than pin.
- **Project Lead:**
  - PERF-1 search semantics;
  - ARCH-1 Keycloak DB separation (with DevOps);
  - ARCH-2 vectors;
  - ARCH-3 rollback window and pinned release (with the business owner);
  - ARCH-4 removal timing;
  - B3 cutover (with DevOps and the DB owner).
- **DevOps:**
  - ENV-1 investigation support;
  - CI-1 run CI;
  - CI-2 Keycloak in CI;
  - B1 production PG backup;
  - B2/INFRA-1 production MySQL;
  - SEC-P (TLS, secret store, backup key);
  - a test MySQL server not shared with the demo/Keycloak.
- **Workstation owner:**
  - ENV-1: identify and stop whatever terminates Docker;
  - ENV-2: one heavy stack at a time, let the VS Code installer finish, keep ChatGPT/Spotify closed;
  - ENV-5: `.env` test database choice.

## I. Priority and execution order

1. **P0 (unblocks everything):**
   1. ENV-1: stop Docker being terminated.
   2. ENV-2: get to under 85 % RAM with Docker running.
   3. ENV-3: start demo MySQL (existing volume) → Keycloak → API, worker, web; re-verify revision and 1,026 opportunities.
2. **P1:**
   1. PERF-2 profile and fix → T-1 E2E Phase 1.
   2. COV-2 route tests (H3, H4, H9, H10).
   3. M9 + M8 (central serialisation).
   4. M3 ingestion race.
   5. M2 INSERT IGNORE.
   6. T-2 build.
   7. CI-1 (after T-3).
   8. **Decisions in parallel:** PERF-1, ARCH-1, ARCH-3/RB-1.
   9. **Production track (DevOps):** B1, B2, SEC-P.
3. **P2:**
   1. M1, M6, M7, M5, M10.
   2. COV-1 (8 modules) and COV-3.
   3. T-3 formatting (before CI-1).
   4. CI-2.
   5. ARCH-2, ARCH-4 decisions.
4. **P3:** M4, ENV-4, ENV-5, SVC-1.

Dependencies:
- T-1 depends on PERF-2 + ENV-2.
- CI-1 depends on T-3.
- B3 depends on B1 + B2 + SEC-P + ARCH-3 + application completion.
- ARCH-4 depends on B3 + the ARCH-3 window.

## J. Final migration readiness

**Application migration is not complete** because:
1. Required E2E is not green (Phase 1 fails: PERF-2 plus the host).
2. The frontend production build is unverified (OOM).
3. CI has never run on MySQL.
4. 10 Medium MySQL defects are open, including user-visible time display (M9) and silent data loss (M2).
5. 8 modules have no MySQL test, and 4 High fixes lack route-level tests.
6. Search performance (PERF-1) has no approved behaviour.
7. The PostgreSQL rollback path is broken in 2 modules, with no pinned rollback release.
8. The environment cannot currently run any verification (ENV-1/2/3).

**Conditions for application completion:**
- ENV-1/2/3 resolved;
- PERF-2 fixed and measured;
- full E2E green (admin-only skips recorded);
- build passes;
- CI green on a real runner;
- M1–M10 fixed with tests (or individually accepted by the Project Lead);
- COV-1/2 closed;
- PERF-1 decided and measured;
- data integrity re-verified.

**Conditions for production cutover:**
- all of the above;
- ARCH-1, ARCH-3 decided;
- RB-1 resolved via a pinned rollback release;
- B1, B2/INFRA-1 and SEC-P done;
- a production restore rehearsal;
- **B3 approval** by the Project Lead, DevOps and the DB owner.

---

# K. Handoff status (2026-11-04, end of day)

Status labels:
- **PASS:** verified by executed evidence.
- **FAIL:** executed and failed.
- **BLOCKED:** could not execute.
- **NOT RUN:** not attempted.

## K1. Why work stopped

Workstation resource gate (owner's rule: no startup above 85 % RAM or with CPU saturated):

| Time (IST) | RAM used | CPU | Decision |
|---|---|---|---|
| ~18:45 | 89.6 % | 65–87 % | stop |
| ~19:00 | 95.5 % | 58–100 % | stop |
| ~19:10 | 91.7 % | 93–100 % (explorer + OneDrive sync ≈ 1.4 cores) | stop |
| ~19:20 | **97.5 %** | 74–100 % | stop |

No Cortex service was started. The demo MySQL (`capital-cortex-mysql-test`, Exited 255) and Keycloak (Exited 143) are **down**. AIOT/DAPRO containers were never touched.

**Continue on a machine or session with ≥ 4 GB free RAM.**

## K2. What is done (code, uncommitted, nothing staged)

| Item | Files | Evidence |
|---|---|---|
| H1–H12 High defects | see `CORTEX_MYSQL_BLOCKER_CLOSURE_REGISTER.md` | **PASS**: 26 tests, unit suite 497/497 (14:51), integration 20 passed / 3 PG-only skips (14:58) |
| M1 tz on write | `platform_core/db/session.py` (MySQL bind hook) | test written, **BLOCKED** (needs DB) |
| M2 INSERT IGNORE (6 sites) | `platform_core/db/compat.py` `insert_or_skip_duplicate`; entity_resolver, relationship_service, alerts ×2, routers/alerts, routers/entities | source check **PASS**; DB test **BLOCKED** |
| M3 ingestion race | `cortex/l1_perception/ingestion.py` | **BLOCKED** |
| M4 JSON null keys | `cortex/l6_agency/orchestrator.py` | dedicated test **NOT RUN** (to be written) |
| M5 JSON path key | `cortex/l7_governance/refs.py` | **BLOCKED** |
| M6 retention | `cortex/l7_governance/retention.py` | decode-level only; run-level **NOT RUN** |
| M7 settings version | `cortex/l7_governance/settings_service.py` | **BLOCKED** |
| M8 booleans | `platform_core/jsonutil.py` (`BOOL_COLUMNS`, `row`) | **PASS** (schema parity + unit); DB test **BLOCKED** |
| M9 datetime offsets | `platform_core/jsonutil.py` | **PASS** |
| M10 calendar/ICS (was −5:30 on IST servers) | `cortex/l8_actuation/api/routers/calendar.py` | **PASS** |
| H10 function test | `tests/unit/test_mysql_medium_defects.py` | **BLOCKED** |
| E2E login sync, vite proxy, CI on MySQL | `apps/web/e2e/helpers.ts`, `apps/web/vite.config.ts`, `.github/workflows/ci.yml` | E2E 5/1/2 at 15:35; CI **NOT RUN** (no runner) |

Last executed DB-free run: `pytest tests/unit/test_mysql_medium_defects.py -k "bool_columns or row_turns or m9_datetimes or no_insert_ignore or m10"` → **5 passed**.

**Important:** the full unit and integration suites have **not** been re-run since the M1–M10 changes. Run them before handing on further.

## K3. Remaining work, in order (for the next engineer)

1. **Recover the demo stack** (authorised by the owner; existing containers and volumes only):
   ```
   docker start capital-cortex-mysql-test        # wait for health=healthy
   docker exec -i capital-cortex-mysql-test sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N -e "SELECT version_num FROM cortex_demo.alembic_version; SELECT COUNT(*) FROM cortex_demo.opportunity"'   # expect m0004_reconcile_legacy_layouts / 1026
   docker start capital-cortex-keycloak-demo
   ```
   Then start the API, worker and web with the existing demo start script (`demo_start_nocompose.ps1`, reads `.env`).
2. **Pending DB tests:**
   ```
   MYSQL_TEST_DATABASE=cortex_unit pytest tests/unit/test_mysql_medium_defects.py tests/unit/test_mysql_json_datetime_compat.py -p no:cacheprovider -q -rfEs
   ```
3. **Full suites, sequentially:**
   ```
   MYSQL_TEST_DATABASE=cortex_unit KEYCLOAK_TEST_URL=http://localhost:8380 pytest tests/unit -p no:cacheprovider -q -rfEs
   CORTEX_OPA_URL=http://localhost:8381 pytest -m integration tests/integration -p no:cacheprovider -q -rfEs
   ```
   The M1 hook and the M8 `row()` change are global. Watch for tests asserting naive datetime strings or 0/1 booleans; fix the assertion only if it encoded the old wrong contract.
4. **New tests:**
   - M4: orchestrator merge keeps null keys.
   - Route tests: H3 (PATCH `/v1/recommendations/{id}` with a portal-export draft), H4 (POST `/v1/recommendations/{id}/approve`), H9 (`ml_scorer.train` with an active model and no holdout candidate).
   - Check that the H7/H8/H11 integration flows assert the fixed values.
   - The 8 untested modules: consolidation_job, interaction_ingest, recall_api, drafts, compliance_report, routers/entities, routers/forecasts, l8 alerts service.
5. **PERF-2:** time each step of `GET /v1/dashboards/executive` (`_runway` with 3 forecast scenarios, `weighted_pipeline`, counts, risks, top, geo); optimise only the measured bottleneck; check result parity; rerun `npx playwright test e2e/phase1.spec.ts`.
6. **Frontend:** `npx vitest run`, `npx eslint .`, `npx tsc -b --noEmit`, `npx vite build` (needs ≥ 4 GB free), then the full `npx playwright test` with `E2E_BASE_URL=http://localhost:5373`.
7. **Formatting:** 76 files fail `ruff format --check .`. Most of the diff is in earlier uncommitted migration work. Agree the scope with the owner before running `ruff format` on them.
8. **CI (DevOps):** push the branch `feature/changes-login` and run `.github/workflows/ci.yml` (unit on a MySQL service, integration via Testcontainer, stack/E2E/backup drill on `docker-compose.mysql.yml`).

## K4. Decisions still required

- **Project Lead:**
  - PERF-1 search semantics (recommend measuring an n-gram FULLTEXT prototype on `cortex_bench_1m`);
  - ARCH-1 Keycloak DB separation;
  - ARCH-2 vectors;
  - ARCH-3 rollback window + pinned PostgreSQL release (current build's PG path is broken in 2 modules);
  - ARCH-4 PG code removal;
  - B3 cutover.
- **DevOps:**
  - CI run;
  - B1 production PostgreSQL backup;
  - B2/INFRA-1 production MySQL;
  - TLS, secret store, backup-encryption key;
  - a dedicated test MySQL server;
  - ENV-1 (Docker Desktop externally terminated: `0x40010004` in its log).

## K5. Migration status

- **Application migration: NOT COMPLETE.** Remaining:
  - M1–M7 DB verification;
  - full suites after the new changes;
  - PERF-2 and Phase 1 E2E;
  - the build;
  - CI;
  - the open tests listed in K3.
- **Production cutover: NOT READY, NOT APPROVED.**

## K6. Update (~19:40 IST)

**Resource gate:**

| Time | RAM used | CPU | ChatGPT | Chrome | Gate |
|---|---|---|---|---|---|
| baseline | 97.2 % | 73–100 % | 14 processes | 21 processes | fails |
| recheck | 97.6 % | 100 % | 14 processes | 22 processes | fails |

The VS Code installer has finished. **No container or service started.**

**M4:**
- `merge_run_output()` was extracted in `cortex/l6_agency/orchestrator.py`; behaviour is unchanged (shallow merge, nulls kept, as with jsonb `||`).
- Tests:
  - `test_m4_merge_keeps_null_keys_and_is_shallow_like_jsonb_concat`: **PASS**.
  - `test_m4_mysql_json_merge_patch_would_drop_the_null_key`: **BLOCKED** (needs DB).
- DB-free regression set: **6 passed** (`-k "bool_columns or row_turns or m9_datetimes or no_insert_ignore or m10 or merge_keeps"`).

**Status:**
- **PASS:** M4 (merge semantics), M8, M9, M10.
- **BLOCKED (DB down):**
  - M1, M2, M3, M5, M6, M7 DB verification;
  - H10;
  - H3, H4, H9 route tests;
  - the 8 module tests;
  - PERF-2;
  - full suites, build, E2E.
- **NOT RUN:** CI (no runner).
