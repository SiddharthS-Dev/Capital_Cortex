"""Phase 1 definition of done, through the real API on the real database:
upload a CSV → opportunities classified and scored with evidence → weights change the ranking → path finder works.
"""

from __future__ import annotations

import json

import fakeredis.aioredis
import httpx
import pytest
from sqlalchemy import text

from cortex.l2_representation.pipeline import process_signal
from cortex.l8_actuation.api.app import create_app
from platform_core.auth import oidc
from platform_core.bus import streams
from platform_core.db import session_scope
from platform_core.policy import opa
from platform_core.policy.opa import PolicyDecision

pytestmark = pytest.mark.integration

CSV = (
    "Title,Organization,Country,Deadline,Amount Min,Amount Max,Currency,Class,Description,Stage\n"
    "Seed round for climate AI software,Veltaris Ventures,United States,2027-02-01,250000,1000000,USD,venture equity,"
    "Venture capital for seed-stage climate and AI startups,seed\n"
    "Clean energy storage research grant,Quorvane Foundation,US,2026-12-15,100000,400000,USD,,"
    "Non-dilutive grant for energy storage research and development,\n"
    "Venture debt term loan,Ardentis Lending LLC,Germany,,2000000,5000000,EUR,,Term loan facility for VC-backed firms,growth\n"
)


class AllowOPA:
    async def evaluate(self, package, input_):
        return PolicyDecision(True, [])


@pytest.fixture
async def client(engine, verifier):
    oidc.set_verifier(verifier)
    opa.set_opa(AllowOPA())  # type: ignore[arg-type]
    streams.set_bus(streams.Bus(fakeredis.aioredis.FakeRedis()))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://t") as c:
        yield c
    oidc.set_verifier(None)
    opa.set_opa(None)
    streams.set_bus(None)


async def drain_signals() -> int:
    """Act as the worker: process every signal.ingested envelope on the (fake) bus."""
    bus = streams.get_bus()
    msgs = await bus.r.xrange("signals.raw")
    for _, fields in msgs:
        payload = json.loads(fields[b"payload"])
        await process_signal(payload["signal_id"])
    await bus.r.delete("signals.raw")
    return len(msgs)


async def test_phase1_definition_of_done(client, make_token):
    h = {"Authorization": f"Bearer {make_token(['admin', 'approver'], auth_age=5)}"}
    sources = (await client.get("/v1/sources", headers=h)).json()["items"]
    csv_src = next(s for s in sources if s["adapter_key"] == "csv_upload")

    # 1) upload → signals stored with provenance → processed
    r = await client.post(
        f"/v1/sources/{csv_src['id']}/upload", headers=h, files={"file": ("pipeline.csv", CSV.encode(), "text/csv")}
    )
    assert r.status_code == 200, r.text
    assert r.json()["new"] == 3 and r.json()["status"] == "succeeded"
    assert await drain_signals() == 3

    # 2) opportunities classified and scored, with evidence on every factor
    await client.put(
        "/v1/organization/self",
        headers=h,
        json={
            "name": "Inspironics",
            "country": "US",
            "strategic_priorities": ["climate", "ai"],
            "tech_tags": ["ai", "energy storage"],
            "description": "AI software for climate and energy storage",
            "stage": "seed",
            "esg_tags": ["climate", "clean_energy"],
            "raise_target": {"min": 200000, "max": 1500000, "currency": "USD"},
        },
    )
    async with session_scope() as s:
        from cortex.l4_reasoning.score_service import rescore_all

        await rescore_all(s)  # what the worker does after the profile-updated rescore job
    lst = (await client.get("/v1/opportunities?source=csv_upload", headers=h)).json()
    by_title = {o["title"]: o for o in lst["items"]}
    assert by_title["Seed round for climate AI software"]["class"] == "venture_equity"
    assert by_title["Clean energy storage research grant"]["class"] == "grant"
    assert by_title["Venture debt term loan"]["class"] == "debt_facility"
    seed = by_title["Seed round for climate AI software"]
    assert seed["score"] is not None and seed["completeness"] >= 0.6
    detail = (await client.get(f"/v1/opportunities/{seed['id']}", headers=h)).json()
    factors = detail["factors"]["factors"]
    assert factors["geography"]["value"] == 1.0 and factors["geography"]["evidence"]
    assert factors["stage"]["value"] == 1.0
    assert factors["relationship_strength"]["gap"]  # still a gap: never imputed
    assert detail["signal"]["field_sources"]["title"].startswith("raw:")
    euro = by_title["Venture debt term loan"]
    euro_d = (await client.get(f"/v1/opportunities/{euro['id']}", headers=h)).json()
    assert "Currency mismatch" in euro_d["factors"]["factors"]["funding_size"]["gap"]

    # 3) change weights → live re-rank (no persistence)
    prof = (await client.get("/v1/scoring/profiles", headers=h)).json()["items"][0]
    only_timing = {k: {"weight": (1.0 if k == "timing" else 0.0)} for k in prof["factors"]}
    pv = (await client.post("/v1/scoring/preview", headers=h, json={"factors": only_timing, "limit": 10})).json()
    assert pv["items"] and any(i["rank_delta"] != 0 or i["new_score"] != i["old_score"] for i in pv["items"])
    after = (await client.get(f"/v1/opportunities/{seed['id']}", headers=h)).json()
    assert after["score"] == detail["score"]  # preview persisted nothing

    # 4) graph path finder: opportunity ↔ its counterparty organisation
    g = (await client.get(f"/v1/graph/paths?from={seed['id']}&to={seed['counterparty_id']}", headers=h)).json()
    assert g["count"] >= 1 and g["paths"][0]["hops"] == 1

    # 5) dashboards reflect it; idempotent-safe re-upload inserts nothing new
    dash = (await client.get("/v1/dashboards/executive", headers=h)).json()
    assert dash["kpis"]["active_opportunities"]["value"] >= 3
    again = await client.post(
        f"/v1/sources/{csv_src['id']}/upload", headers=h, files={"file": ("pipeline.csv", CSV.encode(), "text/csv")}
    )
    assert again.json()["new"] == 0 and again.json()["duplicate"] == 3
    async with session_scope() as s:
        audited = (await s.execute(text("SELECT count(*) FROM audit_log WHERE action = 'source.run'"))).scalar()
        assert audited >= 2
