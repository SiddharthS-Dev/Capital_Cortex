"""Schema-level invariants on the real custom Postgres image (AGE + pgvector).

Run: pytest -m integration   (needs Docker and the image from `make build-postgres`)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from platform_core.audit import append, verify_chain
from platform_core.db import age

pytestmark = pytest.mark.integration

IMAGE = os.environ.get("CORTEX_PG_IMAGE", "capital-cortex/postgres:16-age1.5.0-pgvector0.8.0")
ROOT = Path(__file__).resolve().parents[2]
ORG = "00000000-0000-0000-0000-000000000001"
SRC = json.dumps({"kind": "test", "id": "t1"})


async def test_i1_provenance_check(engine):
    async with engine.begin() as c:
        with pytest.raises(IntegrityError):
            async with c.begin_nested():
                await c.execute(text("INSERT INTO organization (name, kind) VALUES ('NoSource', 'counterparty')"))
        with pytest.raises(IntegrityError):
            async with c.begin_nested():
                await c.execute(
                    text(
                        "INSERT INTO organization (name, kind, source_ref) "
                        "VALUES ('EmptySource', 'counterparty', '{}'::jsonb)"
                    )
                )
        await c.execute(
            text(
                "INSERT INTO organization (name, kind, source_ref) "
                "VALUES ('Sourced', 'counterparty', CAST(:s AS jsonb))"
            ),
            {"s": SRC},
        )


async def test_i1_inference_path(engine):
    async with engine.begin() as c:
        with pytest.raises(IntegrityError):  # an inference must name its basis
            async with c.begin_nested():
                await c.execute(
                    text("INSERT INTO inference (method, produced_by, basis_refs) VALUES ('rule', 'test', '[]'::jsonb)")
                )
        inf = (
            await c.execute(
                text(
                    "INSERT INTO inference (method, produced_by, basis_refs) "
                    "VALUES ('rule', 'test', CAST(:b AS jsonb)) RETURNING id"
                ),
                {"b": json.dumps([{"signal": "s1"}])},
            )
        ).scalar()
        await c.execute(
            text("INSERT INTO organization (name, kind, inference_id) VALUES ('Inferred', 'counterparty', :i)"),
            {"i": inf},
        )


async def test_i2_recommendation_needs_evidence(engine):
    async with engine.begin() as c:
        with pytest.raises(IntegrityError):
            async with c.begin_nested():
                await c.execute(
                    text(
                        "INSERT INTO recommendation (text, confidence, evidence, reasoning, source_ref) "
                        "VALUES ('x', 0.5, '[]'::jsonb, '{}'::jsonb, CAST(:s AS jsonb))"
                    ),
                    {"s": SRC},
                )


async def test_i6_outcome_label_source(engine):
    async with engine.begin() as c:
        opp = (
            await c.execute(
                text("INSERT INTO opportunity (title, source_ref) VALUES ('o', CAST(:s AS jsonb)) RETURNING id"),
                {"s": SRC},
            )
        ).scalar()
        with pytest.raises(IntegrityError):
            async with c.begin_nested():
                await c.execute(
                    text(
                        "INSERT INTO outcome (opportunity_id, result, closed_at, recorded_by, label_source, source_ref)"
                        " VALUES (:o, 'won', now(), 'u', 'predicted', CAST(:s AS jsonb))"
                    ),
                    {"o": opp, "s": SRC},
                )


async def test_insufficient_band_cannot_be_high(engine):
    async with engine.begin() as c:
        with pytest.raises(IntegrityError):
            async with c.begin_nested():
                await c.execute(
                    text(
                        "INSERT INTO opportunity (title, score, score_band, factors, completeness, source_ref) "
                        "VALUES ('o', 0.9, 'high', '{}'::jsonb, 0.4, CAST(:s AS jsonb))"
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
    for stmt in ("UPDATE audit_log SET actor = 'mallory'", "DELETE FROM audit_log", "TRUNCATE audit_log"):
        with pytest.raises(DBAPIError, match="append-only"):
            async with engine.begin() as c:
                await c.execute(text(stmt))


async def test_outbox_edit_invalidates_approval(engine):
    async with engine.begin() as c:
        appr = (
            await c.execute(
                text(
                    "INSERT INTO approval (subject_type, subject_id, content_hash, requested_by, approver_id, decision) "
                    "VALUES ('outbox', gen_random_uuid(), 'h1', 'u1', 'u2', 'approved') RETURNING id"
                )
            )
        ).scalar()
        with pytest.raises(IntegrityError):  # approved without an approval → rejected
            async with c.begin_nested():
                await c.execute(
                    text(
                        "INSERT INTO outbox (channel, payload, content_hash, status, created_by) "
                        "VALUES ('email', '{}'::jsonb, 'h1', 'approved', 'u1')"
                    )
                )
        ob = (
            await c.execute(
                text(
                    "INSERT INTO outbox (channel, payload, content_hash, approval_id, status, created_by) "
                    "VALUES ('email', '{\"body\": \"v1\"}'::jsonb, 'h1', :a, 'approved', 'u1') RETURNING id"
                ),
                {"a": appr},
            )
        ).scalar()
        await c.execute(
            text("UPDATE outbox SET payload = '{\"body\": \"v2\"}'::jsonb, content_hash = 'h2' WHERE id = :id"),
            {"id": ob},
        )
        row = (await c.execute(text("SELECT status, approval_id FROM outbox WHERE id = :id"), {"id": ob})).one()
        assert row.status == "draft" and row.approval_id is None
        dec = (await c.execute(text("SELECT decision FROM approval WHERE id = :a"), {"a": appr})).scalar()
        assert dec == "invalidated"


async def test_age_graph_cypher_with_params(engine):
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
