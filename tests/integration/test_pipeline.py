"""Flow 1 (§7): signal → classify → resolve → graph (AGE + mirrors) → embedding → score, on the real image."""

from __future__ import annotations

import json
import uuid

import fakeredis.aioredis
import pytest
from sqlalchemy import text

from cortex.l1_perception.models import Signal
from cortex.l2_representation.pipeline import process_signal
from platform_core.bus import streams
from platform_core.db import age, session_scope
from platform_core.db.compat import is_mysql_session

pytestmark = pytest.mark.integration


@pytest.fixture
async def bus(engine):
    streams.set_bus(streams.Bus(fakeredis.aioredis.FakeRedis()))
    yield
    streams.set_bus(None)


async def _signal(sig: Signal, source_key: str = "it_source") -> str:
    async with session_scope() as s:
        is_my = is_mysql_session(s)
        src = (
            await s.execute(
                text("SELECT id FROM source WHERE adapter_key = :k"),
                {"k": source_key},
            )
        ).scalar_one_or_none()
        if not src:
            src = str(uuid.uuid4())
            await s.execute(
                text(
                    "INSERT INTO source (id, name, kind, adapter_key, adapter, terms_note) "
                    "VALUES (:id, :k, 'api', :k, 'json_api', 't')"
                ),
                {"id": src, "k": source_key},
            )
        else:
            src = str(src)

        sig_id = str(uuid.uuid4())
        sig_tbl = "`signal`" if is_my else "signal"
        json_type = "JSON" if is_my else "jsonb"
        empty_obj = "CAST('{}' AS JSON)" if is_my else "'{}'::jsonb"

        await s.execute(
            text(
                f"INSERT INTO {sig_tbl} (id, source_id, external_id, raw, normalized, content_hash, source_ref) VALUES "
                f"(:id, :src, :ext, {empty_obj}, CAST(:n AS {json_type}), :h, CAST(:ref AS {json_type}))"
            ),
            {
                "id": sig_id,
                "src": src,
                "ext": sig.external_id,
                "n": sig.model_dump_json(),
                "h": sig.content_hash(),
                "ref": json.dumps({"kind": "signal_source", "source_id": str(src)}),
            },
        )
        return sig_id


def grant(title="Research grant: AI for clean energy storage", ext="it-1", deadline="2027-03-01T00:00:00Z"):
    return Signal(
        source_key="it_source",
        external_id=ext,
        title=title,
        description="Grants for AI in energy storage",
        counterparty_name="U.S. National Science Foundation",
        counterparty_kind="agency",
        counterparty_country="US",
        countries=["US"],
        currency="USD",
        amount_max=275000,
        deadline=deadline,
        class_hint="grant",
        field_sources={"class_hint": "source_default", "title": "raw:title"},
    )


async def test_signal_becomes_scored_opportunity_in_graph(engine, bus):
    async with session_scope() as s:  # isolation: this test asserts behaviour with no organisation profile
        await s.execute(text("DELETE FROM organization WHERE kind = 'self'"))
    sid = await _signal(grant())
    event = await process_signal(sid)
    assert event["type"] == "opportunity.created" and event["class"] == "grant"
    opp_id = event["opportunity_id"]
    async with session_scope() as s:
        is_my = is_mysql_session(s)
        o = (await s.execute(text("SELECT * FROM opportunity WHERE id = :id"), {"id": opp_id})).mappings().one()
        sref = json.loads(o["source_ref"]) if isinstance(o["source_ref"], str) else o["source_ref"]
        factors = json.loads(o["factors"]) if isinstance(o["factors"], str) else o["factors"]
        sectors = json.loads(o["sectors"]) if isinstance(o["sectors"], str) else o["sectors"]
        assert o["external_key"] == "it_source:it-1" and sref["signal_id"] == sid
        assert o["score_band"] == "insufficient_evidence"  # no organisation profile yet: gaps, never imputed
        assert factors["factors"]["geography"]["gap"]
        assert "ai_data" in sectors
        # graph: Opportunity -DERIVED_FROM-> Signal, Organization -OFFERS-> Opportunity
        if is_my:
            # Query relational mirror graph
            derived_rows = (
                (
                    await s.execute(
                        text(
                            "SELECT e2.ref_id AS result FROM relationship_edge re "
                            "JOIN entity e1 ON e1.id = re.from_entity "
                            "JOIN entity e2 ON e2.id = re.to_entity "
                            "WHERE e1.ref_id = :id AND re.type = 'DERIVED_FROM'"
                        ),
                        {"id": opp_id},
                    )
                )
                .mappings()
                .all()
            )
            assert [dict(r) for r in derived_rows] == [{"result": sid}]
            offers_rows = (
                (
                    await s.execute(
                        text(
                            "SELECT e1.label AS result FROM relationship_edge re "
                            "JOIN entity e1 ON e1.id = re.from_entity "
                            "JOIN entity e2 ON e2.id = re.to_entity "
                            "WHERE e2.ref_id = :id AND re.type = 'OFFERS'"
                        ),
                        {"id": opp_id},
                    )
                )
                .mappings()
                .all()
            )
            assert [dict(r) for r in offers_rows] == [{"result": "U.S. National Science Foundation"}]
        else:
            rows = await age.cypher(
                s, "ckg", "MATCH (o:Opportunity {id: $id})-[:DERIVED_FROM]->(sg:Signal) RETURN sg.id", {"id": opp_id}
            )
            assert rows == [{"result": sid}]
            rows = await age.cypher(
                s,
                "ckg",
                "MATCH (org:Organization)-[:OFFERS]->(o:Opportunity {id: $id}) RETURN org.name",
                {"id": opp_id},
            )
            assert rows == [{"result": "U.S. National Science Foundation"}]
        emb = (await s.execute(text("SELECT count(*) FROM embedding WHERE entity_id = :id"), {"id": opp_id})).scalar()
        assert emb == 1


async def test_revised_listing_updates_same_opportunity_and_keeps_human_class(engine, bus):
    first = await process_signal(await _signal(grant(ext="it-2")))
    async with session_scope() as s:
        await s.execute(
            text("UPDATE opportunity SET class = 'government_program', class_source = 'human' WHERE id = :id"),
            {"id": first["opportunity_id"]},
        )
    second = await process_signal(await _signal(grant(ext="it-2", deadline="2027-06-01T00:00:00Z")))
    assert second["opportunity_id"] == first["opportunity_id"] and second["type"] == "opportunity.updated"
    async with session_scope() as s:
        is_my = is_mysql_session(s)
        cls_col = "class AS c" if is_my else "class::text AS c"
        o = (
            (
                await s.execute(
                    text(f"SELECT {cls_col}, class_source, deadline FROM opportunity WHERE id = :id"),
                    {"id": first["opportunity_id"]},
                )
            )
            .mappings()
            .one()
        )
        assert o["c"] == "government_program" and o["class_source"] == "human" and o["deadline"].month == 6
        n = (
            await s.execute(
                text(
                    "SELECT count(*) FROM relationship_edge re JOIN entity e ON e.id = re.from_entity "
                    "WHERE e.ref_id = :id AND re.type = 'DERIVED_FROM'"
                ),
                {"id": first["opportunity_id"]},
            )
        ).scalar()
        assert n == 2  # provenance to both revisions


async def test_same_counterparty_resolves_to_one_organization(engine, bus):
    a = await process_signal(await _signal(grant(ext="it-3", title="Program A")))
    b = await process_signal(await _signal(grant(ext="it-4", title="Program B")))
    async with session_scope() as s:
        ids = (
            (
                await s.execute(
                    text("SELECT DISTINCT counterparty_id FROM opportunity WHERE id IN (:a, :b)"),
                    {"a": a["opportunity_id"], "b": b["opportunity_id"]},
                )
            )
            .scalars()
            .all()
        )
        assert len(ids) == 1


async def test_profile_enables_scoring(engine, bus):
    async with session_scope() as s:
        is_my = is_mysql_session(s)
        json_type = "JSON" if is_my else "jsonb"
        test_src = 'CAST(\'{"kind": "test"}\' AS JSON)' if is_my else '\'{"kind": "test"}\'::jsonb'
        await s.execute(
            text(
                f"INSERT INTO organization (name, normalized_name, kind, country, profile, source_ref) VALUES "
                f"('Inspironics', 'inspironics', 'self', 'US', CAST(:p AS {json_type}), {test_src})"
            ),
            {
                "p": json.dumps(
                    {
                        "strategic_priorities": ["clean energy", "ai"],
                        "tech_tags": ["energy storage", "ai"],
                        "description": "AI for energy storage",
                        "stage": "seed",
                        "esg_tags": ["clean_energy"],
                        "raise_target": {"min": 100000, "max": 500000, "currency": "USD"},
                    }
                )
            },
        )
    ev = await process_signal(await _signal(grant(ext="it-5", title="SBIR Phase I seed grant for AI energy storage")))
    async with session_scope() as s:
        o = (
            (
                await s.execute(
                    text("SELECT score, score_band, completeness, factors FROM opportunity WHERE id = :id"),
                    {"id": ev["opportunity_id"]},
                )
            )
            .mappings()
            .one()
        )
        factors = json.loads(o["factors"]) if isinstance(o["factors"], str) else o["factors"]
        assert o["completeness"] >= 0.6 and o["score"] is not None and o["score_band"] != "insufficient_evidence"
        assert factors["factors"]["geography"]["value"] == 1.0
