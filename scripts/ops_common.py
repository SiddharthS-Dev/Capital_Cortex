"""Shared helpers for the ops scripts (backup.py, restore_drill.py, load_seed.py, scan.py).

Settings come from the repo-root ``.env`` (the same file Compose uses) overridden by the process
environment, with the Compose defaults as the fallback. Nothing here touches application code.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
COMPOSE_FILES = ["-f", "infra/docker-compose.yml", "-f", "infra/docker-compose.dev.yml"]
PROJECT = "capital-cortex"
BUCKET = "cortex-backups"

# Tables compared by the restore drill (row counts). Everything the platform treats as a record of truth.
KEY_TABLES = [
    "tenant",
    "source",
    "source_run",
    "signal",
    "organization",
    "investor",
    "fund",
    "grant_program",
    "opportunity",
    "contact",
    "meeting",
    "interaction",
    "relationship",
    "milestone",
    "entity",
    "relationship_edge",
    "embedding",
    "scoring_profile",
    "financial_snapshot",
    "forecast",
    "outcome",
    "memory",
    "agent_run",
    "recommendation",
    "approval",
    "approval_decision",
    "outbox",
    "alert",
    "alert_rule",
    "inference",
    "ml_model",
    "document",
    "proposal",
    "audit_log",
]
GRAPH_TABLES = ["ckg._ag_label_vertex", "ckg._ag_label_edge"]


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k.isupper()})
    return env


ENV = load_env()


def setting(name: str, default: str) -> str:
    v = ENV.get(name)
    return v if v else default


PG_PASSWORD = setting("POSTGRES_PASSWORD", "cortex-dev-pw")
PG_PORT = int(setting("PG_PORT", "55432"))
MINIO_ENDPOINT = f"localhost:{setting('MINIO_PORT', '9300')}"
MINIO_USER = setting("MINIO_ROOT_USER", "cortex")
MINIO_PASSWORD = setting("MINIO_ROOT_PASSWORD", "cortex-dev-minio")
PG_CONTAINER = setting("CORTEX_PG_CONTAINER", f"{PROJECT}-postgres-1")


def compose_cmd() -> list[str]:
    cmd = ["docker", "compose", *COMPOSE_FILES]
    if (ROOT / ".env").exists():
        cmd += ["--env-file", ".env"]
    return cmd


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def run(
    argv: Sequence[str],
    *,
    check: bool = True,
    capture: bool = True,
    input: bytes | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[bytes]:
    p = subprocess.run(list(argv), cwd=ROOT, input=input, capture_output=capture, timeout=timeout, check=False)  # noqa: S603 - fixed argv
    if check and p.returncode != 0:
        err = (p.stderr or b"").decode("utf-8", "replace").strip()
        raise RuntimeError(f"{' '.join(argv[:6])} ... failed ({p.returncode}): {err[-2000:]}")
    return p


def out(argv: Sequence[str], **kw: Any) -> str:
    return run(argv, **kw).stdout.decode("utf-8", "replace").strip()


def psql(container: str, sql: str, db: str = "cortex", user: str = "cortex") -> str:
    """Run SQL in a container through the local socket (trust auth) and return unaligned output."""
    return out(
        [
            "docker",
            "exec",
            "-i",
            container,
            "psql",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            user,
            "-d",
            db,
            "-Atq",
            "-c",
            sql,
        ]
    )


def minio_client():  # type: ignore[no-untyped-def]
    from minio import Minio

    return Minio(MINIO_ENDPOINT, access_key=MINIO_USER, secret_key=MINIO_PASSWORD, secure=False)


def pg_connect(port: int = PG_PORT, db: str = "cortex", **kw: Any):  # type: ignore[no-untyped-def]
    import psycopg

    return psycopg.connect(
        host="127.0.0.1", port=port, user="cortex", password=PG_PASSWORD, dbname=db, connect_timeout=10, **kw
    )


def table_counts(cur: Any, tables: Iterable[str] = (*KEY_TABLES, *GRAPH_TABLES)) -> dict[str, int | None]:
    """Exact row counts; a table that doesn't exist (older schema) counts as None."""
    counts: dict[str, int | None] = {}
    for t in tables:
        schema, _, name = t.rpartition(".")
        cur.execute("SELECT to_regclass(%s)", (f'{schema or "public"}."{name}"',))
        if cur.fetchone()[0] is None:
            counts[t] = None
            continue
        cur.execute(f'SELECT count(*) FROM {schema or "public"}."{name}"')  # noqa: S608 - fixed allowlist
        counts[t] = int(cur.fetchone()[0])
    return counts


def audit_head(cur: Any) -> dict[str, Any]:
    cur.execute("SELECT seq, hash FROM audit_log ORDER BY seq DESC LIMIT 1")
    r = cur.fetchone()
    return {"seq": r[0], "hash": r[1].strip()} if r else {"seq": None, "hash": None}


def verify_audit_chain(cur: Any, batch: int = 5000) -> dict[str, Any]:
    """Recompute every link with the platform's own verifier (platform_core/audit/chain.py)."""
    sys.path.insert(0, str(ROOT))
    from platform_core.audit.chain import GENESIS_HASH, AuditRecord, verify_records

    prev, expected, total = GENESIS_HASH, 1, 0
    head: tuple[int | None, str | None] = (None, None)
    while True:
        cur.execute(
            "SELECT seq, org_id, actor, action, target, meta, ts, prev_hash, hash FROM audit_log "
            "WHERE seq >= %s ORDER BY seq LIMIT %s",
            (expected, batch),
        )
        rows = cur.fetchall()
        if not rows:
            break
        recs = [
            AuditRecord(r[0], str(r[1]), r[2], r[3], r[4], r[5] or {}, r[6], r[7].strip(), r[8].strip()) for r in rows
        ]
        res = verify_records(recs, prev, expected)
        total += res.checked
        if not res.ok:
            return {"ok": False, "checked": total, "first_broken_seq": res.first_broken_seq, "reason": res.reason}
        prev, expected = recs[-1].hash, recs[-1].seq + 1
        head = (recs[-1].seq, recs[-1].hash)
    return {"ok": True, "checked": total, "head_seq": head[0], "head_hash": head[1]}


def dump_json(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, default=str)
