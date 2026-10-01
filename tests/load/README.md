# Load tests (R3, §14)

k6 against a 1M-node seed. SLOs: dashboards p95 < 3 s, graph queries p95 < 5 s, scoring p95 < 10 s. The opportunity
list is held to the dashboard SLO. **Latest results and analysis: [`docs/LOAD_TEST.md`](../../docs/LOAD_TEST.md)**.
As of 2026-09-30 the gate fails on the executive dashboard and the graph neighbourhood (app-code fixes listed there).

| File | What |
|---|---|
| `seed_1m.sql` | Bulk seed (psql, one transaction, ~8 min): 1,000,000 CKG vertices, 1,000,300 edges, the relational rows behind them and the `entity` / `relationship_edge` mirrors. Every row is `is_demo = true` with `source_ref.kind = synthetic_seed`. `-v scale=0.01` gives a 10k-node smoke seed |
| `cortex.js` | k6 scenarios: executive dashboard, opportunity list, neighbourhood (depth 2), path finder, rescore; thresholds = SLOs |
| `results/<utc>.json` | One file per run: p50/p95/p99/max and error rate per endpoint, graph size, memory-guard minimum |

## Run

```
make load            # ./make.ps1 load on Windows
```

`scripts/load_test.py` does everything, on compose profile `load`, so the live database and API are never touched:

1. starts `postgres-load` (its own server; volume `capital-cortex_pgload`, database `cortex_load`) and runs
   `alembic upgrade head` (`migrate-load`);
2. seeds once: skipped when the seed is present; `--reseed` rebuilds;
3. starts `api-load` on 127.0.0.1:`LOAD_API_PORT` (8384): same image and settings as `api`;
4. gets a real `dev-analyst` token, samples ids from the database and warms up;
5. runs `grafana/k6:2.3.0` on the compose network, prints p50/p95/p99 per endpoint and writes `results/`;
6. stops `api-load` and ends any queries still running server-side.

Options:
- `--scenarios dashboard,opportunities,neighbourhood,paths,rescore`
- `--mode serial --vus 1`: closed loop, for the per-request latency of slow endpoints
- `--rate-mult 3`: stress
- `--duration 5m`, `--timeout 120s`, `--scale 1`, `--keep-api`, `--seed-only`, `--dry-run-seed`, `--label`

Environment defaults are in `.env.example` (`LOAD_*`).

**Shared machine safety.** The load containers are capped (DB 2 GB / 6 CPU, API 1 GB / 2 CPU, no swap). The driver
aborts k6 and `api-load` when the Docker VM's `MemAvailable` falls below `LOAD_MIN_AVAILABLE_MB` (900). The AGE
path finder can use ~1 GB per database connection at this size (see `docs/LOAD_TEST.md` §4.3).

Clean up the load data (2.7 GB):
`docker compose -f infra/docker-compose.yml --profile load rm -sf postgres-load && docker volume rm capital-cortex_pgload`.
