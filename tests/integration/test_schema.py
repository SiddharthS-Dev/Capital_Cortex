"""Schema-level invariants on the real custom Postgres image (AGE + pgvector) or MySQL 8.4.

Run: pytest -m integration
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError

from platform_core.audit import append, verify_chain
from platform_core.db import age

pytestmark = pytest.mark.integration

IMAGE = os.environ.get("CORTEX_PG_IMAGE", "capital-cortex/postgres:16-age1.5.0-pgvector0.8.0")
ROOT = Path(__file__).resolve().parents[2]
ORG = "00000000-0000-0000-0000-000000000001"
SRC = json.dumps({"kind": "test", "id": "t1"})


def _casts(c):
    is_my = c.dialect.name == "mysql"
    return {
        "empty_obj": "CAST('{}' AS JSON)" if is_my else "'{}'::jsonb",
        "empty_arr": "CAST('[]' AS JSON)" if is_my else "'[]'::jsonb",
        "json_type": "JSON" if is_my else "jsonb",
    }


async def test_i1_provenance_check(engine):
    async with engine.begin() as c:
        casts = _casts(c)
        with pytest.raises((IntegrityError, OperationalError)):
            async with c.begin_nested():
                await c.execute(text("INSERT INTO organization (name, kind) VALUES ('NoSource', 'counterparty')"))
        with pytest.raises((IntegrityError, OperationalError)):
            async with c.begin_nested():
                await c.execute(
                    text(
                        f"INSERT INTO organization (name, kind, source_ref) "
                        f"VALUES ('EmptySource', 'counterparty', {casts['empty_obj']})"
                    )
                )
        await c.execute(
            text(
                f"INSERT INTO organization (name, kind, source_ref) "
                f"VALUES ('Sourced', 'counterparty', CAST(:s AS {casts['json_type']}))"
            ),
            {"s": SRC},
        )


async def test_i1_inference_path(engine):
    async with engine.begin() as c:
        casts = _casts(c)
        with pytest.raises((IntegrityError, OperationalError)):  # an inference must name its basis
            async with c.begin_nested():
                await c.execute(
                    text(
                        f"INSERT INTO inference (method, produced_by, basis_refs) VALUES ('rule', 'test', {casts['empty_arr']})"
                    )
                )
        inf_id = str(uuid.uuid4())
        await c.execute(
            text(
                f"INSERT INTO inference (id, method, produced_by, basis_refs) "
                f"VALUES (:id, 'rule', 'test', CAST(:b AS {casts['json_type']}))"
            ),
            {"id": inf_id, "b": json.dumps([{"signal": "s1"}])},
        )
        await c.execute(
            text("INSERT INTO organization (name, kind, inference_id) VALUES ('Inferred', 'counterparty', :i)"),
            {"i": inf_id},
        )


async def test_i2_recommendation_needs_evidence(engine):
    async with engine.begin() as c:
        casts = _casts(c)
        with pytest.raises((IntegrityError, OperationalError)):
            async with c.begin_nested():
                await c.execute(
                    text(
                        f"INSERT INTO recommendation (text, confidence, evidence, reasoning, source_ref) "
                        f"VALUES ('x', 0.5, {casts['empty_arr']}, {casts['empty_obj']}, CAST(:s AS {casts['json_type']}))"
                    ),
                    {"s": SRC},
                )


async def test_i6_outcome_label_source(engine):
    async with engine.begin() as c:
        casts = _casts(c)
        opp_id = str(uuid.uuid4())
        await c.execute(
            text(
                f"INSERT INTO opportunity (id, title, source_ref) VALUES (:id, 'o', CAST(:s AS {casts['json_type']}))"
            ),
            {"id": opp_id, "s": SRC},
        )
        with pytest.raises((IntegrityError, OperationalError)):
            async with c.begin_nested():
                await c.execute(
                    text(
                        f"INSERT INTO outcome (opportunity_id, result, closed_at, recorded_by, label_source, source_ref)"
                        f" VALUES (:o, 'won', now(), 'u', 'predicted', CAST(:s AS {casts['json_type']}))"
                    ),
                    {"o": opp_id, "s": SRC},
                )


async def test_insufficient_band_cannot_be_high(engine):
    async with engine.begin() as c:
        casts = _casts(c)
        with pytest.raises((IntegrityError, OperationalError)):
            async with c.begin_nested():
                await c.execute(
                    text(
                        f"INSERT INTO opportunity (title, score, score_band, factors, completeness, source_ref) "
                        f"VALUES ('o', 0.9, 'high', {casts['empty_obj']}, 0.4, CAST(:s AS {casts['json_type']}))"
                    ),
                    {"s": SRC},
                )


async def test_audit_chain_append_verify_and_immutability(engine):
    from platform_core.db import session_scope

    async with session_scope() as s:
        for i in range(5):
            await append(
                s,
                org_id=ORG,
                actor="user:t",
                action="test.action",
                target=f"t:{i}",
                meta={"i": i, "f": 0.1, "nested": {"z": [1, "x"], "a": None}},
            )
    async with session_scope() as s:
        res = await verify_chain(s)
        assert res.ok and res.checked >= 5
    stmts = ["UPDATE audit_log SET actor = 'mallory'", "DELETE FROM audit_log"]
    if engine.dialect.name != "mysql":
        stmts.append("TRUNCATE audit_log")
    for stmt in stmts:
        with pytest.raises(DBAPIError, match="append-only"):
            async with engine.begin() as c:
                await c.execute(text(stmt))


async def test_outbox_edit_invalidates_approval(engine):
    async with engine.begin() as c:
        casts = _casts(c)
        appr_id = str(uuid.uuid4())
        subj_id = str(uuid.uuid4())
        await c.execute(
            text(
                "INSERT INTO approval (id, subject_type, subject_id, content_hash, requested_by, approver_id, decision) "
                "VALUES (:id, 'outbox', :subj, 'h1', 'u1', 'u2', 'approved')"
            ),
            {"id": appr_id, "subj": subj_id},
        )
        with pytest.raises((IntegrityError, OperationalError)):  # approved without an approval → rejected
            async with c.begin_nested():
                await c.execute(
                    text(
                        f"INSERT INTO outbox (channel, payload, content_hash, status, created_by) "
                        f"VALUES ('email', {casts['empty_obj']}, 'h1', 'approved', 'u1')"
                    )
                )
        ob_id = str(uuid.uuid4())
        v1_json = json.dumps({"body": "v1"})
        v2_json = json.dumps({"body": "v2"})
        await c.execute(
            text(
                f"INSERT INTO outbox (id, channel, payload, content_hash, approval_id, status, created_by) "
                f"VALUES (:id, 'email', CAST(:p AS {casts['json_type']}), 'h1', :a, 'approved', 'u1')"
            ),
            {"id": ob_id, "p": v1_json, "a": appr_id},
        )
        await c.execute(
            text(f"UPDATE outbox SET payload = CAST(:p AS {casts['json_type']}), content_hash = 'h2' WHERE id = :id"),
            {"id": ob_id, "p": v2_json},
        )
        row = (await c.execute(text("SELECT status, approval_id FROM outbox WHERE id = :id"), {"id": ob_id})).one()
        assert row.status == "draft" and row.approval_id is None
        dec = (await c.execute(text("SELECT decision FROM approval WHERE id = :a"), {"a": appr_id})).scalar()
        assert dec == "invalidated"


async def test_age_graph_cypher_with_params(engine):
    if engine.dialect.name == "mysql":
        pytest.skip("Apache AGE graph is PostgreSQL-specific. MySQL graph traversals verified in test_mysql_graph.py.")
    from platform_core.db import session_scope

    async with session_scope() as s:
        await age.cypher(
            s,
            "ckg",
            "CREATE (o:Organization {name: $name, source_ref: $src}) RETURN o",
            {"name": "Northwind Climate Fund I", "src": {"kind": "test"}},
        )
        rows = await age.cypher(
            s, "ckg", "MATCH (o:Organization {name: $name}) RETURN o.name", {"name": "Northwind Climate Fund I"}
        )
        assert rows == [{"result": "Northwind Climate Fund I"}]
        # injection attempt stays a literal value
        rows = await age.cypher(
            s,
            "ckg",
            "MATCH (o:Organization {name: $name}) RETURN o.name",
            {"name": "x'}) MATCH (n) DETACH DELETE n //"},
        )
        assert rows == []


async def test_graph_labels_exist(engine):
    if engine.dialect.name == "mysql":
        pytest.skip("ag_catalog is PostgreSQL AGE-specific. MySQL relational schema verified in test_mysql_graph.py.")
    async with engine.begin() as c:
        labels = set(
            (
                await c.execute(
                    text(
                        "SELECT l.name FROM ag_catalog.ag_label l JOIN ag_catalog.ag_graph g ON l.graph = g.graphid "
                        "WHERE g.name = 'ckg'"
                    )
                )
            ).scalars()
        )
    assert {"Opportunity", "Investor", "DERIVED_FROM", "SUPPORTS", "INTRODUCED"} <= labels


async def test_pgvector_hnsw_search(engine):
    if engine.dialect.name == "mysql":
        pytest.skip("pgvector HNSW is PostgreSQL-specific. MySQL vector BLOB verified in test_mysql_vector.py.")
    import random

    from platform_core.db.vector import COSINE_SEARCH_SQL, EMBEDDING_DIM, to_pgvector

    rnd = random.Random(7)
    vecs = [[rnd.random() for _ in range(EMBEDDING_DIM)] for _ in range(20)]
    async with engine.begin() as c:
        for i, v in enumerate(vecs):
            await c.execute(
                text(
                    "INSERT INTO embedding (entity_id, entity_type, model, dim, text_hash, vector) "
                    "VALUES (gen_random_uuid(), 'thesis', 'test-model', 1024, :h, CAST(:v AS vector))"
                ),
                {"h": f"h{i}", "v": to_pgvector(v)},
            )
        rows = (
            await c.execute(
                text(COSINE_SEARCH_SQL), {"q": to_pgvector(vecs[3]), "org": ORG, "model": "test-model", "k": 3}
            )
        ).all()
    assert rows[0].similarity == pytest.approx(1.0, abs=1e-5)


async def test_mysql_relational_graph_schema(engine):
    """MySQL equivalent of test_graph_labels_exist: validates relational graph schema and edge constraints."""
    if engine.dialect.name != "mysql":
        pytest.skip("MySQL relational graph schema test applies only to MySQL.")
    async with engine.begin() as c:
        ent_cols = set(
            (
                await c.execute(
                    text(
                        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'entity'"
                    )
                )
            ).scalars()
        )
        assert {"id", "org_id", "entity_type", "ref_id", "label", "attrs"}.issubset(ent_cols)

        edge_cols = set(
            (
                await c.execute(
                    text(
                        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
                        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'relationship_edge'"
                    )
                )
            ).scalars()
        )
        assert {"id", "org_id", "from_entity", "to_entity", "type", "weight", "attrs"}.issubset(edge_cols)


async def test_mysql_vector_blob_persistence(engine):
    """MySQL equivalent of test_pgvector_hnsw_search: validates IEEE-754 32-bit packed binary BLOB persistence."""
    if engine.dialect.name != "mysql":
        pytest.skip("MySQL vector BLOB persistence test applies only to MySQL.")
    import random

    from platform_core.db.vector import EMBEDDING_DIM, from_blob, to_blob

    rnd = random.Random(42)
    sample_vec = [rnd.random() for _ in range(EMBEDDING_DIM)]
    packed_blob = to_blob(sample_vec)
    ent_id = str(uuid.uuid4())

    async with engine.begin() as c:
        await c.execute(
            text(
                "INSERT INTO embedding (id, entity_id, entity_type, model, dim, text_hash, vector) "
                "VALUES (UUID(), :ent_id, 'thesis', 'test-model', :dim, 'h_mysql', :v)"
            ),
            {"ent_id": ent_id, "dim": EMBEDDING_DIM, "v": packed_blob},
        )
        row = (
            (
                await c.execute(
                    text("SELECT dim, vector FROM embedding WHERE entity_id = :ent_id"),
                    {"ent_id": ent_id},
                )
            )
            .mappings()
            .one()
        )

        assert row["dim"] == EMBEDDING_DIM
        retrieved_vec = from_blob(row["vector"])
        assert len(retrieved_vec) == EMBEDDING_DIM
        for orig, retr in zip(sample_vec, retrieved_vec, strict=False):
            assert orig == pytest.approx(retr, abs=1e-6)
