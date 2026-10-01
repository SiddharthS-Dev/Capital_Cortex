"""Base backup + logical dumps of the Cortex Postgres server into MinIO ``cortex-backups`` (D-031, RUNBOOK §8).

Layout in the bucket::

    wal/<segment>.gz                       continuous WAL archive (archive_command + wal-shipper)
    backups/<id>/base.tar.gz               pg_basebackup of the whole cluster (tar, gzip, WAL included)
    backups/<id>/cortex.dump               pg_dump -Fc of `cortex`, taken from an exported snapshot
    backups/<id>/keycloak.dump             pg_dump -Fc of `keycloak` (users, TOTP credentials, realm)
    backups/<id>/globals.sql               pg_dumpall --globals-only (roles)
    backups/<id>/manifest.json             sha256 + size of every file, start WAL segment, and the row
                                           counts + audit head read inside the dump's snapshot

Usage: python scripts/backup.py [--keep 7] [--skip-logical] [--skip-base]
Runs from the host (venv). pg tools run inside the postgres container (exact server version, local socket).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import sys
import tarfile
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from ops_common import (
    BUCKET,
    PG_CONTAINER,
    ROOT,
    audit_head,
    dump_json,
    log,
    minio_client,
    out,
    pg_connect,
    table_counts,
)

WAL_DIR = "/var/lib/postgresql/wal-archive"
_SEG = re.compile(r"^[0-9A-F]{24}")


def stream_to_file(argv: list[str], dest: Path) -> dict[str, Any]:
    """Run a command and stream its stdout into ``dest`` while hashing it."""
    h = hashlib.sha256()
    n = 0
    with dest.open("wb") as f, subprocess.Popen(argv, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as p:  # noqa: S603 - fixed argv
        assert p.stdout is not None
        while chunk := p.stdout.read(1 << 20):
            f.write(chunk)
            h.update(chunk)
            n += len(chunk)
        err = p.stderr.read().decode("utf-8", "replace") if p.stderr else ""
        rc = p.wait()
    if rc != 0:
        raise RuntimeError(f"{' '.join(argv[:5])} failed ({rc}): {err[-1500:]}")
    return {"sha256": h.hexdigest(), "bytes": n}


def start_wal_from_base(path: Path) -> tuple[str, str]:
    """Read backup_label from the base tarball: (start WAL file, start LSN)."""
    with tarfile.open(path, "r:gz") as tf:
        for m in tf:
            if m.name.lstrip("./") == "backup_label":
                label = tf.extractfile(m).read().decode()  # type: ignore[union-attr]
                mm = re.search(r"START WAL LOCATION: (\S+) \(file ([0-9A-F]{24})\)", label)
                if mm:
                    return mm.group(2), mm.group(1)
    raise RuntimeError("backup_label not found in base backup")


def logical_dumps(tmp: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """pg_dump of `cortex` from an exported snapshot, so the manifest's counts are exactly the dump's."""
    files: dict[str, Any] = {}
    with pg_connect() as conn:
        conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        snap = conn.execute("SELECT pg_export_snapshot()").fetchone()[0]
        with conn.cursor() as cur:
            counts = table_counts(cur)
            head = audit_head(cur)
            cur.execute("SELECT version_num FROM alembic_version")
            alembic = [r[0] for r in cur.fetchall()]
        log(f"logical: pg_dump cortex (snapshot {snap})")
        files["cortex.dump"] = stream_to_file(
            ["docker", "exec", PG_CONTAINER, "pg_dump", "-U", "cortex", "-Fc", f"--snapshot={snap}", "cortex"],
            tmp / "cortex.dump",
        )
        conn.rollback()
    log("logical: pg_dump keycloak, pg_dumpall --globals-only")
    files["keycloak.dump"] = stream_to_file(
        ["docker", "exec", PG_CONTAINER, "pg_dump", "-U", "cortex", "-Fc", "keycloak"], tmp / "keycloak.dump"
    )
    files["globals.sql"] = stream_to_file(
        ["docker", "exec", PG_CONTAINER, "pg_dumpall", "-U", "cortex", "--globals-only"], tmp / "globals.sql"
    )
    return files, {"snapshot": snap, "counts": counts, "audit_head": head, "alembic": alembic}


def base_backup(tmp: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    log("base: pg_basebackup (tar, gzip, fetch WAL, fast checkpoint)")
    t = time.monotonic()
    info = stream_to_file(
        [
            "docker",
            "exec",
            PG_CONTAINER,
            "pg_basebackup",
            "-U",
            "cortex",
            "-D",
            "-",
            "-Ft",
            "-z",
            "-X",
            "fetch",
            "-c",
            "fast",
            "-l",
            label,
        ],
        tmp / "base.tar.gz",
    )
    seg, lsn = start_wal_from_base(tmp / "base.tar.gz")
    # Close the current segment so the WAL written during the backup reaches the archive promptly.
    with pg_connect() as conn:
        conn.execute("SELECT pg_switch_wal()")
    return {"base.tar.gz": info}, {"start_wal": seg, "start_lsn": lsn, "seconds": round(time.monotonic() - t, 1)}


def prune(keep: int) -> dict[str, Any]:
    """Keep the newest ``keep`` backups; drop WAL older than the oldest kept base (bucket + archive volume)."""
    c = minio_client()
    ids = sorted({o.object_name.split("/")[1] for o in c.list_objects(BUCKET, prefix="backups/", recursive=True)})
    manifests = []
    for i in ids:
        try:
            manifests.append(json.loads(c.get_object(BUCKET, f"backups/{i}/manifest.json").read()))
        except Exception:  # noqa: S112 - no manifest yet = incomplete backup, never kept
            continue
    complete = [m for m in manifests if m.get("base")]
    kept = complete[-keep:]
    removed_backups = []
    kept_ids = {m["id"] for m in kept}
    for i in ids:
        if i not in kept_ids and (not kept or i < kept[0]["id"]):
            for o in c.list_objects(BUCKET, prefix=f"backups/{i}/", recursive=True):
                c.remove_object(BUCKET, o.object_name)
            removed_backups.append(i)
    removed_wal = 0
    if kept:
        oldest = kept[0]["base"]["start_wal"]
        for o in c.list_objects(BUCKET, prefix="wal/", recursive=True):
            name = o.object_name.split("/", 1)[1]
            if _SEG.match(name) and name[:24] < oldest and ".history" not in name:
                c.remove_object(BUCKET, o.object_name)
                removed_wal += 1
        # local archive volume: pg_archivecleanup removes segments older than the oldest kept base
        out(["docker", "exec", "-u", "postgres", PG_CONTAINER, "pg_archivecleanup", "-x", ".gz", WAL_DIR, oldest])
    return {"kept": [m["id"] for m in kept], "removed_backups": removed_backups, "removed_wal_objects": removed_wal}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--keep", type=int, default=7, help="base backups to keep (default 7 = a week of nightlies)")
    ap.add_argument("--skip-logical", action="store_true")
    ap.add_argument("--skip-base", action="store_true")
    args = ap.parse_args()

    started = datetime.now(UTC)
    bid = started.strftime("%Y%m%dT%H%M%SZ")
    c = minio_client()
    if not c.bucket_exists(BUCKET):
        c.make_bucket(BUCKET)
    manifest: dict[str, Any] = {
        "id": bid,
        "started_at": started.isoformat(),
        "server": out(["docker", "exec", PG_CONTAINER, "postgres", "--version"]),
        "container": PG_CONTAINER,
        "files": {},
    }
    with pg_connect() as conn:
        manifest["archiver"] = dict(
            zip(
                ("archive_mode", "archive_timeout"),
                conn.execute("SELECT current_setting('archive_mode'), current_setting('archive_timeout')").fetchone(),
                strict=True,
            )
        )
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="cortex-backup-") as d:
        tmp = Path(d)
        if not args.skip_logical:
            files, meta = logical_dumps(tmp)
            manifest["files"].update(files)
            manifest["logical"] = meta
        if not args.skip_base:
            files, meta = base_backup(tmp, f"cortex-{bid}")
            manifest["files"].update(files)
            manifest["base"] = meta
        for name, info in manifest["files"].items():
            log(f"upload backups/{bid}/{name} ({info['bytes'] / 1e6:.1f} MB, sha256 {info['sha256'][:12]}...)")
            c.fput_object(
                BUCKET, f"backups/{bid}/{name}", str(tmp / name), metadata={"x-amz-meta-sha256": info["sha256"]}
            )
    manifest["finished_at"] = datetime.now(UTC).isoformat()
    manifest["seconds"] = round(time.monotonic() - t0, 1)
    body = dump_json(manifest).encode()
    # the manifest goes last: a backup without one is incomplete and is ignored by the restore drill
    c.put_object(BUCKET, f"backups/{bid}/manifest.json", io.BytesIO(body), len(body), content_type="application/json")
    manifest["retention"] = prune(args.keep)
    wal = [o for o in c.list_objects(BUCKET, prefix="wal/", recursive=True)]
    summary = {
        "id": bid,
        "seconds": manifest["seconds"],
        "files": {k: v["bytes"] for k, v in manifest["files"].items()},
        "start_wal": manifest.get("base", {}).get("start_wal"),
        "audit_head": manifest.get("logical", {}).get("audit_head"),
        "wal_objects_in_bucket": len(wal),
        "retention": manifest["retention"],
    }
    log("backup complete\n" + dump_json(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
