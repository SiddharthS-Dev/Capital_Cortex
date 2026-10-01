"""Flow 1 (§7): signal → classify → resolve → graph (AGE + mirrors) → embedding → score, on the real image."""

from __future__ import annotations

import json

import fakeredis.aioredis
import pytest
from sqlalchemy import text

from cortex.l1_perception.models import Signal
from cortex.l2_representation.pipeline import process_signal
from platform_core.bus import streams
from platform_core.db import age, session_scope

pytestmark = pytest.mark.integration


@pytest.fixture
async def bus(engine):
    streams.set_bus(streams.Bus(fakeredis.aioredis.FakeRedis()))
    yield
    streams.set_bus(None)


async def _signal(sig: Signal, source_key: str = "it_source") -> str:
    async with session_scope() as s:
        src = (
            await s.execute(
                text(
                    "INSERT INTO source (name, kind, adapter_key, adapter, terms_note) VALUES (:k, 'api', :k, 'json_api', 't') "
                    "ON CONFLICT (org_id, adapter_key) DO UPDATE SET name = EXCLUDED.name RETURNING id"
                ),
                {"k": source_key},
            )
        ).scalar_one()
        return str(
            (
                await s.execute(
                    text(
                        "INSERT INTO signal (source_id, external_id, raw, normalized, content_hash, source_ref) VALUES "
                        "(:src, :ext, '{}'::jsonb, CAST(:n AS jsonb), :h, CAST(:ref AS jsonb)) RETURNING id"
                    ),
                    {
                        "src": src,
                        "ext": sig.external_id,
                        "n": sig.model_dump_json(),
                        "h": sig.content_hash(),
                        "ref": json.dumps({"kind": "signal_source", "source_id": str(src)}),
                    },
                )
            ).scalar_one()
        )


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
        o = (await s.execute(text("SELECT * FROM opportunity WHERE id = :id"), {"id": opp_id})).mappings().one()
        assert o["external_key"] == "it_source:it-1" and o["source_ref"]["signal_id"] == sid
        assert o["score_band"] == "insufficient_evidence"  # no organisation profile yet: gaps, never imputed
        assert o["factors"]["factors"]["geography"]["gap"]
        assert "ai_data" in o["sectors"]
        # graph: Opportunity -DERIVED_FROM-> Signal, Organization -OFFERS-> Opportunity
        rows = await age.cypher(
            s, "ckg", "MATCH (o:Opportunity {id: $id})-[:DERIVED_FROM]->(sg:Signal) RETURN sg.id", {"id": opp_id}
        )
        assert rows == [{"result": sid}]
        rows = await age.cypher(
            s, "ckg", "MATCH (org:Organization)-[:OFFERS]->(o:Opportunity {id: $id}) RETURN org.name", {"id": opp_id}
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
        o = (
            (
                await s.execute(
                    text("SELECT class::text AS c, class_source, deadline FROM opportunity WHERE id = :id"),
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
        await s.execute(
            text(
                "INSERT INTO organization (name, normalized_name, kind, country, profile, source_ref) VALUES "
                "('Inspironics', 'inspironics', 'self', 'US', CAST(:p AS jsonb), '{\"kind\": \"test\"}'::jsonb)"
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
        assert o["completeness"] >= 0.6 and o["score"] is not None and o["score_band"] != "insufficient_evidence"
        assert o["factors"]["factors"]["geography"]["value"] == 1.0
