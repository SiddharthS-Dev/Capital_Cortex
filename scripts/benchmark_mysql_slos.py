"""MySQL 8.4 SLO Latency Benchmark Harness (Phase 11).

Directly measures end-to-end SQL query execution latencies on MySQL 8.4 for:
- Executive Dashboard (target: p95 <= 3.0s)
- Opportunities Search & Faceting (target: p95 <= 1.0s)
- Graph Recursive CTE Traversal (target: p95 <= 5.0s)
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import numpy as np
import pymysql

from scripts.seed_mysql_load import MySQLLoadGenerator

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
log = logging.getLogger("mysql_benchmark")

ORG_ID = "00000000-0000-0000-0000-000000000001"
SCHEMA_FILE = ROOT / "scripts" / "schema_mysql.sql"


def run_benchmark(db_config: dict[str, Any], runs: int = 50) -> dict[str, Any]:
    target_db = db_config.get("database", "cortex_integration")
    conn = pymysql.connect(**db_config)

    # Seed benchmark data
    log.info("Seeding benchmark data at scale 0.02 into %s...", target_db)
    gen = MySQLLoadGenerator(db_config, scale=0.02, batch_size=2000)
    gen.run()

    # SQL for Executive Dashboard
    dashboard_sql = """
        SELECT class, status, pipeline_stage, score_band,
               COUNT(*) AS total_count,
               AVG(score) AS avg_score,
               SUM(COALESCE(amount_max, amount_min, 0)) AS total_volume
        FROM opportunity
        WHERE org_id = %s
        GROUP BY class, status, pipeline_stage, score_band
    """

    # SQL for Opportunities list & faceted search
    opps_sql = """
        SELECT o.id, o.title, o.class, o.status, o.pipeline_stage, o.score, o.score_band,
               cp.name AS counterparty_name, cp.country
        FROM opportunity o
        JOIN organization cp ON cp.id = o.counterparty_id
        WHERE o.org_id = %s AND o.status IN ('active', 'watchlist')
        ORDER BY (o.score IS NULL), o.score DESC
        LIMIT 50
    """

    # SQL for Graph Recursive CTE Traversal
    graph_sql = """
        WITH RECURSIVE traversal AS (
            SELECT re.from_entity, re.to_entity, re.type, 1 AS depth
            FROM relationship_edge re
            WHERE re.org_id = %s AND re.from_entity = (
                SELECT id FROM entity WHERE org_id = %s LIMIT 1
            )
            UNION ALL
            SELECT e.from_entity, e.to_entity, e.type, t.depth + 1
            FROM relationship_edge e
            JOIN traversal t ON e.from_entity = t.to_entity
            WHERE t.depth < 3
        )
        SELECT * FROM traversal LIMIT 100
    """

    queries = {
        "Executive Dashboard": (dashboard_sql, (ORG_ID,)),
        "Opportunities Search & List": (opps_sql, (ORG_ID,)),
        "Graph Traversal (Recursive CTE)": (graph_sql, (ORG_ID, ORG_ID)),
    }

    results: dict[str, Any] = {}

    for name, (sql, params) in queries.items():
        log.info("Benchmarking query: %s (warm-up 5, runs %d)...", name, runs)
        # Warm-up
        with conn.cursor() as cur:
            for _ in range(5):
                cur.execute(sql, params)
                cur.fetchall()

        times = []
        with conn.cursor() as cur:
            for _ in range(runs):
                t_start = time.perf_counter()
                cur.execute(sql, params)
                cur.fetchall()
                t_end = time.perf_counter()
                times.append((t_end - t_start) * 1000.0)  # ms

        p50 = float(np.percentile(times, 50))
        p95 = float(np.percentile(times, 95))
        p99 = float(np.percentile(times, 99))

        results[name] = {
            "p50_ms": round(p50, 2),
            "p95_ms": round(p95, 2),
            "p99_ms": round(p99, 2),
            "min_ms": round(min(times), 2),
            "max_ms": round(max(times), 2),
            "runs": runs,
        }
        log.info("%s: p50=%.2fms, p95=%.2fms, p99=%.2fms", name, p50, p95, p99)

    conn.close()
    return results


if __name__ == "__main__":
    cfg = {
        "host": os.environ.get("MYSQL_TEST_HOST", "127.0.0.1"),
        "port": int(os.environ.get("MYSQL_TEST_PORT", 53306)),
        "database": os.environ.get("MYSQL_TEST_DATABASE", "cortex_integration"),
        "user": os.environ.get("MYSQL_TEST_USER", "cortex"),
        "password": os.environ["MYSQL_TEST_PASSWORD"],
    }
    bench_results = run_benchmark(cfg, runs=50)
    print(json.dumps(bench_results, indent=2))
