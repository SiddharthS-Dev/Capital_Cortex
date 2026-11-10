"""Profile GET /v1/dashboards/executive step by step (PERF-2) and save its payload for before/after parity.

Read-only: every query the executive dashboard runs is a SELECT. Runs against the MySQL database named by
--database (default: cortex_demo, the demo data set); credentials come from the environment/.env exactly as for the
test suite. Only timings are printed.

    python scripts/profile_dashboard.py --runs 7 --payload out.json

Each step is timed on its own fresh session (warm-up run discarded), then the whole endpoint function is timed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _load_env() -> None:
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep and key.startswith("MYSQL_TEST_") and key != "MYSQL_TEST_DATABASE":
            os.environ.setdefault(key, value.strip().strip('"'))


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--database", default="cortex_demo")
    ap.add_argument("--runs", type=int, default=7)
    ap.add_argument("--payload", help="write the executive payload (generated_at removed) to this JSON file")
    args = ap.parse_args()
    _load_env()
    os.environ["MYSQL_TEST_DATABASE"] = args.database

    from sqlalchemy.ext.asyncio import AsyncSession

    from cortex.l5_strategy.forecasting import forecast, load_snapshots, preset
    from cortex.l5_strategy.pipeline_engine import grouped_inflows, weighted_pipeline
    from cortex.l8_actuation.api.routers import dashboards as d
    from platform_core.db.session import create_engine_from_url, get_mysql_test_url, reset_engine

    engine = create_engine_from_url(get_mysql_test_url(driver="asyncmy"), pool_size=2, max_overflow=0)
    reset_engine(engine)
    demo = True
    stage, cls = "pipeline_stage", "coalesce(class, 'unclassified')"

    async def runway_inputs(s):
        _snaps, ccy = await load_snapshots(s, demo)
        return await grouped_inflows(s, ccy, demo) if ccy else []

    async def forecast_only(s):  # the 3-scenario computation itself, after its data is loaded
        snaps, ccy = await load_snapshots(s, demo)
        inflows = await grouped_inflows(s, ccy, demo) if ccy else []
        t = time.perf_counter()
        await asyncio.to_thread(lambda: [forecast(snaps, inflows, preset(n)) for n in ("base", "downside", "upside")])
        return time.perf_counter() - t

    steps = {
        "runway (snapshots + inflows + 3 forecasts)": lambda s: d._runway(s, demo),
        "  runway data load only": runway_inputs,
        "weighted_pipeline": lambda s: weighted_pipeline(s, demo),
        "count active": lambda s: d._counts(s, "'all'", demo),
        "funnel (_counts stage)": lambda s: d._counts(s, stage, demo),
        "class_mix (_counts class)": lambda s: d._counts(s, cls, demo),
        "band_mix (_counts band)": lambda s: d._counts(s, "coalesce(score_band, 'unscored')", demo),
        "geo (JSON_TABLE)": lambda s: d._geo(s, demo),
        "grants": lambda s: d._grants(s, demo),
        "top": lambda s: d._top(s, demo),
    }
    results: dict[str, list[float]] = {k: [] for k in steps}
    results["serialisation (json.dumps)"] = []
    forecast_cpu: list[float] = []
    total: list[float] = []
    payload = None
    try:
        for i in range(args.runs + 1):  # run 0 is the warm-up
            for name, fn in steps.items():
                async with engine.connect() as conn:
                    s = AsyncSession(bind=conn)
                    t = time.perf_counter()
                    await fn(s)
                    if i:
                        results[name].append(time.perf_counter() - t)
                    await s.close()
            async with engine.connect() as conn:
                s = AsyncSession(bind=conn)
                cpu = await forecast_only(s)
                if i:
                    forecast_cpu.append(cpu)
                await s.close()
            async with engine.connect() as conn:
                s = AsyncSession(bind=conn)
                t = time.perf_counter()
                payload = await d.dashboard(name="executive", include_demo=demo, _=None, session=s)
                if i:
                    total.append(time.perf_counter() - t)
                await s.close()
            t = time.perf_counter()
            json.dumps(payload, default=str)
            if i:
                results["serialisation (json.dumps)"].append(time.perf_counter() - t)
    finally:
        reset_engine(None)
        await engine.dispose()

    def ms(xs: list[float]) -> str:
        return f"{statistics.median(xs) * 1000:8.1f} ms (min {min(xs) * 1000:.1f}, max {max(xs) * 1000:.1f})"

    print(f"database={args.database} runs={args.runs} (median of warm runs)")
    for name, xs in results.items():
        print(f"  {name:<45} {ms(xs)}")
    print(f"  {'  forecast computation only (3 scenarios)':<45} {ms(forecast_cpu)}")
    print(f"  {'WHOLE executive endpoint function':<45} {ms(total)}")
    if args.payload and payload is not None:
        payload = dict(payload)
        payload.pop("generated_at", None)
        Path(args.payload).write_text(  # noqa: ASYNC240 - one write after all timing is done
            json.dumps(payload, default=str, sort_keys=True, indent=1), encoding="utf-8"
        )
        print(f"payload written to {args.payload}")


if __name__ == "__main__":
    asyncio.run(main())
