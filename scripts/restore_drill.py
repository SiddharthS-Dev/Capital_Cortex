"""Restore drill (D-031, RUNBOOK §8): restore the latest backup into a SCRATCH server and prove it is good.

Never touches the live server or its volumes. Steps:

1. Live checkpoint: count every key table (T0), force a WAL switch, count again (T1), wait until the switched
   segment is in MinIO. The age of the last archived segment just before the switch is the data that a real
   disaster at that instant would have lost (measured RPO exposure).
2. Download the newest complete backup (manifest last) and every WAL segment after its start; verify each file's
   sha256 against the manifest.
3. Physical PITR: unpack base.tar.gz into a scratch volume, replay the WAL archive to the end
   (recovery_target_timeline=latest, promote) in container ``capital-cortex-restore-drill``. RTO = drill start →
   promoted server accepting queries.
4. Verify: per-table row counts (T0 ≤ restored ≤ T1), the audit hash chain recomputed with
   platform_core/audit/chain.py, the audit head at T0 present with the same hash, the AGE graph answers Cypher,
   Keycloak users restored.
5. Logical: pg_restore cortex.dump / keycloak.dump into scratch databases on the same scratch server; counts must
   equal the manifest's snapshot counts exactly; the chain must verify.
6. Print a pass/fail report (and --report FILE as JSON); remove the scratch container and volume (unless --keep).

Usage: python scripts/restore_drill.py [--backup-id ID] [--skip-logical] [--no-switch] [--keep] [--report FILE]
       [--target-time '2026-09-30 09:00:00+00']   (point-in-time recovery; see RUNBOOK §8 for promoting it)
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
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
    audit_head,
    dump_json,
    log,
    minio_client,
    out,
    pg_connect,
    run,
    setting,
    table_counts,
    verify_audit_chain,
)

DRILL = "capital-cortex-restore-drill"
DRILL_PORT = int(setting("DRILL_PG_PORT", "8386"))
IMAGE = "capital-cortex/postgres:16-age1.5.0-pgvector0.8.0"
RTO_SLO_S = 3600
RPO_SLO_S = 900


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def latest_backup(c: Any, wanted: str | None) -> dict[str, Any]:
    ids = sorted({o.object_name.split("/")[1] for o in c.list_objects(BUCKET, prefix="backups/", recursive=True)})
    for i in reversed(ids):
        if wanted and i != wanted:
            continue
        try:
            m = json.loads(c.get_object(BUCKET, f"backups/{i}/manifest.json").read())
        except Exception:  # noqa: S112 - no manifest yet = incomplete backup
            continue
        if m.get("base"):
            return m
    raise SystemExit(f"no complete backup found in {BUCKET}/backups/" + (f" with id {wanted}" if wanted else ""))


def live_checkpoint(switch: bool) -> dict[str, Any]:
    with pg_connect() as conn, conn.cursor() as cur:
        cur.execute("SELECT last_archived_wal, last_archived_time, now() FROM pg_stat_archiver")
        last_wal, last_time, now = cur.fetchone()
        exposure = (now - last_time).total_seconds() if last_time else None
        t0 = table_counts(cur)
        head0 = audit_head(cur)
        seg = None
        if switch:
            cur.execute("SELECT pg_walfile_name(pg_switch_wal())")
            seg = cur.fetchone()[0]
        conn.commit()
        t1 = table_counts(cur)
    return {
        "at": datetime.now(UTC).isoformat(),
        "rpo_exposure_s": exposure,
        "last_archived_wal": last_wal,
        "t0": t0,
        "t1": t1,
        "audit_head_t0": head0,
        "switched_segment": seg,
    }


def wait_shipped(c: Any, seg: str, timeout: float = 180) -> float:
    """Seconds until the switched segment is archived locally and then visible in MinIO."""
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        try:
            c.stat_object(BUCKET, f"wal/{seg}.gz")
            return time.monotonic() - t
        except Exception:
            time.sleep(2)
    raise SystemExit(f"WAL segment {seg} did not reach MinIO within {timeout:.0f}s: is wal-shipper running?")


def download(c: Any, m: dict[str, Any], tmp: Path, logical: bool) -> dict[str, Any]:
    checks = {}
    names = ["base.tar.gz"] + (["cortex.dump", "keycloak.dump", "globals.sql"] if logical else [])
    for name in names:
        info = m["files"].get(name)
        if not info:
            checks[name] = {"ok": False, "reason": "missing from manifest"}
            continue
        c.fget_object(BUCKET, f"backups/{m['id']}/{name}", str(tmp / name))
        got = sha256_file(tmp / name)
        checks[name] = {"ok": got == info["sha256"], "bytes": (tmp / name).stat().st_size}
    start = m["base"]["start_wal"]
    wal_dir = tmp / "wal"
    wal_dir.mkdir()
    n = 0
    for o in c.list_objects(BUCKET, prefix="wal/", recursive=True):
        name = o.object_name.split("/", 1)[1]
        if name[:24] >= start or ".history" in name:
            c.fget_object(BUCKET, o.object_name, str(wal_dir / name))
            n += 1
    return {"files": checks, "wal_segments": n}


def tar_dir(d: Path) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for p in sorted(d.iterdir()):
            tf.add(p, arcname=p.name)
    return buf.getvalue()


def cleanup() -> None:
    run(["docker", "rm", "-f", DRILL], check=False)
    run(["docker", "volume", "rm", "-f", DRILL], check=False)


def start_scratch(tmp: Path, logical: bool, target_time: str | None = None) -> None:
    assert DRILL != PG_CONTAINER
    cleanup()
    run(["docker", "volume", "create", "--label", "capital-cortex.role=restore-drill", DRILL])
    loader = ["docker", "run", "--rm", "-i", "-v", f"{DRILL}:/drill", "--entrypoint", "sh", IMAGE, "-c"]
    run(
        [
            *loader,
            "mkdir -p /drill/data /drill/wal /drill/logical && tar -xzf - -C /drill/data && "
            "touch /drill/data/recovery.signal",
        ],
        input=(tmp / "base.tar.gz").read_bytes(),
    )
    run([*loader, "tar -xf - -C /drill/wal"], input=tar_dir(tmp / "wal"))
    if logical:
        ld = tmp / "logical"
        ld.mkdir()
        for n in ("cortex.dump", "keycloak.dump", "globals.sql"):
            (tmp / n).replace(ld / n)
        run([*loader, "tar -xf - -C /drill/logical"], input=tar_dir(ld))
    run([*loader, "chown -R postgres:postgres /drill && chmod 700 /drill/data"])
    run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            DRILL,
            "--label",
            "capital-cortex.role=restore-drill",
            "-e",
            "PGDATA=/drill/data",
            "-e",
            "POSTGRES_PASSWORD=unused-existing-cluster",
            "-v",
            f"{DRILL}:/drill",
            "-p",
            f"127.0.0.1:{DRILL_PORT}:5432",
            IMAGE,
            "postgres",
            "-c",
            "shared_buffers=256MB",
            "-c",
            "max_connections=200",
            "-c",
            "archive_mode=off",
            "-c",
            "restore_command=gzip -dc /drill/wal/%f.gz > %p",
            "-c",
            "recovery_target_timeline=latest",
            "-c",
            "recovery_target_action=promote",
            *(["-c", f"recovery_target_time={target_time}"] if target_time else []),
        ]
    )


def wait_promoted(timeout: float = RTO_SLO_S) -> None:
    t = time.monotonic()
    while time.monotonic() - t < timeout:
        state = out(["docker", "inspect", "-f", "{{.State.Running}}", DRILL], check=False)
        if state != "true":
            logs = out(["docker", "logs", "--tail", "40", DRILL], check=False)
            raise SystemExit(f"scratch server exited during recovery:\n{logs}")
        p = run(
            [
                "docker",
                "exec",
                DRILL,
                "psql",
                "-X",
                "-U",
                "cortex",
                "-d",
                "postgres",
                "-h",
                "127.0.0.1",
                "-Atc",
                "SELECT pg_is_in_recovery()",
            ],
            check=False,
        )
        if p.returncode == 0 and p.stdout.decode().strip() == "f":
            return
        time.sleep(1)
    raise SystemExit("scratch server did not finish recovery within the RTO budget")


def compare(restored: dict[str, int | None], t0: dict[str, int | None], t1: dict[str, int | None]) -> list[dict]:
    rows = []
    for t, r in restored.items():
        a, b = t0.get(t), t1.get(t)
        if a is None and r is None:
            status = "n/a"
        elif r == a:
            status = "exact"
        elif a is not None and b is not None and r is not None and min(a, b) <= r <= max(a, b):
            status = "window"  # a write committed between the T0 count and the WAL switch
        else:
            status = "MISMATCH"
        rows.append({"table": t, "live_t0": a, "live_t1": b, "restored": r, "status": status})
    return rows


def age_probe(conn: Any) -> int:
    with conn.cursor() as cur:
        cur.execute("LOAD '$libdir/plugins/age'")
        cur.execute('SET search_path = ag_catalog, "$user", public')
        cur.execute("SELECT count(*) FROM cypher('ckg', $$ MATCH (n) RETURN n $$) AS (n agtype)")
        n = int(cur.fetchone()[0])
    conn.rollback()
    return n


def keycloak_users(db: str) -> int | None:
    p = run(
        ["docker", "exec", DRILL, "psql", "-X", "-U", "cortex", "-d", db, "-Atc", "SELECT count(*) FROM user_entity"],
        check=False,
    )
    return int(p.stdout.decode().strip()) if p.returncode == 0 else None


def logical_restore(m: dict[str, Any]) -> dict[str, Any]:
    t = time.monotonic()
    res: dict[str, Any] = {}
    for db, dump in (("cortex_logical", "cortex.dump"), ("keycloak_logical", "keycloak.dump")):
        run(["docker", "exec", DRILL, "createdb", "-U", "cortex", db])
        p = run(
            ["docker", "exec", DRILL, "pg_restore", "-U", "cortex", "-d", db, "--no-owner", f"/drill/logical/{dump}"],
            check=False,
        )
        err = p.stderr.decode("utf-8", "replace")
        res[dump] = {"exit": p.returncode, "errors": err.count("ERROR"), "stderr_tail": err.strip()[-600:]}
    res["seconds"] = round(time.monotonic() - t, 1)
    with pg_connect(DRILL_PORT, "cortex_logical") as conn, conn.cursor() as cur:
        got = table_counts(cur)
        chain = verify_audit_chain(cur)
        try:
            res["age_vertices_via_cypher"] = age_probe(conn)
        except Exception as e:
            conn.rollback()
            res["age_vertices_via_cypher"] = f"ERROR: {e}"
    want = m["logical"]["counts"]
    res["counts"] = [
        {
            "table": t,
            "manifest": want.get(t),
            "restored": got.get(t),
            "status": "exact" if want.get(t) == got.get(t) else "MISMATCH",
        }
        for t in want
    ]
    res["audit_chain"] = chain
    res["audit_head_matches_manifest"] = (
        chain.get("head_seq") == m["logical"]["audit_head"]["seq"]
        and chain.get("head_hash") == m["logical"]["audit_head"]["hash"]
    )
    res["keycloak_users"] = keycloak_users("keycloak_logical")
    res["ok"] = (
        all(r["status"] == "exact" for r in res["counts"])
        and chain["ok"]
        and res["audit_head_matches_manifest"]
        and isinstance(res["age_vertices_via_cypher"], int)
        and res["cortex.dump"]["exit"] == 0
    )
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backup-id")
    ap.add_argument("--skip-logical", action="store_true")
    ap.add_argument("--no-switch", action="store_true", help="don't force a WAL switch (simulate an unannounced loss)")
    ap.add_argument("--keep", action="store_true", help="leave the scratch server running for inspection")
    ap.add_argument("--report", help="also write the JSON report here")
    ap.add_argument(
        "--target-time",
        help="point-in-time recovery, e.g. '2026-09-30 09:00:00+00' (counts are then "
        "reported, not compared: the live server has moved on)",
    )
    args = ap.parse_args()
    logical = not args.skip_logical
    c = minio_client()
    report: dict[str, Any] = {"drill_started_at": datetime.now(UTC).isoformat(), "scratch_container": DRILL}
    t_start = time.monotonic()

    log("live checkpoint: counts, WAL switch")
    cp = live_checkpoint(switch=not args.no_switch)
    report["live"] = {k: v for k, v in cp.items() if k not in ("t0", "t1")}
    if cp["switched_segment"]:
        report["live"]["ship_seconds"] = round(wait_shipped(c, cp["switched_segment"]), 1)
        log(f"segment {cp['switched_segment']} archived and in MinIO after {report['live']['ship_seconds']} s")
    t_disaster = time.monotonic()  # the drill treats this instant as the loss of the live server

    m = latest_backup(c, args.backup_id)
    report["backup"] = {
        "id": m["id"],
        "start_wal": m["base"]["start_wal"],
        "files": {k: v["bytes"] for k, v in m["files"].items()},
    }
    log(f"restoring backup {m['id']} (start WAL {m['base']['start_wal']})")
    try:
        with tempfile.TemporaryDirectory(prefix="cortex-drill-") as d:
            tmp = Path(d)
            dl = download(c, m, tmp, logical)
            report["download"] = {**dl, "seconds": round(time.monotonic() - t_disaster, 1)}
            log(f"downloaded + checksummed in {report['download']['seconds']} s ({dl['wal_segments']} WAL files)")
            if not all(f["ok"] for f in dl["files"].values()):
                raise SystemExit("checksum mismatch: " + dump_json(dl["files"]))
            start_scratch(tmp, logical, args.target_time)
        wait_promoted()
        rto = time.monotonic() - t_disaster
        log(f"scratch server promoted: RTO {rto:.1f} s")
        with pg_connect(DRILL_PORT) as conn, conn.cursor() as cur:
            cur.execute("SELECT pg_last_xact_replay_timestamp(), now()")
            last_replay, _now = cur.fetchone()
            restored = table_counts(cur)
            head = audit_head(cur)
            chain = verify_audit_chain(cur)
            h0 = cp["audit_head_t0"]
            cur.execute("SELECT hash FROM audit_log WHERE seq = %s", (h0["seq"],))
            r = cur.fetchone()
            head0_present = bool(r and r[0].strip() == h0["hash"])
            vertices = age_probe(conn)
        counts = compare(restored, cp["t0"], cp["t1"])
        kc = keycloak_users("keycloak")
        rto_verified = time.monotonic() - t_disaster
        if args.target_time:  # restored to an earlier point: equality with live counts is not expected
            for x in counts:
                x["status"] = "pitr"
            head0_present = True
        phys_ok = (
            all(x["status"] in ("exact", "window", "n/a", "pitr") for x in counts) and chain["ok"] and head0_present
        )
        report["physical"] = {
            "rto_seconds": round(rto, 1),
            "rto_incl_verification_seconds": round(rto_verified, 1),
            "last_replayed_xact": last_replay,
            "counts": counts,
            "audit_chain": chain,
            "audit_head_restored": head,
            "audit_head_t0_present_same_hash": head0_present,
            "age_vertices_via_cypher": vertices,
            "keycloak_users": kc,
            "ok": phys_ok and kc is not None and kc > 0,
        }
        if logical:
            log("logical restore of cortex.dump / keycloak.dump")
            report["logical"] = logical_restore(m)
    finally:
        if not args.keep:
            cleanup()
    total = time.monotonic() - t_start
    exposure = report["live"]["rpo_exposure_s"]
    report["summary"] = {
        "rto_seconds": report["physical"]["rto_seconds"],
        "rto_slo_seconds": RTO_SLO_S,
        "rpo_exposure_seconds_at_drill": round(exposure, 1) if exposure is not None else None,
        "rpo_bound_seconds": "archive_timeout 840 + wal-shipper 30 = 870",
        "rpo_slo_seconds": RPO_SLO_S,
        "physical_ok": report["physical"]["ok"],
        "logical_ok": report.get("logical", {}).get("ok") if logical else None,
        "drill_total_seconds": round(total, 1),
    }
    passed = (
        report["physical"]["ok"]
        and (not logical or report["logical"]["ok"])
        and report["physical"]["rto_seconds"] <= RTO_SLO_S
    )
    report["summary"]["result"] = "PASS" if passed else "FAIL"

    print("\n=== Restore drill report ===")
    print(
        f"backup            {m['id']}  (start WAL {m['base']['start_wal']}, {report['download']['wal_segments']} WAL files)"
    )
    print(
        f"RTO (physical)    {report['physical']['rto_seconds']} s  (SLO {RTO_SLO_S} s); with verification "
        f"{report['physical']['rto_incl_verification_seconds']} s"
    )
    print(
        f"RPO exposure      {report['summary']['rpo_exposure_seconds_at_drill']} s since last archived segment "
        f"(bound 870 s, SLO {RPO_SLO_S} s)"
    )
    print(
        f"audit chain       {chain['checked']} records, ok={chain['ok']}, head seq {head['seq']}, "
        f"T0 head present={head0_present}"
    )
    bad = [x for x in counts if x["status"] == "MISMATCH"]
    print(
        f"row counts        {len(counts)} tables: {sum(x['status'] == 'exact' for x in counts)} exact, "
        f"{sum(x['status'] == 'window' for x in counts)} within T0..T1, {len(bad)} mismatched"
        + (f" ({len(counts)} point-in-time, not compared)" if args.target_time else "")
    )
    for x in bad:
        print(f"   MISMATCH {x['table']}: live T0 {x['live_t0']} T1 {x['live_t1']} restored {x['restored']}")
    print(f"graph             {vertices} vertices via Cypher; keycloak users {kc}")
    if logical:
        lg = report["logical"]
        lbad = [x for x in lg["counts"] if x["status"] != "exact"]
        print(
            f"logical restore   {lg['seconds']} s, pg_restore exit {lg['cortex.dump']['exit']} "
            f"({lg['cortex.dump']['errors']} errors), counts {len(lg['counts']) - len(lbad)}/{len(lg['counts'])} exact, "
            f"chain ok={lg['audit_chain']['ok']}, graph {lg['age_vertices_via_cypher']}, ok={lg['ok']}"
        )
        for x in lbad:
            print(f"   MISMATCH {x['table']}: manifest {x['manifest']} restored {x['restored']}")
    print(
        f"RESULT            {report['summary']['result']}  (drill total {report['summary']['drill_total_seconds']} s)"
    )
    if args.report:
        Path(args.report).write_text(dump_json(report), encoding="utf-8")
        print(f"report written to {args.report}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
