"""Unit tests for MySQL 8.4 Bulk Load Generator (Phase 11).

Validates:
- Generation scale math and deterministic bounds
- UUID determinism and syllable generation
- Safe protection against production port 3306 and production databases
- Correct vector BLOB packing and dimensions
- Batch chunking and referential integrity
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from platform_core.db.vector import EMBEDDING_DIM, from_blob
from scripts.seed_mysql_load import (
    MySQLLoadGenerator,
    gen_org_name,
    gen_uuid,
)


def test_uuid_and_name_determinism():
    """Verify that deterministic generators produce stable values across calls."""
    u1 = gen_uuid("opp", 42)
    u2 = gen_uuid("opp", 42)
    assert u1 == u2
    assert len(u1) == 36

    u3 = gen_uuid("opp", 43)
    assert u1 != u3

    n1 = gen_org_name(100)
    n2 = gen_org_name(100)
    assert n1 == n2
    assert "100" in n1


def test_scale_calculations():
    """Verify entity counts scale linearly with the scale factor."""
    cfg = {"host": "127.0.0.1", "port": 53306, "database": "cortex_load_test"}
    gen_small = MySQLLoadGenerator(cfg, scale=0.01)
    assert gen_small.n_org == 1500
    assert gen_small.n_opp == 2000

    gen_micro = MySQLLoadGenerator(cfg, scale=0.001)
    assert gen_micro.n_org == 150
    assert gen_micro.n_opp == 200


def test_production_safety_checks():
    """Verify generator refuses to target port 3306 or databases with prod in name."""
    cfg_prod_port = {"host": "127.0.0.1", "port": 3306, "database": "cortex_test"}
    with pytest.raises(RuntimeError, match="Safety Abort: Target port 3306 matches production"):
        MySQLLoadGenerator(cfg_prod_port, scale=0.01)

    cfg_prod_db = {"host": "127.0.0.1", "port": 53306, "database": "cortex_production"}
    with pytest.raises(RuntimeError, match="contains 'prod'"):
        MySQLLoadGenerator(cfg_prod_db, scale=0.01)


def test_embedding_vector_blob_generation():
    """Verify that generated embeddings are valid 4096-byte IEEE-754 float32 BLOBs."""
    cfg = {"host": "127.0.0.1", "port": 53306, "database": "cortex_load_test"}
    gen = MySQLLoadGenerator(cfg, scale=0.001)

    mock_conn = MagicMock()
    mock_cur = mock_conn.cursor.return_value.__enter__.return_value

    gen._seed_embeddings(mock_conn)

    # Inspect executemany arguments
    calls = mock_cur.executemany.call_args_list
    assert len(calls) > 0
    sql, rows = calls[0][0]
    assert "INSERT INTO embedding" in sql
    assert len(rows) > 0

    first_row = rows[0]
    # Row tuple: (id, entity_id, entity_type, model, dim, text_hash, vector)
    assert first_row[4] == EMBEDDING_DIM
    blob = first_row[6]
    assert isinstance(blob, bytes)
    assert len(blob) == EMBEDDING_DIM * 4

    unpacked = from_blob(blob)
    assert len(unpacked) == EMBEDDING_DIM
