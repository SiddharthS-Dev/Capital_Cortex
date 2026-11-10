# Capital Cortex: MySQL Performance Report (PERF-1, PERF-2)

**Date:** 2026-11-07, 23:00–00:00 IST.
**For:** Project Lead, Engineering, DBA.
**Evidence:** benchmark logs, kept outside this repository (they contain machine-specific paths).

**Environment:** MySQL 8.4.13 test server with a 512 MB buffer pool, on a workstation at 92–96 % RAM (0.7–1.2 GB free, 31+ containers). Absolute times on this host are **pessimistic and noisy**. The before/after ratios were measured on the same host, minutes apart, and are the reliable figures.

## 1. PERF-2: `GET /v1/dashboards/executive`

### 1.1 What the historical "1.7 s / 3.6 s" was

The 2026-11-04 E2E trace measured the dashboard at 3.6 s, but **in the same trace `/v1/me` took 3.6 s and `/v1/meta` 5.0 s**. Those are trivial endpoints, so the slowness was host saturation (ENV-2), not dashboard SQL. The endpoint's own work on the E2E data set is far below that (§1.4).

### 1.2 Measured bottleneck (`EXPLAIN ANALYZE`, `cortex_bench_1m`, 200 000 opportunities)

1. **`weighted_pipeline`:** MySQL **inlines the CTE into every one of the five `UNION ALL` branches**. The 165 MB `opportunity` table was read **five times**, and a sixth time for the "excluded without amount" count. Total 21.2 s in the plan; 23.5 s median in the profiler. (`perf2_explain_pipeline_bench.log`)
2. **Four count queries** (active, funnel, class mix, band mix): the optimizer chose `ix_opp_stage` (org_id, pipeline_stage) and then **read every full row to test `status`**: 3.4 s each. The covering index `ix_opp_facets` (org_id, status, is_demo, class, pipeline_stage, score_band, …) does the same work in 1.1 s. (`perf2_explain_counts_bench.log`)
3. **Forecast:** 3 scenarios share **one** data load; the CPU work is about 11 ms. **Not a bottleneck**, contrary to the 11-04 hypothesis.

### 1.3 Change (MySQL branch only; the PostgreSQL branch is untouched)

| File | Change |
|---|---|
| `cortex/l5_strategy/pipeline_engine.py` | `weighted_pipeline`: **one** scan grouped by (class, stage, geo, month, currency, no-amount), rolled up per dimension in Python. Group sums are exact `DECIMAL`s and are summed as `Decimal`, then rounded exactly as before |
| `cortex/l8_actuation/api/routers/dashboards.py` | new `_mix_mysql`: active count, funnel, class mix and band mix from **one** `GROUP BY` over `USE INDEX (ix_opp_facets)` (present since migration m0003 on every database). Same keys, counts and count-descending order as `_counts` |

The `pipeline` dashboard and the agent tool also use `weighted_pipeline`, so they benefit automatically. API shapes and results are unchanged.

### 1.4 Before / after

| Data set | Measure | Before | After | Factor |
|---|---|---|---|---|
| `cortex_demo` (1 026 opportunities; the E2E data) | whole endpoint function, median of 7 | **328 ms** (max 449) | **229 ms** (max 368) | 1.4× |
| `cortex_demo` | `weighted_pipeline` | 156 ms | 37 ms | 4.2× |
| `cortex_bench_1m` (200 000 opportunities) | whole endpoint function | **45.7 s** (median of 3) | **6.9 s** (median of 3; 9 statements) | **6.6×** |
| `cortex_bench_1m` | weighted pipeline SQL | 16.5 s (old query alone, same session) | 3.4 s | 4.9× |

### 1.5 Correctness evidence

| Check | Result |
|---|---|
| Executive payload, `cortex_demo`, before vs after (every key and value) | **IDENTICAL** (`perf2_payload_parity.log`) |
| `_mix_mysql` vs the four original queries, `cortex_demo` and `cortex`, with and without demo rows | equal maps, equal active count, count-descending order (`perf2_mix_equivalence.log`) |
| New vs old `weighted_pipeline` SQL at 200k rows | totals, splits and counted **equal** (`perf2_profile_bench200k_after.log`) |
| Regression tests `tests/unit/test_mysql_perf2_dashboard.py` (4): old vs new SQL on edge cases (two currencies, min-only / max-only / no amount, empty currency, NULL class, empty geography, no deadline, lost stage, odd cents) | **4 passed** (`perf2_tests.log`) |
| `tests/unit/test_mysql_router_sql.py` (pipeline engine, facets, inflows) | passed |

### 1.6 What remains at large volume

At 200k rows, two **full-row reads** remain: the pipeline aggregate (3.4 s) and the geography `JSON_TABLE` expansion (2.6 s). Both need columns that can't sit in a B-tree index (amounts, the `geography` JSON array), so they are I/O-bound here: a 512 MB buffer pool under host memory pressure. On a production server whose buffer pool holds the working set (INFRA-1), both should be memory scans. **Not measured here; re-measure on the production-sized test host.**

Options if they are still too slow at real volume (Project Lead decision; not implemented):
- (a) A short-TTL cache (30–60 s) for the executive payload. The page already refetches every 60 s.
- (b) A summary table maintained by the scoring and ingest jobs.
- (c) A multi-valued index on `geography`.

### 1.7 E2E

The E2E "Key figures" assertion (5 s, including login and page bootstrap) depends on this endpoint on `cortex_demo`, where its own time is now about 0.23 s.

**Re-run 2026-11-07 23:33–23:40** on the demo stack (API, worker and web started from the changed code; Keycloak, OPA, Redis, MySQL test server):
- `e2e/phase1.spec.ts`: **PASS** (was FAIL on 2026-11-04).
- Full suite: **6 passed / 0 failed / 2 skipped**. The two skips are admin and approver flows; they need `CORTEX_ADMIN_EMAIL` / `CORTEX_ADMIN_PASSWORD`, which aren't provisioned in `.env`.
- Logs: `e2e_phase1.log`, `e2e_full.log`.

Host memory was 1.0–2.1 GB free during the run.

## 2. PERF-1: search

**Status: NOT RUN this session.** `scripts/perf1_search_options.py --build` creates n-gram FULLTEXT indexes over `cortex_bench_1m` (200k rows, 165 MB table). On a host with 0.7 GB free, the index build would push MySQL and the workstation into swap. The resulting numbers would describe the host, not the options.

| Option | Description | Prior measurement |
|---|---|---|
| A | FULLTEXT only | 1.2 s (2026-11-04) |
| B | A + FULLTEXT on counterparty name | not measured |
| C | n-gram FULLTEXT (title, counterparty) | not measured |
| D | keep the current behaviour (FULLTEXT + `LIKE`) | 6.1 s warm / 13.4 s cold (2026-11-04) |

**Requirement:** a host with ≥ 4 GB free. Then: `python scripts/perf1_search_options.py --build`, then `--runs 5 --json perf1.json` (measures latency, recall and precision against the current results). **Decision: Project Lead.** No search semantics are changed without approval.
