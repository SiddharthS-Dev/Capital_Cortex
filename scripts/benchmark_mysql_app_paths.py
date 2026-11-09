"""Application-path benchmark for Capital Cortex on MySQL 8.4 (reproducible).

Measures the application's own code paths, not hand-written SQL:
  1. In-process: vector index build (cold) and search (warm) via search_opportunity_embeddings, graph
     neighbourhood/paths via cortex.l2_representation.graph_traversal, audit chain verification via verify_chain.
  2. HTTP under concurrency against a running API with a real OIDC token: opportunity list/search/detail,
     graph query/paths, audit list, copilot retrieval (lexical + vector), and a write (POST /v1/contacts).
  3. Resources: MySQL container CPU/memory (docker stats), API process memory, this process's peak memory.

Seed first:  python scripts/seed_mysql_load.py --scale 1.0 --db cortex_bench_1m
API:         uvicorn pointed at the same database (DEMO_MODE=true: the load rows are is_demo)
Run:         python scripts/benchmark_mysql_app_paths.py --db cortex_bench_1m --api http://127.0.0.1:8310 --api-pid <pid>
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import ctypes
import hashlib
import json
import os
import platform
import random
import re
import secrets
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

import httpx
import numpy as np
import pymysql
import smoke

ORG_ID = "00000000-0000-0000-0000-000000000001"


# ------------------------------------------------------------------------------------------------ resources
class _PMC(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_ulong),
        ("PageFaultCount", ctypes.c_ulong),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def process_memory_mib(pid: int | None = None) -> dict[str, float] | None:
    """Working set and peak working set (Windows only; None elsewhere)."""
    if platform.system() != "Windows":
        return None
    k32, psapi = ctypes.windll.kernel32, ctypes.windll.psapi
    # 64-bit HANDLEs: without explicit types ctypes truncates them to int and every call fails.
    k32.GetCurrentProcess.restype = ctypes.c_void_p
    k32.OpenProcess.restype = ctypes.c_void_p
    k32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_bool, ctypes.c_ulong]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PMC), ctypes.c_ulong]
    handle = k32.GetCurrentProcess() if pid is None else k32.OpenProcess(0x1000 | 0x0010, False, _interpreter_pid(pid))
    if not handle:
        return None
    c = _PMC()
    c.cb = ctypes.sizeof(c)
    ok = psapi.GetProcessMemoryInfo(handle, ctypes.byref(c), c.cb)
    if pid is not None:
        k32.CloseHandle(handle)
    return (
        {"working_set_mib": c.WorkingSetSize / 2**20, "peak_working_set_mib": c.PeakWorkingSetSize / 2**20}
        if ok
        else None
    )


def _interpreter_pid(pid: int) -> int:
    """A venv's python.exe on Windows is a launcher that runs the real interpreter as a child process;
    measure that child (the uvicorn server), not the few-MB launcher."""
    out = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            f"(Get-CimInstance Win32_Process -Filter 'ParentProcessId={int(pid)}' | Where-Object Name -eq 'python.exe' | Select-Object -First 1).ProcessId",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()
    return int(out) if out.isdigit() else pid


class DockerSampler(threading.Thread):
    """Samples CPU% and memory of a container every ~2 s while running."""

    def __init__(self, container: str) -> None:
        super().__init__(daemon=True)
        self.container, self.samples, self._halt = container, [], threading.Event()

    def run(self) -> None:
        while not self._halt.is_set():
            out = subprocess.run(
                ["docker", "stats", "--no-stream", "--format", "{{.CPUPerc}}|{{.MemUsage}}", self.container],
                capture_output=True,
                text=True,
                timeout=30,
            ).stdout.strip()
            if "|" in out:
                cpu, mem = out.split("|", 1)
                self.samples.append({"cpu_pct": float(cpu.rstrip("%") or 0), "mem": mem.split("/")[0].strip()})
            self._halt.wait(2)

    def finish(self) -> dict[str, Any]:
        self._halt.set()
        self.join(timeout=35)
        cpus = [s["cpu_pct"] for s in self.samples]
        return {
            "samples": len(cpus),
            "cpu_pct_avg": round(float(np.mean(cpus)), 1) if cpus else None,
            "cpu_pct_max": round(max(cpus), 1) if cpus else None,
            "mem_last": self.samples[-1]["mem"] if self.samples else None,
        }


def pct(values: list[float]) -> dict[str, float]:
    a = np.asarray(values)
    return (
        {
            "n": len(values),
            "p50_ms": round(float(np.percentile(a, 50)), 2),
            "p95_ms": round(float(np.percentile(a, 95)), 2),
            "p99_ms": round(float(np.percentile(a, 99)), 2),
            "max_ms": round(float(a.max()), 2),
        }
        if values
        else {"n": 0}
    )


# ------------------------------------------------------------------------------------------------ auth
def login(kc: str, user: str, password: str) -> str:
    redirect = "http://localhost:5373/auth/callback"
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    with httpx.Client(follow_redirects=False, timeout=20) as c:

        def _insecure_cookies(resp: httpx.Response) -> None:  # as scripts/smoke.py (dev-only, http://localhost)
            resp.read()
            for ck in c.cookies.jar:
                ck.secure = False

        c.event_hooks["response"] = [_insecure_cookies]
        r = c.get(
            f"{kc}/realms/cortex/protocol/openid-connect/auth",
            params={
                "client_id": "cortex-web",
                "redirect_uri": redirect,
                "response_type": "code",
                "scope": "openid",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": secrets.token_hex(8),
            },
        )
        while r.status_code in (302, 303) and redirect not in r.headers.get("location", ""):
            r = c.get(r.headers["location"])
        r = c.post(smoke.form_action(r.text), data={"username": user, "password": password, "credentialId": ""})
        code = urllib.parse.parse_qs(urllib.parse.urlparse(r.headers.get("location", "")).query)["code"][0]
        t = c.post(
            f"{kc}/realms/cortex/protocol/openid-connect/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect,
                "client_id": "cortex-web",
                "code_verifier": verifier,
            },
        )
        t.raise_for_status()
        return t.json()["access_token"]


# ------------------------------------------------------------------------------------------------ phases
def sample_ids(cfg: dict[str, Any]) -> dict[str, Any]:
    c = pymysql.connect(**cfg)
    with c.cursor() as cur:

        def col(sql: str) -> list[str]:
            cur.execute(sql)
            return [str(r[0]) for r in cur.fetchall()]

        counts = {}
        for t in ("organization", "opportunity", "embedding", "entity", "relationship_edge", "audit_log", "contact"):
            cur.execute(f"SELECT COUNT(*) FROM `{t}`")
            counts[t] = cur.fetchone()[0]
        rnd = random.Random(42)  # noqa: S311 - reproducible sampling, not cryptography
        opps = col("SELECT id FROM opportunity ORDER BY id LIMIT 5000")
        org_ents = col(
            "SELECT from_entity FROM relationship_edge GROUP BY from_entity HAVING COUNT(*) > 1 ORDER BY from_entity LIMIT 2000"
        )
        cur.execute(
            "SELECT a.to_entity, b.to_entity FROM relationship_edge a JOIN relationship_edge b "
            "ON a.from_entity = b.from_entity AND a.to_entity < b.to_entity LIMIT 2000"
        )
        pairs = [(str(x), str(y)) for x, y in cur.fetchall()]
        orgs = col("SELECT id FROM organization WHERE kind <> 'self' ORDER BY id LIMIT 2000")
        cur.execute(
            "SELECT COALESCE(SUM(data_length + index_length), 0) FROM information_schema.TABLES WHERE table_schema = DATABASE()"
        )
        size = int(cur.fetchone()[0])
    return {
        "counts": counts,
        "db_size_mib": round(size / 2**20, 1),
        "opps": rnd.sample(opps, min(500, len(opps))),
        "org_entities": org_ents,
        "pairs": pairs,
        "orgs": orgs,
    }


async def inprocess(db_url: str, ids: dict[str, Any], queries: int) -> dict[str, Any]:
    os.environ["DATABASE_URL"] = db_url
    from sqlalchemy.ext.asyncio import AsyncSession

    from cortex.l2_representation import graph_traversal
    from platform_core import embeddings
    from platform_core.audit.chain import verify_chain
    from platform_core.db.session import create_engine_from_url
    from platform_core.db.vector import invalidate_vector_cache, search_opportunity_embeddings

    eng = create_engine_from_url(db_url)
    out: dict[str, Any] = {}
    mem0 = process_memory_mib()
    texts = [
        "grant opportunity targeting climate energy",
        "venture equity opportunity in fintech region",
        "debt facility for healthcare",
        "university program synthetic opportunity",
    ]
    async with AsyncSession(eng) as s:
        invalidate_vector_cache()
        t = time.perf_counter()
        hits = await search_opportunity_embeddings(s, ORG_ID, embeddings.embed(texts[0]), include_demo=True, limit=5)
        out["vector_index_cold_build_s"] = round(time.perf_counter() - t, 2)
        out["vector_cold_hits"] = len(hits)
        mem1 = process_memory_mib()
        lat = []
        for i in range(queries):
            q = embeddings.embed(texts[i % len(texts)] + f" {i}")
            t = time.perf_counter()
            await search_opportunity_embeddings(s, ORG_ID, q, include_demo=True, limit=5)
            lat.append((time.perf_counter() - t) * 1000)
        out["vector_search_warm"] = pct(lat)
        if mem0 and mem1:
            out["vector_index_memory_mib"] = {
                "before": round(mem0["working_set_mib"]),
                "after_build": round(mem1["working_set_mib"]),
                "process_peak": round(mem1["peak_working_set_mib"]),
            }

        lat = []
        for node in ids["org_entities"][:queries]:
            t = time.perf_counter()
            await graph_traversal.neighbourhood(s, node, 2, 200)
            lat.append((time.perf_counter() - t) * 1000)
        out["graph_neighbourhood_depth2"] = pct(lat)
        lat = []
        for a, b in ids["pairs"][:queries]:
            t = time.perf_counter()
            await graph_traversal.paths(s, a, b, 3, 5)
            lat.append((time.perf_counter() - t) * 1000)
        out["graph_paths_max3"] = pct(lat)

        t = time.perf_counter()
        res = await verify_chain(s)
        out["audit_verify_chain"] = {"seconds": round(time.perf_counter() - t, 2), "ok": res.ok, "checked": res.checked}
    await eng.dispose()
    return out


async def http_load(api: str, token: str, ids: dict[str, Any], duration: float, concurrency: int) -> dict[str, Any]:
    rnd = random.Random(7)  # noqa: S311 - reproducible request mix, not cryptography
    lat: dict[str, list[float]] = {}
    status: dict[str, dict[str, int]] = {}

    def endpoints() -> list[tuple[str, str, str, dict | None]]:
        a, b = rnd.choice(ids["pairs"])
        return [
            ("GET opportunities (score, facets)", "GET", "/v1/opportunities?limit=25&sort=score&facets=true", None),
            (
                "GET opportunities search q=",
                "GET",
                f"/v1/opportunities?limit=25&q=Opportunity%20{rnd.randint(1, 199999)}",
                None,
            ),
            ("GET opportunity detail", "GET", f"/v1/opportunities/{rnd.choice(ids['opps'])}", None),
            (
                "GET graph neighbourhood d2",
                "GET",
                f"/v1/graph/query?template=neighbourhood&id={rnd.choice(ids['org_entities'])}&depth=2&limit=100",
                None,
            ),
            ("GET graph paths", "GET", f"/v1/graph/paths?from={a}&to={b}&max_hops=3&limit=5", None),
            ("GET audit list", "GET", "/v1/audit?limit=50", None),
            (
                "POST contact (write)",
                "POST",
                "/v1/contacts",
                {
                    "name": f"Bench Contact {rnd.randint(1, 10**9)}",
                    "organization_id": rnd.choice(ids["orgs"]),
                    "role": "benchmark",
                    "emails": [],
                    "consent_basis": "manual_entry",
                },
            ),
        ]

    async with httpx.AsyncClient(base_url=api, headers={"Authorization": f"Bearer {token}"}, timeout=120) as client:
        # Copilot retrieval: first call builds the API's in-memory vector index (cold); then warm calls.
        async def copilot(question: str) -> tuple[float, int]:
            t = time.perf_counter()
            async with client.stream("POST", "/v1/copilot/ask", json={"question": question, "include_demo": True}) as r:
                ev = None
                async for line in r.aiter_lines():
                    if line.startswith("event:"):
                        ev = line.split(":", 1)[1].strip()
                    elif line.startswith("data:") and ev == "retrieval":
                        break  # stop before any LLM call
            return (time.perf_counter() - t) * 1000, r.status_code

        cold_ms, cold_status = await copilot("storage operators needing lease and asset finance")
        warm = [await copilot(f"energy storage lease finance operators {i}") for i in range(10)]
        lat["POST copilot retrieval (warm)"] = [m for m, _ in warm]
        status["POST copilot retrieval (warm)"] = {str(code): sum(1 for _, x in warm if x == code) for _, code in warm}

        stop_at = time.perf_counter() + duration
        errors: list[str] = []

        async def worker() -> None:
            while time.perf_counter() < stop_at:
                name, method, path, body = rnd.choice(endpoints())
                t = time.perf_counter()
                try:
                    code = (await client.request(method, path, json=body)).status_code
                except Exception as exc:  # counted, never hidden
                    code = 0
                    errors.append(f"{name}: {type(exc).__name__}")
                lat.setdefault(name, []).append((time.perf_counter() - t) * 1000)
                status.setdefault(name, {}).setdefault(str(code), 0)
                status[name][str(code)] += 1

        t0 = time.perf_counter()
        await asyncio.gather(*(worker() for _ in range(concurrency)))
        wall = time.perf_counter() - t0

    per = {}
    for name, v in lat.items():
        s = status.get(name, {})
        per[name] = {
            **pct(v),
            "status": s,
            "errors_5xx_or_conn": sum(n for c, n in s.items() if c == "0" or c.startswith("5")),
        }
    total = sum(len(v) for k, v in lat.items() if "copilot" not in k)
    return {
        "copilot_cold_first_call_ms": round(cold_ms, 1),
        "copilot_cold_status": cold_status,
        "duration_s": round(wall, 1),
        "concurrency": concurrency,
        "requests": total,
        "throughput_rps": round(total / wall, 1),
        "endpoints": per,
        "client_errors": errors[:20],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default="cortex_bench_1m")
    ap.add_argument("--api", default="http://127.0.0.1:8310")
    ap.add_argument("--api-pid", type=int, default=None)
    ap.add_argument("--keycloak", default="http://localhost:8380")
    ap.add_argument("--user", default="dev-analyst")
    ap.add_argument("--duration", type=float, default=60.0)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--queries", type=int, default=100)
    ap.add_argument("--container", default="capital-cortex-mysql-test")
    ap.add_argument("--out", default="benchmark_app_paths.json")
    a = ap.parse_args()

    port = int(os.environ.get("MYSQL_TEST_PORT", 53306))
    user, pw = os.environ.get("MYSQL_TEST_USER", "cortex"), os.environ["MYSQL_TEST_PASSWORD"]
    cfg = {"host": "127.0.0.1", "port": port, "user": user, "password": pw, "database": a.db}
    db_url = f"mysql+asyncmy://{user}:{urllib.parse.quote(pw)}@127.0.0.1:{port}/{a.db}"
    if re.search("prod", a.db, re.I) or port == 3306:
        raise SystemExit("refusing to benchmark a production-looking target")

    started = time.time()
    ids = sample_ids(cfg)
    print(f"dataset: {ids['counts']}  size={ids['db_size_mib']} MiB")
    sampler = DockerSampler(a.container)
    sampler.start()
    result: dict[str, Any] = {
        "env": {
            "db": a.db,
            "dataset_rows": ids["counts"],
            "dataset_rows_total": sum(ids["counts"].values()),
            "db_size_mib": ids["db_size_mib"],
            "python": platform.python_version(),
            "host": platform.platform(),
        }
    }
    result["inprocess"] = asyncio.run(inprocess(db_url, ids, a.queries))
    print("in-process:", json.dumps(result["inprocess"], indent=1))
    token = login(a.keycloak, a.user, os.environ.get("CORTEX_BENCH_PASSWORD") or smoke.setting("SMOKE_USER_PASSWORD"))
    result["http"] = asyncio.run(http_load(a.api, token, ids, a.duration, a.concurrency))
    result["resources"] = {
        "mysql_container": sampler.finish(),
        "api_process": process_memory_mib(a.api_pid) if a.api_pid else None,
        "benchmark_process": process_memory_mib(),
    }
    result["total_seconds"] = round(time.time() - started, 1)
    Path(a.out).write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")

    print(
        f"\nHTTP: {result['http']['requests']} requests in {result['http']['duration_s']} s, "
        f"concurrency {a.concurrency}, {result['http']['throughput_rps']} req/s"
    )
    print(f"{'endpoint':38} {'n':>6} {'p50':>8} {'p95':>8} {'p99':>8} {'5xx':>5}")
    for name, v in result["http"]["endpoints"].items():
        print(
            f"{name:38} {v['n']:>6} {v.get('p50_ms', 0):>8} {v.get('p95_ms', 0):>8} {v.get('p99_ms', 0):>8} {v['errors_5xx_or_conn']:>5}"
        )
    print("resources:", json.dumps(result["resources"]))


if __name__ == "__main__":
    main()
