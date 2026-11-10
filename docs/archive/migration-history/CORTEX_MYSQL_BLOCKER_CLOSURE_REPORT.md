# Capital Cortex — MySQL 8.4 Blocker Closure Report

> **Historical record (dated 2026-10-31).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


**Dates:** 2026-10-31 · **Branch:** `feature/changes-login` (unchanged; nothing committed) · Evidence from runs on this machine.

## Update 2026-11-03: developer blockers closed (full register: `CORTEX_MYSQL_BLOCKER_REGISTER.md`)

**Counts:** 28 blockers tracked. **14 VERIFIED_CLOSED**, 4 OPEN, 2 EXTERNALLY_BLOCKED (B1, B2), 8 REQUIRES_APPROVAL (including B3).

| Area | What changed | Evidence |
|---|---|---|
| Least privilege (MB-06) | The `cortex` account lost every server-wide privilege (SUPER, CREATE USER, SYSTEM_USER, …). It now has ALL on `cortex`, `keycloak` and `cortex\_%` only. The test server runs with `--log-bin-trust-function-creators=1` | Refusals 1227/1227/1044; the account built a full schema with 4 triggers by itself; unit and integration suites green as this account |
| Secrets (MB-02, MB-03, MB-05, MB-25) | No MySQL password literal is left in compose, code, scripts, tests or the launcher. The healthcheck uses `MYSQL_PWD`. Tests load `MYSQL_TEST_*` from the git-ignored `.env` | Grep clean; `ps` shows no `-p`; new regression tests |
| Schema drift (MB-09, MB-10, MB-12) | New read-only `scripts/check_mysql_schema_drift.py`. New revision `m0004_reconcile_legacy_layouts`: rebuilds only empty legacy tables and converts an ENUM only when every value is valid | `cortex_demo`, `cortex_integration`, `cortex_bench_1m`, `cortex_migrate_check`, `cortex_unit`: **OK at m0004**. `alert_delivery` now has `target`/`detail` |
| Remaining drift (MB-11) | `cortex.opportunity.pipeline_stage`: 6 old test rows hold `screening`, which has no baseline equivalent | **REQUIRES_APPROVAL**: choose a mapping or archive the rows |
| Tests (MB-13, MB-14, MB-16) | Scoring-profile isolation fixed; old-vocabulary test data corrected; no assertion weakened | **Unit 383 passed / 0 failed** (`MYSQL_TEST_DATABASE=cortex_unit`). **Integration 21 passed / 0 failed / 3 skipped** (PostgreSQL-only) |
| Demo (MB-17) | Restarted on the current code | **Smoke 10/10** with MFA enforced for the run; data persisted (1,026 opportunities) |
| Backup (MB-18) | Encrypted backup → verify → restore into a new database | PASS: 50 tables, 218 rows, 4 triggers, **0/50 checksum mismatches**; overwrite refused |

**Not closable from code:**
- B1/B2 (DevOps).
- B3 and the decisions MB-07, MB-11, MB-19 to MB-23 (Project Lead).
- MB-08: stopping the exposed stack-test MySQL needs your permission; the command is in the register.

## Update 2026-11-02: real-data rehearsal from the local PostgreSQL

- **Source identified:** the local volume `capital-cortex_pgdata` is a **development** database, not production: PostgreSQL 16, 39 MB, alembic `0005_load_indexes`. All 600 opportunities are `is_demo`, created 2026-10-23, with provenance `synthetic_seed`; Keycloak holds only the 9 dev-realm users. Production data is still unavailable (B17 unchanged).
- **Method, with no change to the source:** with the original volume mounted **read-only**, it was cold-copied to `capital-cortex-rehearsal_pgcopy`. The copy was verified **byte-identical** (2,520 files by checksum). A disposable PostgreSQL (`cortex-pg-realdata`, 127.0.0.1:55434) ran on the copy and completed normal crash recovery.
- **New defect found (B25), now CLOSED:** the first run's preflight refused to migrate, because `signal`, `meeting` and `proposal` have `legal_hold` in PostgreSQL (`0004_phase3`) but not in MySQL. The same gap also broke the **retention job on MySQL** (`retention._held_sql` filters on that column).
  - **Fix:** new schema-history revision `migrations_mysql/versions/m0002_legal_hold_columns.py` (conditional `ADD COLUMN`), plus the same columns in `scripts/schema_mysql.sql`.
  - **Applied to:** `cortex_pgcopy_rehearsal`, `cortex_demo`, `cortex` and `cortex_integration`, all now at `m0002 (head)`.
  - **Regression test:** `test_retention_held_filter_runs_on_every_holdable_table_mysql`.
- **Rehearsal result, PASSED:**
  - **48/48 tables** reconciled; **22 populated tables, 11,360 rows**;
  - **0 row-count and 0 checksum mismatches** (read back from MySQL), **0 orphans**;
  - audit lock present, audit chain valid; 53.7 s, after a clean dry run.
- **PostgreSQL dependency scan:**
  - **Runtime on MySQL needs no PostgreSQL** (verified: no PostgreSQL container, 0 PostgreSQL log references).
  - **PostgreSQL is still the default** in `platform_core/config/settings.py` (`database_url`), the base `docker-compose.yml` / `make.ps1 up`, 49 dual-path files, and `platform_core/db/age.py` (PostgreSQL-only, not called on MySQL).
  - Flipping defaults and removing the PostgreSQL paths is **APPROVAL REQUIRED (B26)**. It should happen in the cutover commit, because the migration tool still needs PostgreSQL as its source until the real data is moved.
- **Not done in this pass (still open):** the opportunity list/search optimisation to p95 < 2 s (B19), the Keycloak isolation benchmark (B20) and vector streaming/warm-up (B23).
- **Environment:** Docker Desktop stopped unexpectedly 3 times during this work; it's an operational risk for the demo machine.

## Summary

| | Count |
|---|---|
| Blockers tracked | **24** |
| **CLOSED** | **18** |
| **APPROVAL REQUIRED** (a business, product or infrastructure decision) | **4** |
| **BLOCKED BY EXTERNAL DEPENDENCY** | **2** |

**Fresh test results on the final code:**
- **Unit:** 299 passed, 0 failed, 0 skipped.
- **Integration:** 20 passed, 0 failed, 3 skipped (PostgreSQL-only AGE/pgvector tests). Run file by file, every file exit 0, no testcontainers fallback; details in `CORTEX_MYSQL_INTEGRATION_PROGRESS.md`, "Final closure run".
- **Project smoke test:** 10/10 on the demo stack and 10/10 on the isolated production stack.
- **1M benchmark:** 0 server errors.

**Production cutover is not complete.** No authorised real-data rehearsal has been possible (B17).

## Blockers

| # | Blocker | Root cause | Fix / action | Files | Evidence | Status |
|---|---|---|---|---|---|---|
| B1 | C: drive full (0.85 GB) | Docker build cache, plus large personal folders; `docker_data.vhdx` is not sparse | Approved `docker builder prune -af`: **3.825 GB** of build cache freed *inside* Docker (C: unchanged, as the virtual disk doesn't shrink). You then freed host space | — | Before: C: 0.85 GB, cache 3.825 GB. After prune: cache 0 B, C: 0.85 GB. Later: **C: 14.6–16.2 GB free**; 33 volumes intact | CLOSED |
| B2 | "3 shell scripts with CRLF" (earlier report) | **False positive**: Git Bash dropped the CR in `grep $'\r'`, so every line matched. `git ls-files --eol` shows `i/lf w/lf`, with 0 CR bytes | Real latent risk kept: `core.autocrlf=true` would write CRLF on the next checkout. Added `.gitattributes` (`*.sh`, `*.envsh` → `eol=lf`) | `.gitattributes` | `sh -n` passes for all 4 scripts in a Linux container; attributes now `text eol=lf`; Git's CRLF warnings gone | CLOSED |
| B3 | A test assertion that could never fail | `Path.read_text()` translates CRLF, so `"\r\n" not in text` was always true | Check bytes; new test that every container shell script is CR-free and pinned by `.gitattributes` | `tests/unit/test_mysql_schema_versioning.py` | 7/7 pass | CLOSED |
| B4 | Vector index memory at scale | `VectorIndex.fit` built Python float lists (measured **9.0×** the float32 size; about 7 GB at 200k) | Decode BLOBs straight into one float32 matrix | `platform_core/db/vector.py` | Old approach: 70.5 MiB for 7.8 MiB of data; new test enforces < 3× | CLOSED |
| B5 | Vector index cold build 577 s at 200k | `ORDER BY o.id` forced a temporary table and filesort of every 4 KB vector | `ORDER BY e.entity_id` (same order, served by `ix_embedding_lookup`) | `platform_core/db/vector.py` | EXPLAIN: filesort gone; fetch 116.6 s; benchmark cold build **143 s** (was 577 s); order verified identical | CLOSED (residual: 2+ min cold start at 200k; see B23) |
| B6 | Vector search 2.57 s p50 at 200k | scikit-learn `NearestNeighbors(metric="cosine")` per query | Exact cosine as one float32 matrix-vector product with precomputed norms | `platform_core/db/vector.py`, tests | **p50 77 ms, p95 ~94 ms**; new test matches a float64 reference ranking exactly; 12/12 vector tests | CLOSED |
| B7 | `GET /v1/opportunities` facets made 5 full scans on MySQL | No `GROUPING SETS` in MySQL; one UNION ALL branch per dimension | One `GROUP BY` over all dimensions, summed in Python (PostgreSQL path unchanged) | `cortex/l8_actuation/api/routers/opportunities.py`, tests | Facets identical to per-dimension SQL on `cortex_demo` and the 1M DB; demo endpoint 0.39 s | CLOSED (scale remainder in B19) |
| B8 | Audit chain duplicate `seq` under concurrent writes (500) | MySQL REPEATABLE READ: after taking `audit_lock`, the plain SELECT of the chain head used the transaction's older snapshot | Read the head with `FOR UPDATE` (a locking read sees the latest commit); PostgreSQL unchanged | `platform_core/audit/chain.py`, tests | New test **failed before the fix** (`Duplicate entry '548'`) and passes after; benchmark writes 0 errors; chain verifies 50,007 records | CLOSED |
| B9 | Benchmark data unrepresentative | Generator: one identical vector for all rows, wrong model name, no `org_id`, no audit rows | Real per-row embeddings (`hash-tf-1024-v1`), `org_id`, 50k hash-chained audit rows | `scripts/seed_mysql_load.py` | 1,150,002 rows loaded in 1,377.8 s; chain verifies | CLOSED |
| B10 | No application-path benchmark | The old harness timed hand-written SQL only | New harness: app functions in-process plus HTTP under concurrency with a real OIDC token; latency percentiles, CPU, memory | `scripts/benchmark_mysql_app_paths.py` | See the benchmark table below | CLOSED |
| B11 | Benchmark memory readings wrong | ctypes 64-bit handle truncation; the venv launcher PID isn't the interpreter | Explicit handle types; resolve the child interpreter PID | `scripts/benchmark_mysql_app_paths.py` | API reads 993 MiB (peak 2,693 MiB) instead of 0.6 MiB | CLOSED |
| B12 | Production stack: `migrate` failed (MySQL 1419) | Binary logging on → `CREATE TRIGGER` needs SUPER unless `log_bin_trust_function_creators` | `--log-bin-trust-function-creators=1` (binlog format is ROW, verified) | `infra/docker-compose.mysql.yml`, test | `migrate` exit 0 in the isolated stack | CLOSED |
| B13 | Production stack never started | — | Isolated run: project `capital-cortex-stacktest`, alternate ports, own volumes and image tag | (scratch override only) | MySQL, migrate (0), Keycloak, API (`/readyz` ready), worker, web, Redis, OPA all up; web `config.js` correct; **smoke 10/10**; **0 PostgreSQL references** in API/worker logs; no PostgreSQL container created | CLOSED |
| B14 | Keycloak first start interrupted → half-built schema | MySQL DDL isn't transactional; Liquibase can't resume (`MIGRATION_MODEL already exists`) | Procedure: never interrupt the first start; on a fresh install, start against a new empty database | Runbook | Recovery verified with a fresh database; the init script created `keycloak` on a fresh volume | CLOSED |
| B15 | Keycloak refresh, logout and roles unverified | — | Verified on MySQL-backed Keycloak | — | Refresh 200 (API accepts the new token); logout 204; refresh after logout 400 `invalid_grant`; forged token 401; roles and `aud` correct | CLOSED |
| B16 | Keycloak user/realm migration procedure | — | Rehearsed on the dev realm: `kc.sh export --users realm_file` → `kc.sh import` into a new database | Runbook | 9 users, 7 password + 1 OTP credentials, 10 clients, roles preserved | CLOSED (procedure) |
| B17 | **Real production-data rehearsal** | No Capital Cortex PostgreSQL backup exists: `cortex-backups` bucket empty; the dumps found belong to other projects | — | — | Searched Downloads, OneDrive, Documents, Desktop and the MinIO volume (read-only) | **BLOCKED BY EXTERNAL DEPENDENCY**: an authorised dump, or approval to run `.\make.ps1 backup` against the local `capital-cortex_pgdata` |
| B18 | **Production PostgreSQL location unknown** | Not on this host | — | — | — | **BLOCKED BY EXTERNAL DEPENDENCY** |
| B19 | Opportunity list/search slow at 200k opportunities | Facets aggregate the whole table on every list call; `q` search is `MATCH … OR LIKE '%q%'` (no index use); test buffer pool 512 MB vs 2.9 GB of data | Single-scan facets (B7) brought the 1M list from about 20 s to 15 s single-threaded | — | Under 8 concurrent clients: list p50 **32 s**, search p50 **37 s** | **APPROVAL REQUIRED**: cached or summary facets or facets on demand; search semantics; buffer pool sizing |
| B20 | Keycloak slow while MySQL is under heavy batch load | Keycloak shares the MySQL instance | — | — | Login 8 s, logout 6 s during the 1M load (normally under 1 s) | **APPROVAL REQUIRED**: a separate instance or scheduled batch windows |
| B21 | Commit / branch strategy | 80+ modified, 60+ untracked; branch named for login work | — | `CORTEX_MYSQL_GIT_REVIEW_REPORT.md` | — | **APPROVAL REQUIRED** |
| B22 | Start script hard-stopped below 1 GB; worker readiness used a fixed 8 s wait | — | `-AllowLowDisk` override; 45 s readiness poll | `CORTEX_MYSQL_DEMO_START.ps1` | Exit 0 with smoke 10/10 after a cold Docker start | CLOSED |
| B23 | 200k-vector index: 2+ min cold build, about 2.7 GB process peak | Index is per tenant, in memory, built on first query | B4–B6 cut time 4× and the memory pattern 9× | — | Cold 143 s; API peak 2,693 MiB | **APPROVAL REQUIRED** (folded into B19's capacity decision: warm-up on start, ANN index or a vector DB) |
| B24 | Earlier fixes (2026-10-30), re-verified | Contacts 500 (naive datetimes), source-runs 500 (SELECT without FROM), compose `depends_on` on a disabled postgres, missing `keycloak` DB, ETL coverage and reconciliation | Fixed previously | (see the implementation report) | Covered by the 299 unit tests and the stack run | CLOSED |

## 1M benchmark (final code)

Environment:
- **Dataset:** `cortex_bench_1m` on the isolated test MySQL 8.4.13 (512 MB buffer pool), 1,150,002 rows, 2,863 MiB: 150k organisations, 200k opportunities, 200k embeddings, 350k entities, 200k edges, 50k audit records.
- **Load:** 8 concurrent HTTP clients for 60 s, plus 100 in-process queries per path.
- **Host:** Windows 11, 8 logical CPUs, 15.6 GB RAM; Docker VM 8 CPUs / 7.6 GB.

| Path | Before fixes | Final |
|---|---|---|
| Vector index cold build (200k) | 576.6 s | **143.3 s** |
| Vector search, warm p50 / p95 / p99 | 2,570 / 4,476 / 5,134 ms | **77 / ~94 / ~102 ms** |
| Graph neighbourhood d2, p50 (in-process) | 212 ms | 20 ms * |
| Graph paths ≤3 hops, p50 (in-process) | 126 ms | 15 ms * |
| Audit chain verify (50k) | 28.8 s | 3.6 s * |
| HTTP opportunities list p50 (8 clients) | 86.9 s | 32.0 s |
| HTTP opportunity search p50 | 99.1 s | 37.5 s |
| HTTP opportunity detail p50 | — | 397 ms |
| HTTP graph neighbourhood / paths p50 | 317 / 346 ms | 82 / 104 ms |
| HTTP audit list p50 | — | 11 ms |
| HTTP write (`POST /v1/contacts`) p50 | 1,784 ms (1 of 3 failed with 500 in run 2) | **584 ms, 0 errors** |
| HTTP copilot retrieval, warm p50 | 8.7 s | 3.1 s |
| Server errors (5xx) | 1 | **0** |
| Throughput (8 clients) | 0.1 req/s | 0.5 req/s (bounded by the list/search endpoints) |
| MySQL container CPU avg / max | 97.6% / 1,056% | 165% / 858% |
| API process memory (working set / peak) | not measurable (harness bug) | 993 / 2,693 MiB |

\* These paths had no code change. Their gains come from a warmer buffer pool on later runs, so treat them as cache-sensitive. The HTTP sample is small (35 requests) because the slow list/search calls tie up the clients. **Vector search here is the local word-overlap embedder (`hash-tf-1024-v1`), not semantic search.**

## Commands (reproducible)

```powershell
.\.venv\Scripts\python.exe scripts\seed_mysql_load.py --scale 1.0 --db cortex_bench_1m           # 1,377.8 s
# API on the benchmark DB (port 8310), then:
.\.venv\Scripts\python.exe -u scripts\benchmark_mysql_app_paths.py --db cortex_bench_1m --api http://127.0.0.1:8310 --api-pid <pid> --duration 60 --concurrency 8
$env:KEYCLOAK_TEST_URL="http://localhost:8380"; .\.venv\Scripts\python.exe -m pytest tests/unit          # 299 passed
docker compose -p capital-cortex-stacktest --env-file <alt-ports env> -f infra/docker-compose.yml -f infra/docker-compose.mysql.yml -f <image-tag override> up -d --wait api worker web
```

## Left in place (nothing deleted)

- **Databases on the test MySQL:** `cortex_bench_1m` (2.9 GB), `cortex_demo`, `cortex_integration`, `cortex_rehearsal`, `cortex_migrate_check`.
- **Isolated stack:** project `capital-cortex-stacktest`, stopped, with its volumes (`capital-cortex-stacktest_*`, incl. databases `keycloak`, `keycloak_fresh`, `keycloak_import_check`) and image `capital-cortex/api:mysql-stacktest` (1.08 GB).
- **Keycloak export** of the *dev* realm: in the session's temporary folder. It contains dev password hashes and TOTP secrets; delete it when you no longer need it.
- **Removing any of the above needs your approval.**
