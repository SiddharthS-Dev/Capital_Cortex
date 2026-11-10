"""§13: the synthetic seed is fully flagged, flows through the real pipeline, and purges without touching real data."""

from __future__ import annotations

import random
import uuid

import fakeredis.aioredis
import pytest
from sqlalchemy import text

from platform_core.bus import streams
from platform_core.db import age, is_mysql_session, session_scope
from seed.generate import seed
from seed.purge import purge

pytestmark = pytest.mark.integration


async def test_seed_then_purge(engine):
    streams.set_bus(streams.Bus(fakeredis.aioredis.FakeRedis()))
    async with session_scope() as s:
        is_my = is_mysql_session(s)
        if is_my:
            real = str(uuid.uuid4())
            await s.execute(
                text(
                    "INSERT INTO organization (id, name, kind, source_ref) VALUES (:id, 'Real Counterparty', 'counterparty', "
                    'CAST(\'{"kind": "test"}\' AS JSON))'
                ),
                {"id": real},
            )
        else:
            real = (
                await s.execute(
                    text(
                        "INSERT INTO organization (name, kind, source_ref) VALUES ('Real Counterparty', 'counterparty', "
                        '\'{"kind": "test"}\'::jsonb) RETURNING id'
                    )
                )
            ).scalar_one()
    try:
        counts = await seed(33, random.Random(1))
        assert counts["opportunities"] == 33 and counts["snapshots"] == 18 and counts["outcomes"] > 0
        async with session_scope() as s:
            is_my = is_mysql_session(s)
            demo_opps = (await s.execute(text("SELECT count(*) FROM opportunity WHERE is_demo"))).scalar()
            classes = (await s.execute(text("SELECT count(DISTINCT class) FROM opportunity WHERE is_demo"))).scalar()
            sig_tbl = "`signal`" if is_my else "signal"
            sig_cond = (
                "sg.source_ref->>'$.kind' = 'synthetic_seed'" if is_my else "sg.source_ref->>'kind' = 'synthetic_seed'"
            )
            not_flagged = (
                await s.execute(
                    text(
                        f"SELECT count(*) FROM opportunity o JOIN {sig_tbl} sg ON sg.id = o.signal_id "
                        f"WHERE {sig_cond} AND NOT o.is_demo"
                    )
                )
            ).scalar()
            assert demo_opps == 33 and classes >= 9 and not_flagged == 0
            factor_cond = (
                "factors->>'$.factors.relationship_strength.available' = 'true'"
                if is_my
                else "factors->'factors'->'relationship_strength'->>'available' = 'true'"
            )
            scored = (
                await s.execute(text(f"SELECT count(*) FROM opportunity WHERE is_demo AND {factor_cond}"))
            ).scalar()
            assert scored > 0  # seeded relationships feed the relationship_strength factor
        purged = await purge()
        assert purged["opportunity"] == 33
        async with session_scope() as s:
            is_my = is_mysql_session(s)
            left = (
                await s.execute(
                    text(
                        "SELECT (SELECT count(*) FROM opportunity WHERE is_demo) + (SELECT count(*) FROM organization WHERE is_demo) "
                        "+ (SELECT count(*) FROM financial_snapshot WHERE is_demo) + (SELECT count(*) FROM outcome WHERE is_demo)"
                    )
                )
            ).scalar()
            assert left == 0
            assert (
                await s.execute(text("SELECT count(*) FROM organization WHERE id = :id"), {"id": real})
            ).scalar() == 1
            if not is_my:
                rows = await age.cypher(s, "ckg", "MATCH (n) WHERE n.is_demo = true RETURN count(n)")
                assert rows[0]["result"] == 0
    finally:
        streams.set_bus(None)
