"""PERF-1 decision evidence: compare the current opportunity search with two candidate semantics, on the benchmark data.

Nothing in the application changes. The benchmark database (default cortex_bench_1m) is only read. The candidates are
built in a separate scratch database, cortex_perf1_proto, so no drift-checked schema is altered:

  current   MATCH(title, description) NATURAL LANGUAGE  OR  title LIKE %q%  OR  counterparty name LIKE %q%
  A         FULLTEXT only (the current MATCH, without the two LIKE scans)
  C         n-gram FULLTEXT (WITH PARSER ngram) on title and counterparty name, BOOLEAN MODE phrase,
            OR the current word FULLTEXT on title/description: keeps substring-style matching through an index

For each query: median time of the full result-id set, result count, and recall/precision of A and C measured
against the current result set (current = reference behaviour). Connects as root to the LOCAL test server only
(MYSQL_TEST_ROOT_PASSWORD from .env; refuses port 3306). Only timings and counts are printed.

    python scripts/perf1_search_options.py --build      # one-off: create cortex_perf1_proto (minutes at 200k rows)
    python scripts/perf1_search_options.py --runs 5 --json perf1.json
    python scripts/perf1_search_options.py --drop       # remove the scratch database
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parents[1]
PROTO = "cortex_perf1_proto"
QUERIES = ["energy storage", "solar", "grant", "battery", "hydrogen fuel", "climate", "ai", "biotech", "water",
           "university", "innovation fund", "carbon"]  # fmt: skip
ACTIVE = "o.status IN ('active','watchlist')"


def env() -> dict[str, str]:
    out = dict(os.environ)
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            k, sep, v = line.partition("=")
            if sep:
                out.setdefault(k.strip(), v.strip().strip('"'))
    return out


def connect(e: dict[str, str], db: str | None = None) -> pymysql.Connection:
    port = int(e.get("MYSQL_TEST_PORT", "53306"))
    if port == 3306:
        raise SystemExit("refusing port 3306: this tool runs against the isolated local test server only")
    return pymysql.connect(host=e.get("MYSQL_TEST_HOST", "127.0.0.1"), port=port, user="root",
                           password=e["MYSQL_TEST_ROOT_PASSWORD"], database=db, autocommit=True,
                           read_timeout=600)  # fmt: skip


def build(c: pymysql.Connection, src: str) -> None:
    with c.cursor() as cur:
        cur.execute(f"CREATE DATABASE IF NOT EXISTS {PROTO} CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
        cur.execute(f"DROP TABLE IF EXISTS {PROTO}.opp")
        cur.execute(
            f"CREATE TABLE {PROTO}.opp (id VARCHAR(36) PRIMARY KEY, title VARCHAR(500), description TEXT, "
            "cp_name VARCHAR(255), FULLTEXT KEY ft_word (title, description), "
            "FULLTEXT KEY ft_ngram_title (title) WITH PARSER ngram, "
            "FULLTEXT KEY ft_ngram_cp (cp_name) WITH PARSER ngram) ENGINE=InnoDB"
        )
        t = time.perf_counter()
        cur.execute(
            f"INSERT INTO {PROTO}.opp SELECT o.id, o.title, o.description, cp.name FROM {src}.opportunity o "
            f"LEFT JOIN {src}.organization cp ON cp.id = o.counterparty_id WHERE {ACTIVE}"
        )
        print(f"built {PROTO}.opp: {cur.rowcount} rows in {time.perf_counter() - t:.1f} s")
        cur.execute(
            "SELECT ROUND(SUM(index_length)/1048576,1), ROUND(SUM(data_length)/1048576,1) FROM information_schema.tables "
            "WHERE table_schema = %s",
            (PROTO,),
        )
        idx, data = cur.fetchone()
        cur.execute("SELECT @@ngram_token_size")
        print(f"index {idx} MB, data {data} MB, ngram_token_size={cur.fetchone()[0]}")


def ids(cur, sql: str, args: tuple) -> tuple[set[str], float]:
    t = time.perf_counter()
    cur.execute(sql, args)
    rows = {r[0] for r in cur.fetchall()}
    return rows, time.perf_counter() - t


def run(c: pymysql.Connection, src: str, runs: int) -> list[dict]:
    current = (
        f"SELECT o.id FROM {src}.opportunity o LEFT JOIN {src}.organization cp ON cp.id = o.counterparty_id "
        f"WHERE {ACTIVE} AND (MATCH(o.title, o.description) AGAINST(%s IN NATURAL LANGUAGE MODE) "
        "OR o.title LIKE %s OR cp.name LIKE %s)"
    )
    fulltext_only = (
        f"SELECT o.id FROM {src}.opportunity o WHERE {ACTIVE} "
        "AND MATCH(o.title, o.description) AGAINST(%s IN NATURAL LANGUAGE MODE)"
    )
    ngram = (
        f"SELECT id FROM {PROTO}.opp WHERE MATCH(title, description) AGAINST(%s IN NATURAL LANGUAGE MODE) "
        f"UNION SELECT id FROM {PROTO}.opp WHERE MATCH(title) AGAINST(%s IN BOOLEAN MODE) "
        f"UNION SELECT id FROM {PROTO}.opp WHERE MATCH(cp_name) AGAINST(%s IN BOOLEAN MODE)"
    )
    out = []
    with c.cursor() as cur:
        for q in QUERIES:
            like, phrase = f"%{q}%", '"' + q.replace('"', "") + '"'
            variants = {"current": (current, (q, like, like)), "A_fulltext_only": (fulltext_only, (q,)),
                        "C_ngram": (ngram, (q, phrase, phrase))}  # fmt: skip
            res: dict[str, dict] = {}
            for name, (sql, args) in variants.items():
                ids(cur, sql, args)  # warm-up
                times, got = [], set()
                for _ in range(runs):
                    got, dt = ids(cur, sql, args)
                    times.append(dt)
                res[name] = {"ids": got, "ms": round(statistics.median(times) * 1000, 1)}
            ref = res["current"]["ids"]
            row = {"q": q, "current_n": len(ref), "current_ms": res["current"]["ms"]}
            for name in ("A_fulltext_only", "C_ngram"):
                got = res[name]["ids"]
                tp = len(got & ref)
                row[name] = {"n": len(got), "ms": res[name]["ms"],
                             "recall_vs_current": round(tp / len(ref), 4) if ref else None,
                             "precision_vs_current": round(tp / len(got), 4) if got else None}  # fmt: skip
            out.append(row)
            print(json.dumps(row))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default="cortex_bench_1m")
    ap.add_argument("--build", action="store_true")
    ap.add_argument("--drop", action="store_true")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--json")
    a = ap.parse_args()
    c = connect(env())
    try:
        if a.drop:
            with c.cursor() as cur:
                cur.execute(f"DROP DATABASE IF EXISTS {PROTO}")
            print(f"dropped {PROTO}")
            return
        if a.build:
            build(c, a.source)
            return
        rows = run(c, a.source, a.runs)
        if a.json:
            Path(a.json).write_text(json.dumps(rows, indent=1), encoding="utf-8")
    finally:
        c.close()


if __name__ == "__main__":
    main()
