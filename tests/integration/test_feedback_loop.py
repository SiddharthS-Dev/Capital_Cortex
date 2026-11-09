"""Phase 3 feedback loop (§16): ml_scorer trains on the factor values an opportunity had when it was decided
(factor_history), shadow-evaluates the candidate on a temporal holdout against the prior or the active model, and
promotes only a better model. Runs in one transaction that is rolled back, so no other test sees the outcomes."""

from __future__ import annotations

import hashlib
import json
import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l4_reasoning import ml_scorer

pytestmark = pytest.mark.integration
SRC = json.dumps({"kind": "manual_entry", "entered_by": "integration"})


def _doc(fit: float) -> str:
    names = ml_scorer.ml_config()["features"]["factors"]
    return json.dumps(
        {"factors": {n: {"value": fit if n == "strategic_fit" else 0.5, "available": True} for n in names}}
    )


async def test_trains_on_decision_time_factors_and_promotes_only_better_models(engine):
    rnd = random.Random(11)
    t0 = datetime.now(UTC) - timedelta(days=400)
    is_my = engine.dialect.name == "mysql"
    json_type = "JSON" if is_my else "jsonb"

    async with engine.connect() as conn:
        tx = await conn.begin()
        s = AsyncSession(bind=conn, join_transaction_mode="create_savepoint")
        try:
            await s.execute(text("DELETE FROM outcome WHERE NOT is_demo"))  # this test owns the real-outcome set
            for i in range(60):
                won = i % 2 == 0
                oid = str(uuid.uuid4())
                await s.execute(
                    text(
                        f"INSERT INTO opportunity (id, title, class, factors, completeness, source_ref) VALUES "
                        f"(:id, :t, 'grant', CAST(:f AS {json_type}), 0.9, CAST(:s AS {json_type}))"
                    ),
                    {"id": oid, "t": f"feedback-{i}", "f": _doc(rnd.random()), "s": SRC},
                )
                decided = _doc(
                    0.85 + rnd.random() * 0.1 if won else 0.05 + rnd.random() * 0.1
                )  # as score_service stores it
                h = hashlib.sha256(str(i).encode()).hexdigest()
                await s.execute(
                    text(
                        f"INSERT INTO factor_history (opportunity_id, completeness, factors, factor_hash, scored_at) "
                        f"VALUES (:o, 0.9, CAST(:f AS {json_type}), :h, :at)"
                    ),
                    {"o": oid, "f": decided, "h": h, "at": t0 + timedelta(days=i * 5)},
                )
                await s.execute(
                    text(
                        f"INSERT INTO outcome (opportunity_id, result, closed_at, recorded_by, label_source, source_ref) "
                        f"VALUES (:o, :r, :at, 'user:test', 'realised', CAST(:s AS {json_type}))"
                    ),
                    {"o": oid, "r": "won" if won else "lost", "at": t0 + timedelta(days=i * 5 + 2), "s": SRC},
                )

            first = await ml_scorer.train(s, "user:test", demo=False)
            assert first.metrics["decision_time_share"] == 1.0
            ho = first.metrics["holdout"]
            assert ho["n"] == 12 and ho["reference_label"] == "the class-prior baseline"
            assert ho["candidate"]["auc"] > 0.9, ho  # only decision-time values carry the signal
            assert first.status == "active" and "(holdout)" in first.reason

            second = await ml_scorer.train(s, "user:test", demo=False)
            assert second.metrics["holdout"]["reference_label"] == f"active model v{first.version}"
            assert second.status == "rejected" and "not better" in second.reason  # same data: no promotion
            active = await ml_scorer.active_models(s)
            assert active[False].version == first.version
        finally:
            await s.close()
            await tx.rollback()
            ml_scorer._model_cache.clear()
