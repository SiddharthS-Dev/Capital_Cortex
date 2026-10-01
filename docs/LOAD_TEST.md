# Load test: 1M-node CKG (R3, §14), 2026-09-30

**Verdict: the §14 load gate passes** after the application fixes (§5). All five endpoints are mixed at the team
rate for 5 min with 0 errors: dashboard p95 1.87 s (SLO 3 s), list 1.08 s (3 s), neighbourhood 143 ms (5 s), paths
91 ms (5 s), rescore 148 ms (10 s). At 3× the team rate, the graph endpoints and rescore still pass, but the list
(3.3 s) and dashboard (5.2 s) exceed their SLO. There are still no errors and no DB crashes (§5.2).

§2–§4 record the first run, before the fixes: the dashboard at 28 s, the neighbourhood over 60 s, and a mixed run
that failed everywhere, with path-finder backends OOM-killed. Migration `0005_load_indexes` was necessary but not
sufficient.

## 1. Setup

| | |
|---|---|
| Graph `ckg` | **1,000,000 vertices**: Signal 390k, Opportunity 200k, Contact 200k, Organization 150k, Investor 30k, Fund 20k, GrantProgram 10k |
| | **1,000,300 edges**: OFFERS 210k, KNOWS 200.3k, DERIVED_FROM 200k, MENTIONS 190k, INTRODUCED 100k, RELATES_TO 50k, PART_OF 30k, MANAGES 20k |
| Relational | organization 150k, opportunity 200k (score, band, factors ~2.5 KB, 11 classes, 25 countries, 9 stages), signal 390k, contact 200k, relationship 200k, investor 30k, fund 20k, grant_program 10k, 18 financial snapshots; mirrors `entity` 1.0M, `relationship_edge` 1.0M. All rows `is_demo = true`, `source_ref = {"kind": "synthetic_seed", "generator": "tests/load/seed_1m.sql"}`, with fictional names |
| Shape | 20% of opportunities belong to 1,000 hub organisations (~40 each); vertex `id` = relational uuid; database 2.66 GB |
| Seed | `tests/load/seed_1m.sql`, one transaction, 484 s + VACUUM ANALYZE 12 s (idempotent: skipped when present) |
| Database | `postgres-load`: same image and settings as `postgres` (PG 16.3, AGE 1.5.0, `shared_buffers` 512 MB, `max_connections` 200); capped at 2 GB RAM / 6 CPU, no swap (3 GB for passes before 14:05 local) |
| API | `api-load`: image `capital-cortex/api:dev`, current source tree, migrations at `0005_load_indexes`, **one uvicorn process** (as `api`), SQLAlchemy pool 10 + 20; capped at 1 GB / 2 CPU |
| Client | k6 2.3.0 (`grafana/k6:2.3.0`) on the compose network; a real `dev-analyst` access token from `scripts/devtoken.py` |
| Hardware | Windows 11 host, Docker Desktop VM with 16 vCPU / 7.4 GB RAM, shared with ~25 running containers from other projects |

**Traffic model** (`tests/load/cortex.js`): an open-model arrival rate for about 10–15 analysts active at once, each
acting about every 10 s. The Capital Cortex audience is one company's capital team. `RATE_MULT=3` is the stress run.

| Scenario | Request | Rate | SLO (p95) |
|---|---|---|---|
| dashboard | `GET /v1/dashboards/executive` | 0.1 req/s | 3 s |
| opportunities | `GET /v1/opportunities?limit=50` (Radar list; held to the dashboard SLO) | 0.5 req/s | 3 s |
| neighbourhood | `GET /v1/graph/query?template=neighbourhood&id=<uuid>&depth=2` (150 opportunities, 80 organisations, 20 hubs) | 0.3 req/s | 5 s |
| paths | `GET /v1/graph/paths?from=&to=` (600 connected 3-hop intro chains, 100 self-org warm intros, 50 random pairs) | 0.2 req/s | 5 s |
| rescore | `POST /v1/opportunities/{id}/rescore` | 0.3 req/s | 10 s |

## 2. Results

Result files: `tests/load/results/<utc>.json`.

### Per endpoint (clean runs; no DB crash, memory guard not tripped)

| Endpoint | Run | n | p50 | p95 | p99 | max | Errors | SLO p95 | |
|---|---|---|---|---|---|---|---|---|---|
| `GET /v1/opportunities?limit=50` | A2: list + rescore at the team rate, 5 min | 151 | 653 ms | **842 ms** | 924 ms | 1.19 s | 0% | 3 s | **PASS** |
| `POST /v1/opportunities/{id}/rescore` | A2 | 91 | 65 ms | **108 ms** | 139 ms | 169 ms | 0% | 10 s | **PASS** |
| `GET /v1/dashboards/executive` | B: 1 serial user, 3 min | 8 | 22.9 s | **28.2 s** | 29.9 s | 30.4 s | 0% | 3 s | **FAIL** |
| `GET /v1/graph/query` neighbourhood depth 2 | C: 1 serial user, 60 s timeout, 2 min | 2 | >60 s | **>60 s** | >60 s | >60 s | 100% (timeouts) | 5 s | **FAIL** |
| `GET /v1/graph/paths` | D2: 0.2 req/s, 3 min | 37 | 12 ms | **376 ms** | 2.96 s | 3.63 s | 0% | 5 s | **PASS**\* |
| `GET /v1/graph/paths` | D1: 1 serial user, 3 min | 12,815 | 10 ms | 24 ms | 36 ms | 6.80 s | 0% | 5 s | PASS\* |

\* In D1 the p95 was: connected 17 ms, warm intro 34 ms, random pair 20 ms. The max is the first call on a
connection (§4.3). Paths pass only while few connections run them concurrently.

Before the index migration, single requests with no load took: neighbourhood depth 1 **>300 s** (timeout); dashboard
25.4–32.0 s; list 0.82 s warm (12.7 s cold cache); rescore 0.13 s.

### Mixed and stress runs

| Run | What happened |
|---|---|
| E: all five mixed, team rate, 3 min (`make load` default) | Every endpoint failed. p95: list 37 s (93% errors), rescore 29 s (21%), dashboard 37 s (100%), neighbourhood 37 s (100%), paths 37 s (84%). Path-finder backends were OOM-killed repeatedly inside the DB container's 2 GB limit (`terminated by signal 9`), and each kill made Postgres run crash recovery, failing every in-flight query. |
| F: dashboard + list + rescore mixed (no graph), team rate, 3 min | Every endpoint failed without any DB crash. One dashboard request per 10 s drove list p95 from 0.84 s to **60 s** (93% timeouts) and rescore from 0.11 s to **52 s**. The dashboard hit 100% timeouts. Its synchronous Python blocks the only event loop (§4.2). |
| Stress: list 2 req/s + rescore 1 req/s (≈4×/3× team rate), 5 min, first run | List p95 45.4 s (21% errors), rescore p95 9.5 s (31% errors). The list's facet queries saturated the DB's 6 CPUs. Without the memory caps added afterwards, the Docker VM ran out of memory and its OOM killer took `capital-cortex-keycloak-1` (restarted; no other project's containers were affected). OPA calls timed out, and the API failed closed with 403s. |

## 3. Before/after migration `0005_load_indexes`

AGE creates its label tables **without any index** on the graph-id columns: vertex `id`, edge `start_id`/`end_id`.
The only existing indexes were the GIN `properties` indexes from `0002`, which serve the `{id: $id}` lookup in
~20 ms. Every hop is a join on those unindexed columns. `0005` adds btree indexes on `id` for all 17 vertex labels,
and on `id`/`start_id`/`end_id` for all 14 edge labels (59 indexes), in 11 s on the 1M graph.

| Query (1M graph, warm) | Before | After 0005 |
|---|---|---|
| API neighbourhood, depth 1 (undirected) | >300 s | >60 s: the query shape problem remains (§4.1) |
| Directed 2-hop out→out from a hub organisation | 144 ms | 78 ms |
| Directed 2-hop in→out from a hub organisation | 128 ms | 13 ms |
| Directed 1-hop in/out from an opportunity | – | 0.2–1.6 ms |
| `MATCH (a:Organization {id}),(b:Opportunity {id}) MATCH (a)-[r:OFFERS]->(b)` (the `graph_writer.upsert_edge` pattern) | 22.7 ms | 22.5 ms |
| Paths (VLE) | in-memory, unaffected | unaffected |

The index keeps per-hop cost flat as edge tables grow, instead of scanning them. It is required for the rewrite
in §4.1, but on its own it fixes neither failing SLO.

## 4. Findings from the first run (all fixed; see §5)

### 4.1 Graph neighbourhood: the undirected hop can't use an index (`cortex/l8_actuation/api/routers/graph.py`, `query`)
- AGE compiles `(n)-[r]-(m)` into one join clause:
  `(r.start_id = n.id AND r.end_id = m.id) OR (r.end_id = n.id AND r.start_id = m.id)`.
- PostgreSQL can't derive an `n`-only index condition from that OR. So the plan enumerates every vertex `m`
  (1,000,011 rows), and per `m` it probes the edge indexes. Before `0005`, it ran a nested loop over all edges ×
  all vertices (estimated cost 7.6 × 10¹¹).
- **Fix:** issue directed patterns and merge them in Python: `(n)-[r]->(m)` plus `(n)<-[r]-(m)` for depth 1, and
  the four direction combinations for depth 2, each with `LIMIT`. Alternatively, traverse the relational mirror
  (`relationship_edge`, indexed by `ix_edge_from`/`ix_edge_to`) and fetch the vertices by id. Measured cost: 13–80
  ms per branch on a hub, so **≈0.1–0.3 s per request**. The `provenance` template is directed already.

### 4.2 Executive dashboard: every active opportunity is aggregated in Python, on the event loop (`cortex/l5_strategy/pipeline_engine.py`, `routers/dashboards.py`)
- `weighted_pipeline()` and `expected_inflows()` load every active opportunity (190,000 rows) into Python for each
  request. The full-table SQL itself takes 175 ms warm; the 23–30 s is Python row handling and aggregation.
- The handler is `async`, so the CPU-bound loop **blocks the only uvicorn event loop**: every other request waits
  (run F).
- **Fix:**
  - aggregate in SQL: `sum(amount_mid × stage probability)` grouped by currency, stage, class, first geography
    and deadline month, with the probabilities from a `VALUES` list; do the inflow buckets per month in SQL;
  - cache the payload per org for 30–60 s (Redis) and invalidate it on `opportunity.updated`;
  - move any remaining heavy work off the loop (`run_in_threadpool`);
  - run ≥ 2 uvicorn workers in production (an infra change, but it only isolates the damage).

### 4.3 Path finder: AGE VLE keeps a copy of the whole graph in memory per connection (`routers/graph.py`, `paths`)
- `[*1..4]` uses AGE's variable-length-edge machinery. On first use, a backend loads all 1M vertices and 1M
  edges into memory: **6.8–37 s** (warm/cold) and **~950 MB RSS per backend**. Later calls on that connection take
  10–30 ms. Indexes don't help.
- The API pool (10 + 20) can end up with that many copies. In run E, the DB container's 2 GB limit killed the
  backends, and each kill reset the whole server. Without a limit, the host swaps or OOM-kills something else.
- **Fix:**
  - replace VLE with a bounded bidirectional BFS over `relationship_edge` (a recursive CTE capped at 4 hops, or
    two 2-hop frontiers joined in the middle), or with a union of fixed-length directed patterns;
  - at minimum, run path queries on a dedicated 1–2-connection pool with `statement_timeout`, so the number of
    graph copies is bounded.

### 4.4 Opportunity list: facet queries on every page (`routers/opportunities.py`, `list_opportunities`)
- Each request runs the page query, `count(*)`, and five facet `GROUP BY`s over every matching row (190k, with 3
  LEFT JOINs): ~0.65 s warm and ~1.2 CPU-s of DB time. That passes at 0.5 req/s and saturates 6 CPUs at ~2 req/s.
- **Fix:**
  - return facets only on the first page or on a filter change (make `facets` default false for pagination);
  - cache facet counts ~30 s;
  - join `signal`/`source` only when the `source` filter or facet is requested.

### 4.5 Rescore: fine
65 ms p50 / 108 ms p95 at the team rate. It degrades only when the event loop is blocked (run F).

## 5. After the application fixes (2026-09-30, 15:44 and 15:50 local)

| Finding | Fix | Decision |
|---|---|---|
| 4.1 neighbourhood | walks `ckg._ag_label_edge` by graph id with the 0005 indexes (`cortex/l2_representation/graph_traversal.py`); matches the Cypher result node-for-node on the live graph | D-076 |
| 4.2 dashboard | weighted pipeline as one grouping-sets query; the forecast buckets inflows by month once and runs in a worker thread; dashboard and alert presets use inflows grouped in SQL (identical totals: 0.00 difference on live and load data) | D-077 |
| 4.3 path finder | bidirectional BFS over the label tables (frontier cap, 5 s statement timeout); no VLE, so no per-backend graph copy; shortest hop counts match Cypher on sampled pairs | D-076 |
| 4.4 list facets | total + four facets in one grouping-sets scan (was six queries) | D-077 |
| scan bugs | multipart/validation 500, NUL byte 500, DLQ id 500, Copilot mid-stream raise, missing CORP: all fixed with regression tests (`tests/unit/test_scan_regressions.py`) | D-078 |

Single-request timings on the load DB: the dashboard went from 25–32 s to about 1.05 s. The forecast went from
2,046 ms per-opportunity to 145 ms grouped (53,334 inflow opportunities).

### 5.1 Mixed, team rate, 5 min (`make load`), result `tests/load/results/20260930T101959Z.json`

| Endpoint | n | p50 | p95 | p99 | max | Errors | SLO p95 | |
|---|---|---|---|---|---|---|---|---|
| `GET /v1/dashboards/executive` | 30 | 1.75 s | **1.87 s** | 2.38 s | 2.58 s | 0% | 3 s | **PASS** |
| `GET /v1/opportunities?limit=50` | 151 | 927 ms | **1.08 s** | 1.52 s | 2.15 s | 0% | 3 s | **PASS** |
| `GET /v1/graph/query` neighbourhood depth 2 | 91 | 53 ms | **143 ms** | 221 ms | 261 ms | 0% | 5 s | **PASS** |
| `GET /v1/graph/paths` | 61 | 51 ms | **91 ms** | 173 ms | 224 ms | 0% | 5 s | **PASS** |
| `POST /v1/opportunities/{id}/rescore` | 90 | 84 ms | **148 ms** | 255 ms | 323 ms | 0% | 10 s | **PASS** |

The minimum free VM memory was 3,179 MB, so the guard never tripped. An intermediate run (before inflows were
grouped, result `20260930T101236Z.json`) passed everything except the dashboard, at 4.3 s.

### 5.2 Stress, 3× team rate, 5 min, result `tests/load/results/20260930T102554Z.json`

| Endpoint | n | p95 | Errors | SLO p95 | |
|---|---|---|---|---|---|
| dashboard | 91 | 5.20 s | 0% | 3 s | over |
| opportunities list | 450 | 3.28 s | 0% | 3 s | over |
| neighbourhood | 271 | 345 ms | 0% | 5 s | pass |
| paths | 181 | 289 ms | 0% | 5 s | pass |
| rescore | 271 | 385 ms | 0% | 10 s | pass |

At 3× the load is DB-CPU-bound: each list and dashboard request still scans the 190k active opportunities for
counts. The next levers, not needed at the team rate:
- a 30–60 s Redis cache for facets and the dashboard payload, invalidated on `opportunity.updated`;
- two or more uvicorn workers;
- a partial index / materialised counts for active opportunities.

## 6. Reproduce

```
make load                                   # or ./make.ps1 load: seed if needed, all five mixed, 5 min, SLO thresholds
python scripts/load_test.py --scenarios opportunities,rescore --duration 5m
python scripts/load_test.py --scenarios dashboard --mode serial --vus 1 --duration 3m
python scripts/load_test.py --scenarios neighbourhood --mode serial --vus 1 --duration 2m --timeout 60s
python scripts/load_test.py --scenarios paths --duration 3m --timeout 60s
python scripts/load_test.py --rate-mult 3   # stress
```

State after the test: `api-load` and `postgres-load` are **stopped**. The load database is **kept** in volume
`capital-cortex_pgload` (2.7 GB), so the next `make load` skips the 8-minute seed. To drop it:
`docker compose -f infra/docker-compose.yml --profile load rm -sf postgres-load && docker volume rm capital-cortex_pgload`.
