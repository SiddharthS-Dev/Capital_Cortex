"""MySQL 8.4 logical backups: encrypted, checksummed, off-host capable, never overwriting (CORTEX_MYSQL_CUTOVER_RUNBOOK).

Layout under the destination (a local/mounted directory or ``s3://bucket/prefix`` on an S3-compatible store)::

    <id>/<db>.sql.gz.enc     mysqldump of one database, gzip, then AES-256-GCM in 1 MiB authenticated frames
    <id>/manifest.json       written LAST: sha256 of ciphertext and plaintext, sizes, schema inventory, row counts

``<id>`` is the UTC start time (YYYYMMDDTHHMMSSZ). An existing id or object is never overwritten.

Subcommands::

    backup   [--databases cortex,keycloak] [--no-verify] [--allow-unencrypted]
    verify   --id ID                         re-read every file from the store, check both sha256s and the GCM tags
    restore  --id ID --database cortex --target-db NEW [--target-container C] [--strict-counts]
             verifies first, then streams into a NEW database (an existing one is refused) and compares the inventory
    prune    --keep N [--confirm]            dry run unless --confirm; only touches ids that carry this tool's manifest
    list

mysqldump/mysql run inside the server container (exact server version) with the container's own
MYSQL_ROOT_PASSWORD, so no password appears on the host command line. Configuration: MYSQL_BACKUP_* in .env
(see .env.example); secrets also accept <NAME>_FILE.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, Protocol

sys.path.insert(0, str(Path(__file__).parent))
from ops_common import ENV, ROOT, dump_json, log, setting
from secure_connect import read_secret

TOOL = "cortex-mysql-backup"
FORMAT_VERSION = 1
MAGIC = b"CXMYBK1\n"
FRAME = 1 << 20
_NAME = re.compile(r"^[A-Za-z0-9_]{1,64}$")
_ID = re.compile(r"^\d{8}T\d{6}Z$")
DUMP_FLAGS = (
    "--single-transaction --routines --triggers --events --hex-blob --set-gtid-purged=OFF --no-tablespaces "
    "--default-character-set=utf8mb4"
)


class BackupError(RuntimeError):
    pass


def check_name(name: str) -> str:
    if not _NAME.match(name):
        raise BackupError(f"invalid database name {name!r}")
    return name


# ------------------------------------------------------------------ encryption (AES-256-GCM, framed)


def load_key(env: dict[str, str] | None = None) -> bytes | None:
    raw = read_secret(("MYSQL_BACKUP_ENCRYPTION_KEY",), ENV if env is None else env)
    if not raw:
        return None
    key = base64.b64decode(raw, validate=True)
    if len(key) != 32:
        raise BackupError("MYSQL_BACKUP_ENCRYPTION_KEY must be 32 bytes, base64-encoded")
    return key


class Encryptor:
    """Streaming AES-256-GCM. Each frame: 4-byte length + ciphertext||tag; nonce = 8-byte random prefix + counter.

    The frame counter and a final flag are authenticated (AAD), so reordering, dropping or truncating frames fails.
    """

    def __init__(self, key: bytes, out: Any):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        self._aead = AESGCM(key)
        self._prefix = os.urandom(8)
        self._out = out
        self._buf = bytearray()
        self._n = 0
        out.write(MAGIC + self._prefix)

    def _frame(self, data: bytes, final: bool) -> None:
        nonce = self._prefix + struct.pack(">I", self._n)
        ct = self._aead.encrypt(nonce, data, MAGIC + struct.pack(">IB", self._n, final))
        self._out.write(struct.pack(">I", len(ct)) + ct)
        self._n += 1

    def write(self, data: bytes) -> None:
        self._buf += data
        while len(self._buf) >= FRAME:
            self._frame(bytes(self._buf[:FRAME]), False)
            del self._buf[:FRAME]

    def close(self) -> None:
        self._frame(bytes(self._buf), True)
        self._buf.clear()


def decrypt_stream(key: bytes, src: Any) -> Iterator[bytes]:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    head = src.read(len(MAGIC) + 8)
    if head[: len(MAGIC)] != MAGIC:
        raise BackupError("not an encrypted Cortex MySQL backup (bad header)")
    aead, prefix, n = AESGCM(key), head[len(MAGIC) :], 0
    while True:
        hdr = src.read(4)
        if len(hdr) < 4:
            raise BackupError("encrypted backup is truncated (no final frame)")
        (size,) = struct.unpack(">I", hdr)
        ct = src.read(size)
        if len(ct) != size:
            raise BackupError("encrypted backup is truncated")
        nonce = prefix + struct.pack(">I", n)
        for final in (False, True):
            try:
                pt = aead.decrypt(nonce, ct, MAGIC + struct.pack(">IB", n, final))
                break
            except InvalidTag:
                continue
        else:
            raise BackupError(f"frame {n} failed authentication (tampered, reordered or wrong key)")
        yield pt
        n += 1
        if final:
            if src.read(1):
                raise BackupError("data after the final frame")
            return


def plaintext_chunks(src: Any, key: bytes | None) -> Iterator[bytes]:
    """Decrypt (when keyed) and gunzip a stored dump, chunk by chunk."""
    gz = zlib.decompressobj(31)
    frames: Iterator[bytes] = decrypt_stream(key, src) if key else iter(lambda: src.read(FRAME), b"")
    for frame in frames:
        if out := gz.decompress(frame):
            yield out
    if tail := gz.flush():
        yield tail
    if not gz.eof:
        raise BackupError("compressed stream is truncated")


# ------------------------------------------------------------------ storage (never overwrites)


class Store(Protocol):
    def ids(self) -> list[str]: ...
    def exists(self, bid: str, name: str | None = None) -> bool: ...
    def put(self, bid: str, name: str, path: Path) -> None: ...
    def open(self, bid: str, name: str) -> IO[bytes]: ...
    def delete(self, bid: str) -> None: ...


class LocalStore:
    """A directory (local disk or a mounted, approved network share)."""

    def __init__(self, root: Path):
        self.root = root

    def ids(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and _ID.match(p.name))

    def exists(self, bid: str, name: str | None = None) -> bool:
        return (self.root / bid / name).exists() if name else (self.root / bid).exists()

    def put(self, bid: str, name: str, path: Path) -> None:
        dest = self.root / bid / name
        if dest.exists():
            raise BackupError(f"refusing to overwrite {dest}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        with path.open("rb") as s, tmp.open("xb") as d:  # "x": fail rather than overwrite
            shutil.copyfileobj(s, d, FRAME)
        tmp.rename(dest)  # Windows: rename never replaces an existing file

    def open(self, bid: str, name: str) -> IO[bytes]:
        return (self.root / bid / name).open("rb")

    def delete(self, bid: str) -> None:
        shutil.rmtree(self.root / bid)


class S3Store:
    """S3-compatible object store (MinIO, AWS S3, ...); TLS on by default."""

    def __init__(self, url: str, env: dict[str, str]):
        from minio import Minio

        bucket, _, prefix = url.removeprefix("s3://").partition("/")
        self.bucket, self.prefix = bucket, prefix.strip("/")
        endpoint = env.get("MYSQL_BACKUP_S3_ENDPOINT") or ""
        if not endpoint:
            raise BackupError("MYSQL_BACKUP_S3_ENDPOINT is required for an s3:// destination")
        self.client = Minio(
            endpoint,
            access_key=read_secret(("MYSQL_BACKUP_S3_ACCESS_KEY",), env),
            secret_key=read_secret(("MYSQL_BACKUP_S3_SECRET_KEY",), env),
            secure=env.get("MYSQL_BACKUP_S3_SECURE", "true").lower() != "false",
        )

    def _key(self, bid: str = "", name: str = "") -> str:
        return "/".join(p for p in (self.prefix, bid, name) if p)

    def ids(self) -> list[str]:
        base = self._key() + "/" if self.prefix else ""
        names = (o.object_name[len(base) :].strip("/") for o in self.client.list_objects(self.bucket, prefix=base))
        return sorted(n for n in names if _ID.match(n))

    def exists(self, bid: str, name: str | None = None) -> bool:
        if name is None:
            return any(True for _ in self.client.list_objects(self.bucket, prefix=self._key(bid) + "/"))
        try:
            self.client.stat_object(self.bucket, self._key(bid, name))
            return True
        except Exception:
            return False

    def put(self, bid: str, name: str, path: Path) -> None:
        if self.exists(bid, name):
            raise BackupError(f"refusing to overwrite s3://{self.bucket}/{self._key(bid, name)}")
        self.client.fput_object(self.bucket, self._key(bid, name), str(path))

    def open(self, bid: str, name: str) -> IO[bytes]:
        tmp = tempfile.TemporaryFile()
        resp = self.client.get_object(self.bucket, self._key(bid, name))
        try:
            shutil.copyfileobj(resp, tmp, FRAME)
        finally:
            resp.close()
            resp.release_conn()
        tmp.seek(0)
        return tmp  # type: ignore[return-value]

    def delete(self, bid: str) -> None:
        for o in self.client.list_objects(self.bucket, prefix=self._key(bid) + "/", recursive=True):
            self.client.remove_object(self.bucket, o.object_name)


def open_store(dest: str, env: dict[str, str] | None = None) -> Store:
    if not dest:
        raise BackupError("no destination: set MYSQL_BACKUP_DEST (directory or s3://bucket/prefix) or pass --dest")
    return S3Store(dest, ENV if env is None else env) if dest.startswith("s3://") else LocalStore(Path(dest))


# ------------------------------------------------------------------ server access (inside the container)


def _exec(container: str, script: str, *args: str, interactive: bool = False) -> list[str]:
    """`docker exec` a sh script that reads the root password from the container's own environment."""
    return ["docker", "exec", *(["-i"] if interactive else []), container, "sh", "-c", script, "sh", *args]


def mysql_query(container: str, sql: str) -> list[list[str]]:
    argv = _exec(container, 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -B -e "$1"', sql)
    p = subprocess.run(argv, cwd=ROOT, capture_output=True, check=False)
    if p.returncode != 0:
        raise BackupError(f"mysql query failed: {p.stderr.decode('utf-8', 'replace').strip()[-500:]}")
    return [line.split("\t") for line in p.stdout.decode("utf-8").splitlines() if line]


def inventory(container: str, db: str, counts: bool = True) -> dict[str, Any]:
    db = check_name(db)
    tables = [
        r[0]
        for r in mysql_query(
            container,
            f"SELECT table_name FROM information_schema.tables WHERE table_schema='{db}' AND table_type='BASE TABLE' ORDER BY 1",
        )
    ]
    inv: dict[str, Any] = {
        "tables": tables,
        "triggers": sorted(
            r[0]
            for r in mysql_query(
                container, f"SELECT trigger_name FROM information_schema.triggers WHERE trigger_schema='{db}'"
            )
        ),
        "routines": sorted(
            r[0]
            for r in mysql_query(
                container, f"SELECT routine_name FROM information_schema.routines WHERE routine_schema='{db}'"
            )
        ),
    }
    if counts and tables:
        union = " UNION ALL ".join(f"SELECT '{t}', COUNT(*) FROM `{db}`.`{t}`" for t in tables)
        inv["row_counts"] = {r[0]: int(r[1]) for r in mysql_query(container, union)}
    return inv


def database_exists(container: str, db: str) -> bool:
    return bool(
        mysql_query(container, f"SELECT 1 FROM information_schema.schemata WHERE schema_name='{check_name(db)}'")
    )


# ------------------------------------------------------------------ backup / verify / restore / prune


def dump_database(container: str, db: str, out: Path, key: bytes | None) -> dict[str, Any]:
    argv = _exec(container, f'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot {DUMP_FLAGS} "$1"', check_name(db))
    plain, cipher, n_plain, last = hashlib.sha256(), hashlib.sha256(), 0, b""
    gz = zlib.compressobj(6, zlib.DEFLATED, 31)

    class _HashingSink:
        def __init__(self, f: IO[bytes]):
            self.f = f

        def write(self, b: bytes) -> None:
            cipher.update(b)
            self.f.write(b)

    with out.open("xb") as raw, subprocess.Popen(argv, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE) as p:
        sink = _HashingSink(raw)
        enc = Encryptor(key, sink) if key else None
        emit: Callable[[bytes], None] = enc.write if enc else sink.write
        assert p.stdout is not None
        while chunk := p.stdout.read(FRAME):
            plain.update(chunk)
            n_plain += len(chunk)
            last = (last + chunk)[-4096:]
            emit(gz.compress(chunk))
        emit(gz.flush())
        if enc:
            enc.close()
        err = p.stderr.read().decode("utf-8", "replace") if p.stderr else ""
        rc = p.wait()
    if rc != 0 or b"-- Dump completed" not in last:
        out.unlink(missing_ok=True)
        raise BackupError(f"mysqldump {db} failed or is incomplete ({rc}): {err.strip()[-800:]}")
    return {
        "bytes": out.stat().st_size,
        "plaintext_bytes": n_plain,
        "sha256_ciphertext": cipher.hexdigest(),
        "sha256_plaintext": plain.hexdigest(),
    }


def read_manifest(store: Store, bid: str) -> dict[str, Any]:
    if not _ID.match(bid) or not store.exists(bid, "manifest.json"):
        raise BackupError(f"backup {bid} has no manifest (incomplete or not created by {TOOL})")
    with store.open(bid, "manifest.json") as f:
        m = json.loads(f.read())
    if m.get("tool") != TOOL:
        raise BackupError(f"backup {bid} was not created by {TOOL}")
    return m


def verify(store: Store, bid: str, key: bytes | None) -> dict[str, Any]:
    """Re-read every stored file: ciphertext sha256, GCM authentication of every frame, plaintext sha256."""
    m = read_manifest(store, bid)
    encrypted = m["encryption"] != "none"
    if encrypted and key is None:
        raise BackupError("backup is encrypted; MYSQL_BACKUP_ENCRYPTION_KEY is required")
    results: dict[str, str] = {}
    for db, info in m["files"].items():
        cipher, plain = hashlib.sha256(), hashlib.sha256()

        class _Tee:
            def __init__(self, f: IO[bytes]):
                self.f = f

            def read(self, n: int = -1) -> bytes:
                b = self.f.read(n)
                cipher.update(b)  # noqa: B023 - _Tee is used and discarded within this iteration
                return b

        try:
            with store.open(bid, info["name"]) as f:
                tee = _Tee(f)
                for chunk in plaintext_chunks(tee, key if encrypted else None):
                    plain.update(chunk)
                tee.read()
        except BackupError as e:
            results[db] = f"FAILED: {e}"
            continue
        ok = cipher.hexdigest() == info["sha256_ciphertext"] and plain.hexdigest() == info["sha256_plaintext"]
        results[db] = "OK" if ok else "CHECKSUM MISMATCH"
    return {"id": bid, "status": "PASS" if all(v == "OK" for v in results.values()) else "FAIL", "files": results}


def backup(args: argparse.Namespace, store: Store, key: bytes | None) -> dict[str, Any]:
    if key is None and not args.allow_unencrypted:
        raise BackupError("encryption key missing: set MYSQL_BACKUP_ENCRYPTION_KEY(_FILE) or pass --allow-unencrypted")
    bid = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    if store.exists(bid):
        raise BackupError(f"backup id {bid} already exists; refusing to overwrite")
    dbs = [check_name(d.strip()) for d in args.databases.split(",") if d.strip()]
    manifest: dict[str, Any] = {
        "tool": TOOL,
        "version": FORMAT_VERSION,
        "id": bid,
        "created_utc": datetime.now(UTC).isoformat(),
        "source": {
            "container": args.container,
            "server_version": mysql_query(args.container, "SELECT @@version")[0][0],
        },
        "encryption": "aes-256-gcm-framed-v1" if key else "none",
        "dump_flags": DUMP_FLAGS,
        "files": {},
    }
    with tempfile.TemporaryDirectory(prefix="cortex-mysql-backup-") as d:
        for db in dbs:
            inv = inventory(args.container, db, counts=not args.skip_counts)
            name = f"{db}.sql.gz.enc" if key else f"{db}.sql.gz"
            log(f"dump {db} ({len(inv['tables'])} tables, {len(inv['triggers'])} triggers)")
            info = dump_database(args.container, db, Path(d) / name, key)
            store.put(bid, name, Path(d) / name)
            manifest["files"][db] = {"name": name, **info, "inventory": inv}
            log(f"stored {bid}/{name} ({info['bytes'] / 1e6:.1f} MB, sha256 {info['sha256_ciphertext'][:12]}...)")
        mpath = Path(d) / "manifest.json"
        mpath.write_text(dump_json(manifest), encoding="utf-8")
        store.put(bid, "manifest.json", mpath)  # last: a backup without a manifest is incomplete and never used
    result: dict[str, Any] = {
        "id": bid,
        "encryption": manifest["encryption"],
        "files": {db: f["bytes"] for db, f in manifest["files"].items()},
    }
    if not args.no_verify:
        result["verify"] = verify(store, bid, key)
    return result


def restore(args: argparse.Namespace, store: Store, key: bytes | None) -> dict[str, Any]:
    m = read_manifest(store, args.id)
    info = m["files"].get(args.database)
    if info is None:
        raise BackupError(f"backup {args.id} has no database {args.database!r} (has {sorted(m['files'])})")
    target, container = check_name(args.target_db), args.target_container or args.container
    if database_exists(container, target):
        raise BackupError(f"target database {target} already exists on {container}; restore only into a new database")
    v = verify(store, args.id, key)  # pass 1: every byte authenticated and checksummed before anything is written
    if v["files"][args.database] != "OK":
        raise BackupError(f"verification failed, nothing restored: {v}")
    mysql_query(container, f"CREATE DATABASE `{target}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
    log(f"restore {args.id}/{info['name']} -> {container}:{target}")
    argv = _exec(
        container,
        'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot --default-character-set=utf8mb4 "$1"',
        target,
        interactive=True,
    )
    encrypted = m["encryption"] != "none"
    with (
        store.open(args.id, info["name"]) as f,
        subprocess.Popen(argv, cwd=ROOT, stdin=subprocess.PIPE, stderr=subprocess.PIPE) as p,
    ):
        assert p.stdin is not None
        for chunk in plaintext_chunks(f, key if encrypted else None):  # pass 2: streamed, no plaintext on disk
            p.stdin.write(chunk)
        p.stdin.close()
        err = p.stderr.read().decode("utf-8", "replace") if p.stderr else ""
        rc = p.wait()
    if rc != 0:
        raise BackupError(f"restore into {target} failed ({rc}): {err.strip()[-800:]} ({target} left for inspection)")
    expected = info["inventory"]
    got = inventory(container, target, counts="row_counts" in expected)
    problems = [f"{k} differ" for k in ("tables", "triggers", "routines") if expected[k] != got[k]]
    drift = {
        t: [n, got.get("row_counts", {}).get(t)]
        for t, n in expected.get("row_counts", {}).items()
        if got.get("row_counts", {}).get(t) != n
    }
    if drift and args.strict_counts:
        problems.append(f"row counts differ: {drift}")
    return {
        "id": args.id,
        "database": args.database,
        "target": f"{container}:{target}",
        "status": "PASS" if not problems else "FAIL",
        "problems": problems,
        "tables": len(got["tables"]),
        "triggers": len(got["triggers"]),
        "rows": sum(got.get("row_counts", {}).values()),
        # Counts are read just before the dump, outside its snapshot: on a busy server they can drift legitimately.
        "row_count_drift": drift,
    }


def prune(store: Store, keep: int, confirm: bool) -> dict[str, Any]:
    """Retention. Dry run unless confirm; ids without this tool's manifest (incomplete, foreign) are never touched."""
    if keep < 1:
        raise BackupError("--keep must be at least 1")
    own = []
    for bid in store.ids():
        try:
            read_manifest(store, bid)
        except BackupError:
            continue
        own.append(bid)
    doomed = own[:-keep] if len(own) > keep else []
    if confirm:
        for bid in doomed:
            store.delete(bid)
            log(f"deleted {bid}")
    return {"kept": own[-keep:], "deleted" if confirm else "would_delete": doomed, "dry_run": not confirm}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Cortex MySQL backup / verify / restore / prune")
    ap.add_argument("command", choices=["backup", "verify", "restore", "prune", "list"])
    ap.add_argument("--dest", default=setting("MYSQL_BACKUP_DEST", ""))
    ap.add_argument("--container", default=setting("MYSQL_BACKUP_CONTAINER", "capital-cortex-mysql"))
    ap.add_argument("--databases", default=setting("MYSQL_BACKUP_DATABASES", "cortex,keycloak"))
    ap.add_argument("--allow-unencrypted", action="store_true", help="local development only")
    ap.add_argument("--no-verify", action="store_true")
    ap.add_argument("--skip-counts", action="store_true", help="no exact row counts in the manifest (very large DBs)")
    ap.add_argument("--id")
    ap.add_argument("--database")
    ap.add_argument("--target-db")
    ap.add_argument("--target-container", help="restore into another (isolated) server container")
    ap.add_argument("--strict-counts", action="store_true", help="fail the restore on any row-count difference")
    ap.add_argument("--keep", type=int, default=int(setting("MYSQL_BACKUP_KEEP", "14")))
    ap.add_argument("--confirm", action="store_true", help="prune: actually delete (default is a dry run)")
    ap.add_argument("--report", help="also write the JSON result here")
    args = ap.parse_args(argv)
    if args.command == "restore" and not (args.id and args.database and args.target_db):
        ap.error("restore needs --id, --database and --target-db")
    try:
        store, key = open_store(args.dest), load_key()
        if args.command == "backup":
            result = backup(args, store, key)
        elif args.command == "verify":
            ids = store.ids()
            result = verify(store, args.id or (ids[-1] if ids else ""), key)
        elif args.command == "restore":
            result = restore(args, store, key)
        elif args.command == "prune":
            result = prune(store, args.keep, args.confirm)
        else:
            result = {"ids": store.ids()}
    except BackupError as e:
        log(f"ERROR: {e}")
        return 1
    print(dump_json(result))
    if args.report:
        Path(args.report).write_text(dump_json(result), encoding="utf-8")
    statuses = [result.get("status", "PASS"), result.get("verify", {}).get("status", "PASS")]
    return 0 if all(s == "PASS" for s in statuses) else 1


if __name__ == "__main__":
    sys.exit(main())
