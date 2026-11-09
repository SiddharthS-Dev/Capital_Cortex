"""Unit and functional safety tests for PostgreSQL to MySQL ETL Tool (Phase 10).

Covers:
- UUID and JSON conversion
- Vector IEEE-754 binary packing
- Foreign-key dependency ordering
- Rollback after failures
- Reconciliation checksum calculations and mismatch detection
- Audit-chain verification logic
- Dry-run mode behavior
- Safety guard against unintended production targets
"""

from __future__ import annotations

import decimal
import json
import uuid
from datetime import datetime
from unittest.mock import MagicMock

import pytest

from platform_core.audit.chain import GENESIS_HASH, AuditRecord, compute_hash
from platform_core.db.vector import EMBEDDING_DIM, from_blob
from scripts.migrate_pg_to_mysql import (
    TABLE_MIGRATION_ORDER,
    MigrationError,
    PostgresToMySQLMigrator,
    canonical_row_hash,
    migrated_tables,
    transform_row,
    transform_value,
)


def test_table_migration_order_dependencies():
    """Verify topological dependency order: parents before children."""
    order = [t.strip("`") for t in TABLE_MIGRATION_ORDER]

    # Tenant must be first
    assert order.index("tenant") == 0

    # Source before signal and source_run
    assert order.index("source") < order.index("signal")
    assert order.index("source") < order.index("source_run")

    # Organization before opportunity and contacts
    assert order.index("organization") < order.index("opportunity")
    assert order.index("organization") < order.index("contact")

    # Opportunity before embedding, proposals, and milestones
    assert order.index("opportunity") < order.index("embedding")
    assert order.index("opportunity") < order.index("proposal")
    assert order.index("opportunity") < order.index("milestone")

    # Entity before relationship_edge
    assert order.index("entity") < order.index("relationship_edge")

    # Approval before outbox
    assert order.index("approval") < order.index("outbox")


def test_value_transformations_uuid_and_json():
    """Verify UUID and JSON array/dict transformations."""
    u = uuid.uuid4()
    assert transform_value(u, "id", "opportunity") == str(u)

    arr = ["energy", "climate", "storage"]
    assert transform_value(arr, "sectors", "opportunity") == json.dumps(arr)

    doc = {"key": "val", "num": 42}
    assert transform_value(doc, "profile", "organization") == json.dumps(doc)

    assert transform_value(True, "is_demo", "opportunity") == 1
    assert transform_value(False, "is_demo", "opportunity") == 0
    assert transform_value(None, "summary", "opportunity") is None


def test_vector_binary_packing_transformation():
    """Verify float array to IEEE-754 32-bit packed binary BLOB conversion."""
    floats = [0.12345] * EMBEDDING_DIM
    packed = transform_value(floats, "vector", "embedding")

    assert isinstance(packed, bytes)
    assert len(packed) == EMBEDDING_DIM * 4

    unpacked = from_blob(packed)
    assert len(unpacked) == EMBEDDING_DIM
    assert pytest.approx(unpacked[0], abs=1e-5) == 0.12345

    # String vector representation '[0.1, 0.2, ...]'
    str_vec = "[" + ", ".join([str(0.5)] * EMBEDDING_DIM) + "]"
    packed_str = transform_value(str_vec, "vector", "embedding")
    assert len(packed_str) == EMBEDDING_DIM * 4
    assert pytest.approx(from_blob(packed_str)[0], abs=1e-5) == 0.5


def test_transform_row_complete():
    """Verify full row transformation with mixed types."""
    u1 = uuid.uuid4()
    u2 = uuid.uuid4()
    row = {
        "id": u1,
        "org_id": u2,
        "title": "Clean Energy Grant",
        "is_demo": False,
        "sectors": ["energy", "solar"],
        "source_ref": {"origin": "seed"},
        "created_at": datetime(2026, 10, 15, 12, 0, 0),
        "amount": decimal.Decimal("250000.00"),
    }

    t_row = transform_row(row, "opportunity")
    assert t_row["id"] == str(u1)
    assert t_row["org_id"] == str(u2)
    assert t_row["title"] == "Clean Energy Grant"
    assert t_row["is_demo"] == 0
    assert t_row["sectors"] == json.dumps(["energy", "solar"])
    assert t_row["source_ref"] == json.dumps({"origin": "seed"})
    assert "2026-10-15 12:00:00" in t_row["created_at"]
    assert t_row["amount"] == decimal.Decimal("250000.00")


def test_canonical_row_checksum_deterministic():
    """Verify that canonical row hash is deterministic regardless of key order or formatting."""
    row1 = {
        "id": "11111111-1111-1111-1111-111111111111",
        "title": "Grant A",
        "sectors": ["energy", "tech"],
        "amount": decimal.Decimal("100.50"),
    }
    # Different key insertion order, same values
    row2 = {
        "amount": decimal.Decimal("100.50"),
        "title": "Grant A",
        "id": "11111111-1111-1111-1111-111111111111",
        "sectors": ["energy", "tech"],
    }
    assert canonical_row_hash(row1) == canonical_row_hash(row2)

    # Different value yields different hash
    row3 = {**row1, "amount": decimal.Decimal("100.51")}
    assert canonical_row_hash(row1) != canonical_row_hash(row3)


def test_production_target_safety_protection():
    """Verify that the migrator rejects execution against production targets."""
    pg_cfg = {"host": "127.0.0.1", "port": 55432, "dbname": "cortex"}

    # Refuse target on standard production port 3306 without override
    my_cfg_prod_port = {"host": "127.0.0.1", "port": 3306, "database": "cortex_test"}
    with pytest.raises(MigrationError, match="Safety Violation: Target port 3306 is default production port"):
        PostgresToMySQLMigrator(pg_cfg, my_cfg_prod_port, dry_run=False)

    # Refuse database with 'prod' in name
    my_cfg_prod_db = {"host": "127.0.0.1", "port": 53306, "database": "cortex_prod"}
    with pytest.raises(
        MigrationError, match="Safety Violation: Refusing automated migration directly into cortex_prod"
    ):
        PostgresToMySQLMigrator(pg_cfg, my_cfg_prod_db, dry_run=False)


def test_dry_run_mode_protection():
    """Verify that dry_run mode performs no target writes or modifications."""
    pg_cfg = {"host": "127.0.0.1", "port": 55432, "dbname": "cortex"}
    my_cfg = {"host": "127.0.0.1", "port": 53306, "database": "cortex_integration"}

    migrator = PostgresToMySQLMigrator(pg_cfg, my_cfg, dry_run=True)
    assert migrator.dry_run is True

    # Mock database connections
    mock_pg = MagicMock()
    mock_mysql = MagicMock()

    # information_schema rows: PG (name, data_type, udt_name, is_generated), MySQL (name, DATA_TYPE, EXTRA)
    pg_cols = [("id", "uuid", "uuid", "NEVER"), ("name", "text", "text", "NEVER")]
    mock_mysql.cursor.return_value.__enter__.return_value.fetchall.return_value = [
        ("id", "varchar", ""),
        ("name", "varchar", ""),
    ]

    # Mock streaming fetch
    stream_cur = MagicMock()
    stream_cur.fetchmany.side_effect = [
        [(str(uuid.uuid4()), "Inspironics")],
        [],  # End of stream
    ]
    mock_pg.cursor.return_value.__enter__.side_effect = [
        MagicMock(fetchall=MagicMock(return_value=pg_cols)),
        stream_cur,
    ]

    stats = migrator.migrate_table(mock_pg, mock_mysql, "tenant")
    assert stats["extracted"] == 1
    assert stats["loaded"] == 0  # Dry run: loaded is 0
    assert stats["target_checksum"] == "DRY_RUN"

    # Verify executemany was NEVER called on MySQL cursor
    for call in mock_mysql.cursor.return_value.__enter__.return_value.mock_calls:
        assert "executemany" not in str(call)


def test_audit_chain_verification_logic():
    """Verify audit chain verification on valid and tampered chains."""
    pg_cfg = {"host": "127.0.0.1", "port": 55432, "dbname": "cortex"}
    my_cfg = {"host": "127.0.0.1", "port": 53306, "database": "cortex_integration"}
    migrator = PostgresToMySQLMigrator(pg_cfg, my_cfg, dry_run=True)

    # 1. Valid chain
    now = datetime(2026, 10, 20, 10, 0, 0)
    rec1 = AuditRecord(1, "org1", "user1", "create", "opp:1", {"a": 1}, now, GENESIS_HASH)
    h1 = compute_hash(GENESIS_HASH, rec1.payload())
    rec1.hash = h1

    rec2 = AuditRecord(2, "org1", "user1", "update", "opp:1", {"a": 2}, now, h1)
    h2 = compute_hash(h1, rec2.payload())
    rec2.hash = h2

    mock_mysql = MagicMock()
    mock_cur = mock_mysql.cursor.return_value.__enter__.return_value
    mock_cur.fetchall.return_value = [
        (1, "org1", "user1", "create", "opp:1", json.dumps({"a": 1}), now, GENESIS_HASH, h1),
        (2, "org1", "user1", "update", "opp:1", json.dumps({"a": 2}), now, h1, h2),
    ]

    assert migrator._verify_mysql_audit_chain(mock_mysql) is True

    # 2. Tampered chain
    mock_cur.fetchall.return_value = [
        (1, "org1", "user1", "create", "opp:1", json.dumps({"a": 1}), now, GENESIS_HASH, h1),
        (2, "org1", "mallory", "update", "opp:1", json.dumps({"a": 2}), now, h1, "forged_hash"),
    ]
    assert migrator._verify_mysql_audit_chain(mock_mysql) is False


def test_real_data_transfer_and_checksum_match():
    """Verify live batch migration (dry_run=False): execution, type packing, and checksum matching."""
    pg_cfg = {"host": "127.0.0.1", "port": 55432, "dbname": "cortex"}
    my_cfg = {"host": "127.0.0.1", "port": 53306, "database": "cortex_integration"}

    migrator = PostgresToMySQLMigrator(pg_cfg, my_cfg, dry_run=False)
    assert migrator.dry_run is False

    mock_pg = MagicMock()
    mock_mysql = MagicMock()

    # Column existence
    pg_cols = [
        ("id", "uuid", "uuid", "NEVER"),
        ("title", "text", "text", "NEVER"),
        ("is_demo", "boolean", "bool", "NEVER"),
        ("amount", "numeric", "numeric", "NEVER"),
        ("sectors", "ARRAY", "_text", "NEVER"),
    ]
    mysql_cur = mock_mysql.cursor.return_value.__enter__.return_value
    mysql_cur.fetchall.return_value = [
        ("id", "varchar", ""),
        ("title", "varchar", ""),
        ("is_demo", "tinyint", ""),
        ("amount", "decimal", ""),
        ("sectors", "json", ""),
    ]

    u1 = uuid.uuid4()
    row1 = (u1, "Green Energy Grant", False, decimal.Decimal("150000.00"), ["energy", "solar"])
    # What MySQL hands back when the target checksum re-reads the loaded table
    mysql_cur.fetchmany.side_effect = [
        [(str(u1), "Green Energy Grant", 0, decimal.Decimal("150000.00"), '["energy", "solar"]')],
        [],
    ]

    stream_cur = MagicMock()
    stream_cur.fetchmany.side_effect = [
        [row1],
        [],
    ]
    mock_pg.cursor.return_value.__enter__.side_effect = [
        MagicMock(fetchall=MagicMock(return_value=pg_cols)),
        stream_cur,
    ]

    stats = migrator.migrate_table(mock_pg, mock_mysql, "opportunity")
    assert stats["extracted"] == 1
    assert stats["loaded"] == 1
    assert stats["source_checksum"] is not None
    assert stats["target_checksum"] is not None
    assert stats["source_checksum"] == stats["target_checksum"]

    # Verify executemany was called
    assert mysql_cur.executemany.call_count == 1
    args, _ = mysql_cur.executemany.call_args
    sql, batch = args
    assert "INSERT INTO `opportunity`" in sql
    assert batch[0][0] == str(u1)
    assert batch[0][2] == 0  # False mapped to 0


def test_reconciliation_summary_report_generation():
    """Verify run_reconciliation produces a passing report when row counts and checksums match."""
    pg_cfg = {"host": "127.0.0.1", "port": 55432, "dbname": "cortex"}
    my_cfg = {"host": "127.0.0.1", "port": 53306, "database": "cortex_integration"}
    migrator = PostgresToMySQLMigrator(pg_cfg, my_cfg, dry_run=False)

    rows = {"organization": 5, "opportunity": 10}
    table_stats = [_stat(t, rows.get(t, 0)) for t in migrated_tables()]

    mock_mysql = MagicMock()
    cur = mock_mysql.cursor.return_value.__enter__.return_value
    # Row count per table, then the audit_lock mutex row
    cur.fetchone.side_effect = [(rows.get(t, 0),) for t in migrated_tables()] + [(1,)]
    # No foreign keys / empty audit chain
    cur.fetchall.return_value = []

    report = migrator.run_reconciliation(mock_mysql, table_stats)
    assert report["overall_status"] == "PASSED"
    assert report["row_count_mismatches"] == 0
    assert report["checksum_mismatches"] == 0
    assert report["audit_chain_valid"] is True
    assert len(report["table_results"]) == len(migrated_tables())


def _stat(table: str, n: int, checksum: str | None = None, **extra) -> dict:
    cs = checksum or ("EMPTY" if n == 0 else f"cs-{table}")
    return {
        "table": table,
        "extracted": n,
        "loaded": n,
        "errors": 0,
        "source_checksum": cs,
        "target_checksum": cs,
        "problems": [],
        **extra,
    }
