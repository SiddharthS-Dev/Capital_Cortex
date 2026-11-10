"""scripts/backup_mysql.py without a server: encryption, tamper detection, no-overwrite storage, retention, manifests.

The real dump/restore against MySQL 8.4 is exercised by the isolated drill recorded in the readiness report.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import struct
import sys
from pathlib import Path

import pytest

from scripts import backup_mysql as bm

KEY = os.urandom(32)


def _encrypt(data: bytes, key: bytes = KEY) -> bytes:
    buf = io.BytesIO()
    enc = bm.Encryptor(key, buf)
    enc.write(data)
    enc.close()
    return buf.getvalue()


def _decrypt(blob: bytes, key: bytes = KEY) -> bytes:
    return b"".join(bm.decrypt_stream(key, io.BytesIO(blob)))


@pytest.mark.parametrize("size", [0, 1, bm.FRAME - 1, bm.FRAME, 2 * bm.FRAME + 17])
def test_encrypt_roundtrip_across_frame_boundaries(size):
    data = os.urandom(size)
    blob = _encrypt(data)
    assert blob.startswith(bm.MAGIC)
    assert _decrypt(blob) == data


def test_ciphertext_does_not_contain_plaintext():
    data = b"INSERT INTO contact VALUES ('alice@example.com');\n" * 1000
    assert b"alice@example.com" not in _encrypt(data)


def _frames(blob: bytes) -> tuple[bytes, list[bytes]]:
    head, rest, frames = blob[: len(bm.MAGIC) + 8], blob[len(bm.MAGIC) + 8 :], []
    while rest:
        (n,) = struct.unpack(">I", rest[:4])
        frames.append(rest[: 4 + n])
        rest = rest[4 + n :]
    return head, frames


@pytest.mark.parametrize(
    "case", ["bit flip", "final frame dropped", "frames reordered", "trailing data", "cut mid-frame"]
)
def test_tampering_is_detected(case):
    blob = _encrypt(os.urandom(2 * bm.FRAME + 5))
    head, frames = _frames(blob)
    assert len(frames) == 3
    flipped = bytearray(blob)
    flipped[len(head) + 10] ^= 1
    bad = {
        "bit flip": bytes(flipped),
        "final frame dropped": head + frames[0] + frames[1],
        "frames reordered": head + frames[1] + frames[0] + frames[2],
        "trailing data": blob + b"x",
        "cut mid-frame": blob[:-5],
    }[case]
    with pytest.raises(bm.BackupError):
        _decrypt(bad)


def test_wrong_key_fails():
    with pytest.raises(bm.BackupError, match="authentication"):
        _decrypt(_encrypt(b"secret rows"), os.urandom(32))


def test_load_key_validates_length(tmp_path: Path):
    assert bm.load_key({}) is None
    assert bm.load_key({"MYSQL_BACKUP_ENCRYPTION_KEY": base64.b64encode(KEY).decode()}) == KEY
    f = tmp_path / "k"
    f.write_text(base64.b64encode(KEY).decode(), encoding="utf-8")
    assert bm.load_key({"MYSQL_BACKUP_ENCRYPTION_KEY_FILE": str(f)}) == KEY
    with pytest.raises(bm.BackupError, match="32 bytes"):
        bm.load_key({"MYSQL_BACKUP_ENCRYPTION_KEY": base64.b64encode(b"short").decode()})


def test_local_store_never_overwrites(tmp_path: Path):
    store = bm.LocalStore(tmp_path / "dest")
    src = tmp_path / "f"
    src.write_bytes(b"one")
    store.put("20261102T000000Z", "a.sql.gz.enc", src)
    src.write_bytes(b"two")
    with pytest.raises(bm.BackupError, match="overwrite"):
        store.put("20261102T000000Z", "a.sql.gz.enc", src)
    assert store.open("20261102T000000Z", "a.sql.gz.enc").read() == b"one"


@pytest.mark.parametrize("name", ["cortex; DROP", "a b", "x`y", "", "a" * 65])
def test_database_names_are_validated(name):
    with pytest.raises(bm.BackupError):
        bm.check_name(name)


# ---------------------------------------------------------------- end to end with a stand-in mysqldump

DUMP = (
    b"-- MySQL dump\nCREATE TABLE t (id INT);\nINSERT INTO t VALUES (1),(2);\n" * 5000
    + b"-- Dump completed on 2026-11-02\n"
)


@pytest.fixture
def fake_server(monkeypatch, tmp_path: Path):
    dump_file = tmp_path / "dump.sql"
    dump_file.write_bytes(DUMP)
    cat = [
        sys.executable,
        "-c",
        f"import sys,shutil; shutil.copyfileobj(open({str(dump_file)!r},'rb'), sys.stdout.buffer)",
    ]
    monkeypatch.setattr(bm, "_exec", lambda *a, **k: cat)
    monkeypatch.setattr(bm, "mysql_query", lambda c, sql: [["8.4.13"]])
    inv = {"tables": ["t"], "triggers": ["trg"], "routines": [], "row_counts": {"t": 2}}
    monkeypatch.setattr(bm, "inventory", lambda c, db, counts=True: dict(inv))
    return dump_file


def _args(**kw) -> argparse.Namespace:
    base = {
        "container": "c",
        "databases": "cortex,keycloak",
        "allow_unencrypted": False,
        "no_verify": False,
        "skip_counts": False,
    }
    return argparse.Namespace(**{**base, **kw})


def test_backup_writes_encrypted_files_and_manifest_last_then_verifies(fake_server, tmp_path: Path):
    store = bm.LocalStore(tmp_path / "dest")
    order: list[str] = []
    real_put = store.put

    def put(bid, name, path):
        order.append(name)
        real_put(bid, name, path)

    store.put = put  # type: ignore[method-assign]
    res = bm.backup(_args(), store, KEY)
    assert order == ["cortex.sql.gz.enc", "keycloak.sql.gz.enc", "manifest.json"]
    assert res["verify"]["status"] == "PASS" and res["encryption"] == "aes-256-gcm-framed-v1"
    stored = (tmp_path / "dest" / res["id"] / "cortex.sql.gz.enc").read_bytes()
    assert b"CREATE TABLE" not in stored and b"INSERT INTO" not in stored
    m = json.loads((tmp_path / "dest" / res["id"] / "manifest.json").read_text(encoding="utf-8"))
    assert m["tool"] == bm.TOOL and m["files"]["cortex"]["plaintext_bytes"] == len(DUMP)
    assert all(flag in m["dump_flags"] for flag in ("--hex-blob", "--triggers", "--routines", "--single-transaction"))


def test_backup_requires_key_unless_explicitly_unencrypted(fake_server, tmp_path: Path):
    store = bm.LocalStore(tmp_path / "dest")
    with pytest.raises(bm.BackupError, match="encryption key missing"):
        bm.backup(_args(), store, None)
    res = bm.backup(_args(allow_unencrypted=True, databases="cortex"), store, None)
    assert res["verify"]["status"] == "PASS" and res["encryption"] == "none"


def test_verify_detects_a_corrupted_stored_file(fake_server, tmp_path: Path):
    store = bm.LocalStore(tmp_path / "dest")
    res = bm.backup(_args(databases="cortex"), store, KEY)
    f = tmp_path / "dest" / res["id"] / "cortex.sql.gz.enc"
    data = bytearray(f.read_bytes())
    data[100] ^= 0xFF
    f.write_bytes(bytes(data))
    v = bm.verify(store, res["id"], KEY)
    assert v["status"] == "FAIL" and v["files"]["cortex"].startswith("FAILED")


def test_incomplete_dump_is_rejected(fake_server, tmp_path: Path):
    fake_server.write_bytes(b"-- MySQL dump\nCREATE TABLE t (id INT);\n")  # no completion marker: the dump died
    with pytest.raises(bm.BackupError, match="incomplete"):
        bm.backup(_args(databases="cortex"), bm.LocalStore(tmp_path / "dest"), KEY)


def test_restore_refuses_an_existing_target(fake_server, monkeypatch, tmp_path: Path):
    store = bm.LocalStore(tmp_path / "dest")
    res = bm.backup(_args(databases="cortex"), store, KEY)
    monkeypatch.setattr(bm, "database_exists", lambda c, db: True)
    args = argparse.Namespace(
        id=res["id"], database="cortex", target_db="cortex", target_container=None, container="c", strict_counts=False
    )
    with pytest.raises(bm.BackupError, match="already exists"):
        bm.restore(args, store, KEY)


def test_prune_is_dry_run_by_default_and_skips_foreign_or_incomplete(tmp_path: Path):
    root = tmp_path / "dest"
    for bid, tool in [
        ("20261101T000000Z", bm.TOOL),
        ("20261102T000000Z", bm.TOOL),
        ("20261103T000000Z", bm.TOOL),
        ("20261031T000000Z", "someone-else"),
    ]:
        (root / bid).mkdir(parents=True)
        (root / bid / "manifest.json").write_text(json.dumps({"tool": tool}), encoding="utf-8")
    (root / "20260101T000000Z").mkdir()  # incomplete: no manifest
    store = bm.LocalStore(root)
    dry = bm.prune(store, keep=1, confirm=False)
    assert dry["dry_run"] and dry["would_delete"] == ["20261101T000000Z", "20261102T000000Z"]
    assert len(list(root.iterdir())) == 5
    done = bm.prune(store, keep=1, confirm=True)
    assert done["deleted"] == ["20261101T000000Z", "20261102T000000Z"]
    assert sorted(p.name for p in root.iterdir()) == ["20260101T000000Z", "20261031T000000Z", "20261103T000000Z"]
    with pytest.raises(bm.BackupError):
        bm.prune(store, keep=0, confirm=True)


def test_no_password_in_server_command_lines():
    argv = bm._exec("capital-cortex-mysql", 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysqldump -uroot "$1"', "cortex")
    assert argv[:3] == ["docker", "exec", "capital-cortex-mysql"]
    assert not any(a.startswith("-p") or "--password" in a for a in argv)
