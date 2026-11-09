# Capital Cortex: MySQL 8.4 Test Evidence

**Latest results:** see "Final local validation (2026-11-09)" at the end. The sections below are the earlier record.

**Session:** 2026-11-07, 22:25–00:00 IST.
**Logs:** kept outside this repository (they contain machine-specific paths).
**History:** earlier runs (U1, U2, I1, R1, D1) are not repeated here.

**Environment:**
- MySQL 8.4.13 test server `capital-cortex-mysql-test` (127.0.0.1:53306).
- Keycloak demo on :8380.
- Python 3.12.15; pytest 9.1.1; asyncmy 0.2.17; SQLAlchemy 2.0.55.
- Node 24.18.0.

**Host:** 15.6 GB RAM, 0.7–2.4 GB free. Heavy jobs ran one at a time; AIOT and DAPRO were not touched.

No credential value appears in any log. The E2E credentials were loaded from `.env` into the process environment only.

| ID | What | Command (abridged) | Database | Result | Log |
|---|---|---|---|---|---|
| T1 | H8/H11 value tests + M6 tests | `pytest tests/unit/test_mysql_h8_h11_values.py tests/unit/test_mysql_medium_defects.py -k "h8 or h11 or m6" -rA --junitxml` | `cortex_unit` | **8 passed** | `ver1_ver3.log`, `ver1_ver3_junit.xml` |
| T2 | Mutation check: the tests with `json_obj` swapped back to the pre-fix pass-through at the 4 fix sites (scratch pytest plugin; application code untouched) | `pytest … -p revert_json_obj` | `cortex_unit` | **7 of 7 failed** (6 H8/H11 + the M6 archival test). Each failure shows the original defect (`investing at [, ", s, e, …`, `dd_tags` as a string, double-encoded M6 payload, character-listed eligibility fields). The M6 integrity test was written after this run and **was not part of it** | `ver1_ver3_mutation.log` |
| T3 | Full unit suite (before PERF-2) | `pytest tests/unit -q --junitxml` | `cortex_unit` | **592 passed, 0 failed, 0 skipped** (688 s) | `unit_full.log`, `unit_full_junit.xml` |
| T4 | Schema drift, all application databases | `check_mysql_schema_drift.py --reference cortex_unit --targets cortex cortex_integration cortex_demo` | 4 databases | **0 of 3 drift**, all at `m0004_reconcile_legacy_layouts` | `drift_all4.log` |
| T5 | Integration suite (after PERF-2) | `pytest -m integration tests/integration -rs --junitxml` | `cortex_integration` | **20 passed, 3 skipped** (AGE ×2, pgvector HNSW: PostgreSQL-only by design), 0 failed (421 s) | `integration.log`, `integration_junit.xml` |
| T6 | PERF-2 profile before/after, `EXPLAIN ANALYZE`, payload parity, equivalence, parity tests | `scripts/profile_dashboard.py`, scratch scripts, `pytest tests/unit/test_mysql_perf2_dashboard.py tests/unit/test_mysql_router_sql.py` | `cortex_demo`, `cortex`, `cortex_bench_1m` (read-only); tests on `cortex_unit` | payload **IDENTICAL**; 200k: 45.7 s → 6.9 s; tests **18 passed** | `perf2_*.log`, `perf2_payload_*.json`, `perf2_tests_junit.xml` |
| T7 | Runtime verification | `scripts/verify_mysql_runtime.py` (`MYSQL_TEST_DATABASE=cortex`) | `cortex` | **all checks passed**; own rows removed; audit chain 1061 records verified | `verify_mysql_runtime_cortex.log` |
| T8 | Frontend | `npx vitest run`; `npx eslint .`; `npx tsc -b --noEmit`; `npx vite build --outDir <scratch>` | – | **6/6**; clean; clean; **build OK** (2 min 7 s) | `fe1_*.log`, `fe2_vite_build.log` |
| T9 | E2E (demo stack started with `CORTEX_MYSQL_DEMO_START.ps1`, then stopped) | `npx playwright test e2e/phase1.spec.ts`, then `npx playwright test` (`E2E_BASE_URL=http://localhost:5373`) | `cortex_demo` | phase 1 **PASS**; full suite **6 passed, 0 failed, 2 skipped** (admin credentials not provisioned) | `demo_start.log`, `e2e_phase1.log`, `e2e_full.log` |
| T10 | RB-1: current code on PostgreSQL | `CORTEX_TEST_DIALECT=postgres pytest -m integration tests/integration` (throwaway testcontainer, image `capital-cortex/postgres:16-age1.5.0-pgvector0.8.0`) | ephemeral PG | **13 passed, 8 FAILED, 2 skipped**. Cause: MySQL-only SQL in `graph_writer.py` | `rb1_postgres_integration.log`, `…_junit.xml` |
| T11 | RB-1: pre-migration release on PostgreSQL | `git archive HEAD` (commit `f2c447a`) to the scratch directory; its own `pytest -m integration tests/integration` with `PYTHONPATH` set to the export (imports confirmed to resolve there; current `.venv` dependencies) | ephemeral PG | **21 passed, 0 failed** | `rb1_head_release_pg.log`, `…_junit.xml` |
| T12 | U-FINAL: full unit suite + ruff on the final code (after PERF-2) | `pytest tests/unit -q --junitxml`; `ruff check .`; `ruff format --check .` | `cortex_unit` | **596 passed, 0 failed**; ruff clean | `unit_final.log`, `unit_final_junit.xml`, `ruff.log` |

Supporting evidence:
- `mysql_server_settings.log`: server variables, collations, driver versions.
- `secret_value_scan_worktree.log`: no `.env` secret value appears outside `.env*` (635 files).

## 1. Tests added this session

| File | Tests | Purpose |
|---|---|---|
| `tests/unit/test_mysql_h8_h11_values.py` (new) | 6 | H8/H11 value-level (VER-3) |
| `tests/unit/test_mysql_medium_defects.py` | +1 (`test_m6_retention_dry_run_and_legal_holds_leave_signals_intact`) | M6 data integrity |
| `tests/unit/test_mysql_perf2_dashboard.py` (new) | 4 | PERF-2 parity with the previous SQL |

No existing test expectation was changed.

## 2. U-FINAL (T12)

Run on the final code, after PERF-2 and every test added this session:
- Unit suite: **596 passed, 0 failed, 0 errors, 0 skipped** (419 s).
- `ruff check .`: **All checks passed**.
- `ruff format --check .`: **237 files already formatted**.

Logs: `unit_final.log`, `unit_final_junit.xml`, `ruff.log`.

## 3. Database writes during this session

| Database | Writes |
|---|---|
| `cortex_unit` | test rows, always in rolled-back transactions |
| `cortex_integration` | integration fixtures (the suite manages its own tables) |
| `cortex` | runtime verification: 6 rows written and removed; 1 append-only audit record kept |
| `cortex_demo` | whatever the E2E specs do through the demo app (not itemised) |
| `cortex_bench_1m` | read-only |
| Other MySQL databases, every PostgreSQL database, AIOT/DAPRO | **untouched** |

---

# Verification of the commit candidate (2026-11-09)

**What was tested:** exact copies of the candidate commit, built outside the repository from `HEAD` plus the listed files. These are local results. Nothing is committed, so they do not describe pushed code.
**Logs and exit codes:** kept outside this repository (they contain machine-specific paths).
**Environment:** MySQL 8.4.13, Python 3.12.15, Node 24.18.0, Windows 11, 0.6–3.8 GB free RAM. Steps ran one at a time.

## Import checks: which files are really needed

| Tree | Paths | Import of all 145 modules | Test collection |
|---|---|---|---|
| Migration only | 277 | **exit 1**: 3 modules fail (`ingestion`, `api.app`, `routers.sources`), all on missing `normalizer.accept` | **exit 2**: 9 collection errors |
| Plus 10 required files | 287 | exit 0 | exit 0, 663 tests |
| Full candidate | 308 | exit 0 | exit 0, 663 tests |

## Full candidate (308 paths)

| Check | Exit | Result |
|---|---|---|
| Ruff check, Ruff format | 0, 0 | clean |
| mypy | 0 | no issues, 145 files |
| Import contracts | 0 | 2 kept |
| Unit (`unit_full_lf`) | **0** | **639 passed, 0 failed** |
| Integration on MySQL | **0** | **20 passed, 3 skipped, 0 failed** |
| Contract | 0 | 1 passed |
| Eval gates | 0 | pass |
| OpenAPI regenerated in the tree | 0 | identical to `docs/openapi.json` |
| Production build | **0** | built |
| Browser E2E, default 5 s wait | **1** on all 3 runs | Latest full run: **5 passed, 1 failed, 2 skipped** |
| Phase 1 spec alone, 30 s wait (diagnostic) | **0** | 1 passed |

**Browser failure.** `phase1.spec.ts` timed out on a 5-second visibility wait at a different step on each run (Scoring Studio, Kanban, Sources). The API returned 200, the expected data is in `cortex_demo`, and the spec passes with exit code 0 when given 30 seconds. The cause is page-load time on a loaded host, not a found code defect. **There is no clean exit-0 run of the full browser suite at the default wait on the final tree.**

**Skips.** The 3 integration skips are Apache AGE and pgvector tests, which exist only on PostgreSQL. The 2 browser skips (approver release, Admin screen) need `CORTEX_ADMIN_EMAIL` and `CORTEX_ADMIN_PASSWORD`, which are not provisioned.

**Failures investigated:**
- The first unit run failed 1 test (`unit_full`, exit 1) because the export wrote shell scripts with CRLF under `core.autocrlf=true`. The index holds them as LF. Re-exported with conversion off: exit 0.
- The import check on the re-exported tree hit its 600-second timeout once with no output. Cause not found. A later retry passed with exit 0 (`import_D_lf_retry2`); `import_D_lf_retry` failed on a path mistake in the command.
- Running only the 287-path tree failed 8 further unit tests (`unit_tier1_only`), which identified 6 more required files.

**Not run:** PERF-1 (needs 4 GB free), full-stack `scripts/smoke.py`, Docker image build, CI, MySQL 8.0.

Previous run, 2026-11-08, including new regression tests for AUD-3 to AUD-10. Its build and browser runs have no recorded exit codes and are superseded by this section.

# Final local validation (2026-11-09)

Run after the pre-push security and configuration fixes. These are local results. Nothing is committed.

| Check | Result |
|---|---|
| Import of all modules | 143 modules, 0 failures |
| Ruff check and format, mypy, import contracts | Pass (145 files typed, 2 contracts kept) |
| Unit | 633 passed. 6 failed on the first run because the live Keycloak tests pointed at a stopped port (58480) |
| Live Keycloak tests with `KEYCLOAK_TEST_URL=http://localhost:8380` | 10 passed. No single run covers all 639 |
| Integration on MySQL | 20 passed, 3 PostgreSQL-only skips |
| Contract, evals, OPA | Pass (OPA 24 of 24) |
| OpenAPI compared with `docs/openapi.json` | Identical |
| TypeScript, ESLint, Vitest, production build | Pass (6 Vitest tests) |
| Browser E2E | 8 passed, 0 failed, 2 skipped, exit code 0 |
| Docker web image | Built |

**Not completed:** the two admin browser flows (`CORTEX_ADMIN_*` not configured), the Docker API image (build timed out
at 560 s on a loaded host), PERF-1 (needs 4 GB free), CI (needs a pull request) and the full-stack smoke test.
