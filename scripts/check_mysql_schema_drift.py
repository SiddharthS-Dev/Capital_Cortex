"""MySQL schema drift check: compare databases against a reference built from the migration history (read-only).

The reference is a database created by `alembic -n mysql upgrade head` (the schema exactly as the migrations define
it). Every target database on the same server is compared with it on: tables, columns (type, nullability,
default), indexes (columns, uniqueness), foreign keys (columns, referenced table/columns, ON DELETE/UPDATE), CHECK
constraints (by name) and triggers (timing/event/table), plus the Alembic revision. Exit status 1 when any target
drifts, so CI can gate on it.

    python scripts/check_mysql_schema_drift.py --reference cortex_ref --targets cortex cortex_demo cortex_integration

Connection: MYSQL_HOST/MYSQL_TEST_PORT/MYSQL_TEST_USER and MYSQL_TEST_PASSWORD (or MYSQL_TEST_PASSWORD_FILE) from the
environment or .env. Only SELECTs on information_schema and alembic_version are issued; nothing is written.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import pymysql

ROOT = Path(__file__).resolve().parents[1]
IGNORED_TABLES = {"alembic_version"}


def _env() -> dict[str, str]:
    env: dict[str, str] = {}
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$", line)
            if m:
                env[m[1]] = m[2].strip().strip('"')
    env.update(os.environ)
    if not env.get("MYSQL_TEST_PASSWORD") and env.get("MYSQL_TEST_PASSWORD_FILE"):
        env["MYSQL_TEST_PASSWORD"] = Path(env["MYSQL_TEST_PASSWORD_FILE"]).read_text(encoding="utf-8").strip()
    return env


def connect() -> pymysql.Connection:
    env = _env()
    if not env.get("MYSQL_TEST_PASSWORD"):
        raise SystemExit("set MYSQL_TEST_PASSWORD (or MYSQL_TEST_PASSWORD_FILE) in the environment or .env")
    return pymysql.connect(
        host=env.get("MYSQL_HOST", "127.0.0.1"),
        port=int(env.get("MYSQL_TEST_PORT") or 53306),
        user=env.get("MYSQL_TEST_USER") or "cortex",
        password=env["MYSQL_TEST_PASSWORD"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def _rows(cur, sql: str, db: str) -> list[dict[str, Any]]:
    cur.execute(sql, {"db": db})
    return list(cur.fetchall())


def snapshot(cur, db: str) -> dict[str, Any]:
    """Normalised structure of one database (comparable across databases: no schema names, no auto names)."""
    cols = _rows(
        cur,
        "SELECT table_name t, column_name c, column_type ty, is_nullable n, column_default d, extra x "
        "FROM information_schema.columns WHERE table_schema = %(db)s",
        db,
    )
    idx = _rows(
        cur,
        "SELECT table_name t, index_name i, non_unique nu, GROUP_CONCAT(CONCAT(column_name, "
        "IF(collation = 'D', ' DESC', '')) ORDER BY seq_in_index) cols "
        "FROM information_schema.statistics WHERE table_schema = %(db)s GROUP BY table_name, index_name, non_unique",
        db,
    )
    fks = _rows(
        cur,
        "SELECT k.table_name t, k.constraint_name n, GROUP_CONCAT(k.column_name ORDER BY k.ordinal_position) cols, "
        "k.referenced_table_name rt, GROUP_CONCAT(k.referenced_column_name ORDER BY k.ordinal_position) rcols, "
        "r.delete_rule dr, r.update_rule ur FROM information_schema.key_column_usage k "
        "JOIN information_schema.referential_constraints r ON r.constraint_schema = k.constraint_schema "
        "AND r.constraint_name = k.constraint_name AND r.table_name = k.table_name "
        "WHERE k.table_schema = %(db)s AND k.referenced_table_name IS NOT NULL "
        "GROUP BY k.table_name, k.constraint_name, k.referenced_table_name, r.delete_rule, r.update_rule",
        db,
    )
    checks = _rows(
        cur,
        "SELECT tc.table_name t, tc.constraint_name n FROM information_schema.table_constraints tc "
        "WHERE tc.table_schema = %(db)s AND tc.constraint_type = 'CHECK'",
        db,
    )
    trg = _rows(
        cur,
        "SELECT trigger_name n, action_timing ti, event_manipulation ev, event_object_table t "
        "FROM information_schema.triggers WHERE trigger_schema = %(db)s",
        db,
    )
    tables = {
        r["t"]
        for r in _rows(
            cur,
            "SELECT table_name t FROM information_schema.tables WHERE table_schema = %(db)s "
            "AND table_type = 'BASE TABLE'",
            db,
        )
    } - IGNORED_TABLES
    try:
        cur.execute(f"SELECT version_num FROM `{db}`.alembic_version")
        rev = [r["version_num"] for r in cur.fetchall()]
    except pymysql.MySQLError:
        rev = []
    keep = lambda r: r["t"] not in IGNORED_TABLES  # noqa: E731
    return {
        "revision": rev,
        "tables": sorted(tables),
        "columns": {
            f"{r['t']}.{r['c']}": f"{r['ty']} {'NULL' if r['n'] == 'YES' else 'NOT NULL'} "
            f"default={r['d']} {r['x'] or ''}".strip()
            for r in cols
            if keep(r)
        },
        "indexes": {
            f"{r['t']}.{r['i']}": f"{'unique' if not int(r['nu']) else 'index'}({r['cols']})" for r in idx if keep(r)
        },
        "foreign_keys": {
            f"{r['t']}.{r['n']}": f"({r['cols']})->{r['rt']}({r['rcols']}) del={r['dr']} upd={r['ur']}"
            for r in fks
            if keep(r)
        },
        "checks": sorted(f"{r['t']}.{r['n']}" for r in checks if keep(r)),
        "triggers": {r["n"]: f"{r['ti']} {r['ev']} ON {r['t']}" for r in trg},
    }


def diff(ref: dict[str, Any], tgt: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if ref["revision"] != tgt["revision"]:
        out["revision"] = {"expected": ref["revision"], "actual": tgt["revision"]}
    for key in ("tables", "checks"):
        missing, extra = sorted(set(ref[key]) - set(tgt[key])), sorted(set(tgt[key]) - set(ref[key]))
        if missing or extra:
            out[key] = {"missing": missing, "extra": extra}
    for key in ("columns", "indexes", "foreign_keys", "triggers"):
        r, t = ref[key], tgt[key]
        missing = sorted(set(r) - set(t))
        extra = sorted(set(t) - set(r))
        changed = {k: {"expected": r[k], "actual": t[k]} for k in sorted(set(r) & set(t)) if r[k] != t[k]}
        if missing or extra or changed:
            out[key] = {"missing": missing, "extra": extra, "changed": changed}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--reference", required=True, help="database built by `alembic -n mysql upgrade head`")
    ap.add_argument("--targets", nargs="+", required=True)
    ap.add_argument("--json", help="also write the full result to this file")
    args = ap.parse_args(argv)
    with connect() as conn, conn.cursor() as cur:
        ref = snapshot(cur, args.reference)
        if not ref["tables"]:
            raise SystemExit(f"reference database {args.reference!r} has no tables")
        results = {db: diff(ref, snapshot(cur, db)) for db in args.targets}
    drifted = {db: d for db, d in results.items() if d}
    for db, d in results.items():
        if not d:
            print(f"OK      {db}: matches {args.reference} (revision {ref['revision']})")
            continue
        print(f"DRIFT   {db}:")
        for key, v in d.items():
            if key == "revision":
                print(f"          revision {v['actual']} (expected {v['expected']})")
                continue
            for kind in ("missing", "extra"):
                for item in v.get(kind, []):
                    print(f"          {key} {kind}: {item}")
            for item, ch in (v.get("changed") or {}).items():
                print(f"          {key} changed: {item}: {ch['actual']}  (expected {ch['expected']})")
    if args.json:
        Path(args.json).write_text(
            json.dumps({"reference": args.reference, "results": results}, indent=1), encoding="utf-8"
        )
    print(f"{len(drifted)} of {len(results)} database(s) drift from {args.reference}")
    return 1 if drifted else 0


if __name__ == "__main__":
    sys.exit(main())
