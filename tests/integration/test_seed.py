"""§13: the synthetic seed is fully flagged, flows through the real pipeline, and purges without touching real data."""

from __future__ import annotations

import json
import random

import fakeredis.aioredis
import pytest
from sqlalchemy import text

from platform_core.bus import streams
from platform_core.db import age, session_scope
from seed.generate import seed
from seed.purge import purge

pytestmark = pytest.mark.integration


async def test_seed_then_purge(engine):
    streams.set_bus(streams.Bus(fakeredis.aioredis.FakeRedis()))
    async with session_scope() as s:
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
            demo_opps = (await s.execute(text("SELECT count(*) FROM opportunity WHERE is_demo"))).scalar()
            classes = (await s.execute(text("SELECT count(DISTINCT class) FROM opportunity WHERE is_demo"))).scalar()
            not_flagged = (
                await s.execute(
                    text(
                        "SELECT count(*) FROM opportunity o JOIN signal sg ON sg.id = o.signal_id "
                        "WHERE sg.source_ref->>'kind' = 'synthetic_seed' AND NOT o.is_demo"
                    )
                )
            ).scalar()
            assert demo_opps == 33 and classes >= 9 and not_flagged == 0
            scored = (
                await s.execute(
                    text(
                        "SELECT count(*) FROM opportunity WHERE is_demo AND factors->'factors'->'relationship_strength'->>'available' = 'true'"
                    )
                )
            ).scalar()
            assert scored > 0  # seeded relationships feed the relationship_strength factor
        # demo work products from Phase 2/3 flows: an APPROVED demo e-mail (outbox → approval FK) and a demo
        # board pack with its approval and distribution e-mail (linked only through the payload)
        async with session_scope() as s:
            opp = (await s.execute(text("SELECT id FROM opportunity WHERE is_demo LIMIT 1"))).scalar_one()
            oid = (
                await s.execute(
                    text(
                        "INSERT INTO outbox (channel, payload, content_hash, status, created_by, opportunity_id) "
                        "VALUES ('email', '{\"to\": \"x@example.org\"}'::jsonb, 'h', 'draft', 'u', :o) RETURNING id"
                    ),
                    {"o": opp},
                )
            ).scalar_one()
            aid = (
                await s.execute(
                    text(
                        "INSERT INTO approval (subject_type, subject_id, content_hash, requested_by, approver_id, decision) "
                        "VALUES ('outbox', :o, 'h', 'u', 'v', 'approved') RETURNING id"
                    ),
                    {"o": oid},
                )
            ).scalar_one()
            await s.execute(
                text("UPDATE outbox SET status = 'approved', approval_id = :a WHERE id = :o"), {"a": aid, "o": oid}
            )
            bid = (
                await s.execute(
                    text(
                        "INSERT INTO board_report (period_start, period_end, title, content, content_hash, created_by, is_demo) "
                        "VALUES (current_date, current_date, 'Demo pack', '{}'::jsonb, 'h', 'u', true) RETURNING id"
                    )
                )
            ).scalar_one()
            await s.execute(
                text(
                    "INSERT INTO approval (subject_type, subject_id, content_hash, requested_by, approver_id, decision) "
                    "VALUES ('board_report', :b, 'h', 'u', 'v', 'approved')"
                ),
                {"b": bid},
            )
            await s.execute(
                text(
                    "INSERT INTO outbox (channel, payload, content_hash, status, created_by) "
                    "VALUES ('email', CAST(:p AS jsonb), 'h', 'draft', 'u')"
                ),
                {"p": json.dumps({"board_report_id": str(bid)})},
            )
        purged = await purge()
        assert purged["opportunity"] == 33 and purged["outbox"] >= 2 and purged["approval"] >= 2, purged
        async with session_scope() as s:
            orphans = (
                await s.execute(
                    text(
                        "SELECT count(*) FROM approval a WHERE a.subject_type = 'board_report' "
                        "AND NOT EXISTS (SELECT 1 FROM board_report b WHERE b.id = a.subject_id)"
                    )
                )
            ).scalar()
            assert orphans == 0, "an approval leaves with its demo subject"
        async with session_scope() as s:
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
            rows = await age.cypher(s, "ckg", "MATCH (n) WHERE n.is_demo = true RETURN count(n)")
            assert rows[0]["result"] == 0
    finally:
        streams.set_bus(None)
