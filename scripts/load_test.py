"""Load test driver (R3, §14; `make load`): 1M-node seed + k6 against a second API instance.

Everything runs on the compose profile `load`, so the live `cortex` database and API are never touched:

1. start `postgres-load` (its own server + volume), `alembic upgrade head` via `migrate-load`
2. seed tests/load/seed_1m.sql once (idempotent: skipped when the load seed is already there), VACUUM ANALYZE
3. start `api-load` (same image and settings as `api`, DATABASE_URL -> cortex_load; host port LOAD_API_PORT=8384)
4. get a real dev-analyst access token (scripts/devtoken.py), sample ids, warm up
5. run tests/load/cortex.js with the grafana/k6 image on the compose network; thresholds = the SLOs
6. print p50/p95/p99 per endpoint, write tests/load/results/<ts>.json, stop api-load (unless --keep-api)

Usage: python scripts/load_test.py [--scale 1] [--duration 5m] [--rate-mult 1] [--keep-api] [--seed-only]
       [--reseed]  (drops and recreates cortex_load first)   [--dry-run-seed] (seed in a rolled-back transaction)
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from ops_common import ROOT, compose_cmd, dump_json, log, out, run, setting

LOAD_PG = "capital-cortex-postgres-load-1"
NETWORK = "capital-cortex_default"
K6_IMAGE = "grafana/k6:2.3.0"
K6_NAME = "capital-cortex-k6"
# The Docker VM is shared with other projects: abort the run before the VM's OOM killer picks a victim.
MIN_AVAILABLE_MB = int(setting("LOAD_MIN_AVAILABLE_MB", "900"))
LOAD = [*compose_cmd(), "--profile", "load"]
SEED_SQL = ROOT / "tests" / "load" / "seed_1m.sql"
ENDPOINTS = ["dashboard_executive", "opportunities_list", "graph_neighbourhood", "graph_paths", "rescore"]
SLO_MS = {
    "dashboard_executive": 3000,
    "opportunities_list": 3000,
    "graph_neighbourhood": 5000,
    "graph_paths": 5000,
    "rescore": 10000,
}


def lpsql(sql: str, db: str = "cortex_load") -> str:
    return out(
        [
            "docker",
            "exec",
            "-i",
            LOAD_PG,
            "psql",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "cortex",
            "-d",
            db,
            "-Atq",
            "-c",
            sql,
        ]
    )


def ensure_db(reseed: bool) -> None:
    log("starting postgres-load")
    run([*LOAD, "up", "-d", "--no-deps", "--wait", "postgres-load"], capture=False)
    if reseed:
        log("--reseed: dropping and recreating cortex_load")
        lpsql("DROP DATABASE IF EXISTS cortex_load WITH (FORCE)", db="postgres")
        lpsql("CREATE DATABASE cortex_load", db="postgres")
    log("alembic upgrade head (cortex_load)")
    run([*LOAD, "run", "--rm", "--no-deps", "migrate-load"], capture=False)


def seed(scale: float, dry_run: bool) -> dict[str, Any]:
    present = int(lpsql("SELECT count(*) FROM source WHERE adapter_key = 'load_seed'") or 0)
    if present and not dry_run:
        log("load seed already present: skipping (use --reseed to rebuild)")
    else:
        sql = SEED_SQL.read_text(encoding="utf-8")
        if dry_run:
            sql = sql.replace("\nCOMMIT;", "\nROLLBACK;")
        log(f"seeding scale={scale} ({'dry run, rolled back' if dry_run else 'one transaction'})")
        t = time.monotonic()
        p = run(
            [
                "docker",
                "exec",
                "-i",
                LOAD_PG,
                "psql",
                "-X",
                "-U",
                "cortex",
                "-d",
                "cortex_load",
                "-v",
                f"scale={scale}",
                "-f",
                "-",
            ],
            input=sql.encode("utf-8"),
            timeout=7200,
        )
        log(f"seed finished in {time.monotonic() - t:.0f} s: {p.stdout.decode().strip().splitlines()[-4:]}")
        if dry_run:
            return {}
    never_vacuumed = lpsql("SELECT last_vacuum IS NULL FROM pg_stat_user_tables WHERE relname = 'opportunity'")
    if never_vacuumed == "t":
        t = time.monotonic()
        lpsql("VACUUM (ANALYZE)")
        log(f"VACUUM ANALYZE {time.monotonic() - t:.0f} s")
    return stats()


def stats() -> dict[str, Any]:
    rows = lpsql(
        "SELECT l.name, l.kind, (xpath('/row/c/text()', query_to_xml(format('SELECT count(*) AS c FROM ONLY ckg.%I', "
        "l.name), false, true, '')))[1]::text::bigint FROM ag_catalog.ag_label l JOIN ag_catalog.ag_graph g ON "
        "g.graphid = l.graph WHERE g.name = 'ckg' AND l.name NOT LIKE '\\_ag%' ORDER BY l.kind, l.name"
    )
    v, e = {}, {}
    for line in rows.splitlines():
        name, kind, n = line.split("|")
        if int(n):
            (v if kind == "v" else e)[name] = int(n)
    rel = lpsql(
        "SELECT json_build_object('organization', (SELECT count(*) FROM organization), 'opportunity', "
        "(SELECT count(*) FROM opportunity), 'signal', (SELECT count(*) FROM signal), 'contact', "
        "(SELECT count(*) FROM contact), 'relationship', (SELECT count(*) FROM relationship), 'entity', "
        "(SELECT count(*) FROM entity), 'relationship_edge', (SELECT count(*) FROM relationship_edge), "
        "'db_size', pg_size_pretty(pg_database_size('cortex_load')))"
    )
    return {
        "vertices": v,
        "vertices_total": sum(v.values()),
        "edges": e,
        "edges_total": sum(e.values()),
        "relational": json.loads(rel),
    }


def sample_ids() -> dict[str, Any]:
    q = lambda sql: [r.split("|") if "|" in r else r for r in lpsql(sql).splitlines()]  # noqa: E731
    opps = q("SELECT id FROM opportunity TABLESAMPLE SYSTEM (1) WHERE is_demo LIMIT 300")
    orgs = q("SELECT id FROM organization TABLESAMPLE SYSTEM (2) WHERE kind <> 'self' LIMIT 100")
    hubs = q("SELECT counterparty_id FROM opportunity GROUP BY 1 ORDER BY count(*) DESC LIMIT 20")
    self_org = lpsql("SELECT id FROM organization WHERE kind = 'self' LIMIT 1")
    connected = q(
        "SELECT a.ref_id, b.ref_id FROM relationship_edge i JOIN relationship_edge ka ON ka.from_entity = i.from_entity "
        "AND ka.type = 'KNOWS' JOIN relationship_edge kb ON kb.from_entity = i.to_entity AND kb.type = 'KNOWS' "
        "JOIN entity a ON a.id = ka.to_entity JOIN entity b ON b.id = kb.to_entity "
        "WHERE i.type = 'INTRODUCED' AND a.id <> b.id AND a.label <> 'Loadtest Self Organisation' "
        "AND b.label <> 'Loadtest Self Organisation' LIMIT 200"
    )
    warm = q(
        "SELECT o.ref_id FROM relationship_edge ks JOIN entity s ON s.id = ks.to_entity AND s.ref_table = 'organization' "
        "JOIN organization so ON so.id = s.ref_id AND so.kind = 'self' JOIN relationship_edge ko ON "
        "ko.from_entity = ks.from_entity AND ko.type = 'KNOWS' AND ko.to_entity <> ks.to_entity "
        "JOIN entity o ON o.id = ko.to_entity WHERE ks.type = 'KNOWS' LIMIT 100"
    )
    rnd = [[orgs[i], orgs[-1 - i]] for i in range(min(50, len(orgs) // 2))]
    paths = (
        [[a, b, "connected"] for a, b in connected] * 3
        + [[self_org, o, "warm_intro"] for o in warm]
        + [[a, b, "random"] for a, b in rnd]
    )
    # neighbourhood: opportunities, ordinary organisations and a few hub organisations (~40 opportunities each)
    neighbourhood = opps[:150] + orgs[:80] + hubs
    return {
        "opportunities": opps,
        "neighbourhood": neighbourhood,
        "paths": paths,
        "mix": {
            "paths_connected": len(connected) * 3,
            "paths_warm": len(warm),
            "paths_random": len(rnd),
            "neighbourhood_hubs": len(hubs),
        },
    }


def get_token() -> str:
    sys.path.insert(0, str(ROOT / "scripts"))
    sys.path.insert(0, str(ROOT / "infra" / "keycloak"))
    from devtoken import token

    user = setting("LOAD_TEST_USER", "dev-analyst")
    pw = setting("LOAD_TEST_PASSWORD", "")
    if not pw:
        from generate_realm import DEV_PASSWORD

        pw = DEV_PASSWORD
    return token(user, pw)


def warmup(tok: str, ids: dict[str, Any]) -> None:
    import httpx

    base = f"http://localhost:{setting('LOAD_API_PORT', '8384')}"
    h = {"Authorization": f"Bearer {tok}"}
    with httpx.Client(timeout=300, headers=h) as c:
        # first rescore creates the active scoring profile (avoid a first-request race under load)
        # (graph endpoints are not warmed: at 1M nodes they can run for minutes; k6 measures them cold/warm)
        for path, method in (
            (f"/v1/opportunities/{ids['opportunities'][0]}/rescore", "POST"),
            ("/v1/opportunities?limit=50", "GET"),
        ):
            t = time.monotonic()
            r = c.request(method, base + path)
            log(f"warmup {method} {path.split('?')[0]} -> {r.status_code} in {time.monotonic() - t:.2f} s")
            if r.status_code >= 400:
                raise SystemExit(f"warmup failed: {r.status_code} {r.text[:500]}")


class MemoryGuard(threading.Thread):
    """Polls the VM's MemAvailable (containers see the VM's /proc/meminfo) and kills k6 + api-load when low."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.stop = threading.Event()
        self.tripped: str | None = None
        self.min_seen: int | None = None

    def run(self) -> None:
        while not self.stop.wait(5):
            p = run(["docker", "exec", LOAD_PG, "grep", "MemAvailable", "/proc/meminfo"], check=False)
            try:
                mb = int(p.stdout.split()[1]) // 1024
            except (IndexError, ValueError):
                continue
            self.min_seen = mb if self.min_seen is None else min(self.min_seen, mb)
            if mb < MIN_AVAILABLE_MB:
                self.tripped = f"VM MemAvailable {mb} MB < {MIN_AVAILABLE_MB} MB: run aborted"
                log(self.tripped)
                run(["docker", "rm", "-f", K6_NAME], check=False)
                run([*LOAD, "stop", "-t", "2", "api-load"], check=False)
                return


def run_k6(tok: str, ids: dict[str, Any], args: argparse.Namespace) -> tuple[int, dict[str, Any]]:
    with tempfile.TemporaryDirectory(prefix="cortex-k6-") as d:
        tmp = Path(d)
        (tmp / "data").mkdir()
        (tmp / "out").mkdir()
        (tmp / "data" / "ids.json").write_text(json.dumps(ids), encoding="utf-8")
        log(
            f"k6 {K6_IMAGE}: scenarios {args.scenarios or 'all'}, mode {args.mode}, duration {args.duration}, "
            f"rate x{args.rate_mult}, vus {args.vus}, timeout {args.timeout}"
        )
        guard = MemoryGuard()
        guard.start()
        p = run(
            [
                "docker",
                "run",
                "--rm",
                "--name",
                K6_NAME,
                "--network",
                NETWORK,
                "-e",
                f"TOKEN={tok}",
                "-e",
                "BASE_URL=http://api-load:8000",
                "-e",
                f"DURATION={args.duration}",
                "-e",
                f"RATE_MULT={args.rate_mult}",
                "-e",
                f"SCENARIOS={args.scenarios}",
                "-e",
                f"MODE={args.mode}",
                "-e",
                f"VUS={args.vus}",
                "-e",
                f"TIMEOUT={args.timeout}",
                "-v",
                f"{ROOT / 'tests' / 'load'}:/scripts:ro",
                "-v",
                f"{tmp / 'data'}:/data:ro",
                "-v",
                f"{tmp / 'out'}:/out",
                K6_IMAGE,
                "run",
                "--quiet",
                "/scripts/cortex.js",
            ],
            check=False,
            capture=False,
            timeout=3600,
        )
        guard.stop.set()
        f = tmp / "out" / "summary.json"
        summary = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"metrics": {}}
        summary["guard"] = {"tripped": guard.tripped, "min_available_mb": guard.min_seen}
    return p.returncode, summary


def results(summary: dict[str, Any]) -> dict[str, Any]:
    m = summary["metrics"]
    res: dict[str, Any] = {}
    for key, metric in m.items():
        if not key.startswith("http_req_duration{"):
            continue
        tag = key[len("http_req_duration{") : -1]
        if not tag.startswith("endpoint:"):
            continue
        vals = metric.get("values", metric)
        name = tag.replace("endpoint:", "").replace(",kind:", ":")
        fail_key = f"http_req_failed{{{tag}}}"
        failed = m.get(fail_key, {}).get("values", m.get(fail_key, {})).get("rate") if fail_key in m else None
        slo = SLO_MS.get(name.split(":")[0])
        res[name] = {
            "count": vals.get("count"),
            "p50_ms": round(vals.get("med", 0)),
            "p95_ms": round(vals.get("p(95)", 0)),
            "p99_ms": round(vals.get("p(99)", 0)),
            "max_ms": round(vals.get("max", 0)),
            "error_rate": failed,
            "slo_p95_ms": slo,
            "pass": vals.get("p(95)", 1e12) < slo if slo else None,
        }
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scale", type=float, default=float(setting("LOAD_SCALE", "1")))
    ap.add_argument("--duration", default=setting("LOAD_DURATION", "5m"))
    ap.add_argument("--rate-mult", type=float, default=float(setting("LOAD_RATE_MULT", "1")))
    ap.add_argument(
        "--scenarios",
        default=setting("LOAD_SCENARIOS", ""),
        help="comma list of dashboard,opportunities,neighbourhood,paths,rescore (default all)",
    )
    ap.add_argument("--mode", choices=["rate", "serial"], default="rate")
    ap.add_argument("--vus", type=int, default=1, help="closed-loop users per scenario in --mode serial")
    ap.add_argument("--timeout", default="120s", help="k6 client timeout per request")
    ap.add_argument("--keep-api", action="store_true")
    ap.add_argument("--seed-only", action="store_true")
    ap.add_argument("--reseed", action="store_true")
    ap.add_argument("--dry-run-seed", action="store_true")
    ap.add_argument("--label", default="", help="free text stored with the results (e.g. 'before indexes')")
    args = ap.parse_args()

    ensure_db(args.reseed)
    st = seed(args.scale, args.dry_run_seed)
    if args.dry_run_seed or args.seed_only:
        log(dump_json(st))
        return 0
    log(f"graph: {st['vertices_total']:,} vertices, {st['edges_total']:,} edges")
    log("starting api-load")
    run([*LOAD, "up", "-d", "--no-deps", "--wait", "api-load"], capture=False)
    try:
        ids = sample_ids()
        log(f"sampled ids: {ids['mix']}")
        tok = get_token()
        warmup(tok, ids)
        rc, summary = run_k6(tok, ids, args)
    finally:
        if not args.keep_api:
            log("stopping api-load")
            run([*LOAD, "stop", "api-load"], check=False)
            # queries whose client timed out keep running server-side: end them so they don't linger
            lpsql(
                "SELECT count(pg_terminate_backend(pid)) FROM pg_stat_activity WHERE datname = 'cortex_load' "
                "AND pid <> pg_backend_pid() AND backend_type = 'client backend'"
            )
    res = results(summary)
    report = {
        "at": datetime.now(UTC).isoformat(),
        "label": args.label,
        "duration": args.duration,
        "memory_guard": summary.get("guard"),
        "rate_mult": args.rate_mult,
        "scenarios": args.scenarios or "all",
        "mode": args.mode,
        "vus": args.vus,
        "timeout": args.timeout,
        "k6_exit": rc,
        "graph": st,
        "endpoints": res,
        "sampled": ids["mix"],
        "hardware": {
            "docker_cpus": out(["docker", "info", "--format", "{{.NCPU}}"]),
            "docker_mem_bytes": out(["docker", "info", "--format", "{{.MemTotal}}"]),
        },
    }
    rdir = ROOT / "tests" / "load" / "results"
    rdir.mkdir(exist_ok=True)
    f = rdir / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
    f.write_text(dump_json(report), encoding="utf-8")
    print(f"\n{'endpoint':32} {'n':>6} {'p50':>8} {'p95':>8} {'p99':>8} {'max':>8} {'err':>6}  SLO p95")
    for name, r in res.items():
        err = f"{r['error_rate'] * 100:.1f}%" if r["error_rate"] is not None else "-"
        verdict = ("PASS" if r["pass"] else "FAIL") if r["pass"] is not None else ""
        print(
            f"{name:32} {r['count'] or 0:>6} {r['p50_ms']:>7}ms {r['p95_ms']:>7}ms {r['p99_ms']:>7}ms "
            f"{r['max_ms']:>7}ms {err:>6}  <{r['slo_p95_ms']}ms {verdict}"
        )
    g = summary.get("guard") or {}
    print(
        f"memory guard: min VM MemAvailable {g.get('min_available_mb')} MB"
        + (f"; {g['tripped']}" if g.get("tripped") else "")
    )
    print(f"k6 exit {rc} ({'thresholds met' if rc == 0 else 'thresholds FAILED'}); results {f.relative_to(ROOT)}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
