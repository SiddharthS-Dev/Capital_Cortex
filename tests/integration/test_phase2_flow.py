"""Phase 2 definition of done, through the real API, real Postgres (AGE + pgvector) and real OPA/Rego:

run the council on a high-score opportunity → live stream → citation report → approval inbox → approve with
step-up MFA → outbox released; editing after approval invalidates it. Plus the I3 negative paths: no token,
forged token, self-approval, stale MFA.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import fakeredis.aioredis
import httpx
import jwt
import pytest
from sqlalchemy import text

from cortex.l6_agency import run_events
from cortex.l6_agency.orchestrator import run_council
from cortex.l7_governance import outbox as outbox_mod
from cortex.l8_actuation.api.app import create_app
from platform_core.auth import oidc
from platform_core.bus import streams
from platform_core.db import session_scope
from platform_core.policy import opa

pytestmark = pytest.mark.integration
KEY = "integration-approval-signing-key-0123456789"


@pytest.fixture
async def env(engine, verifier, opa_url, monkeypatch):
    monkeypatch.setenv("APPROVAL_SIGNING_KEY", KEY)
    sent: list[dict] = []
    monkeypatch.setattr(
        outbox_mod, "_smtp_send", lambda msg: sent.append({"to": msg["To"], "id": msg["Message-ID"]}) or "smtp://test"
    )
    oidc.set_verifier(verifier)
    opa.set_opa(opa.OPAClient(opa_url))
    streams.set_bus(streams.Bus(fakeredis.aioredis.FakeRedis()))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://t") as c:
        yield c, sent
    oidc.set_verifier(None)
    opa.set_opa(None)
    streams.set_bus(None)


async def _seed_high_opportunity() -> dict[str, str]:
    """A self-organisation profile and a grant that genuinely scores in the high band through the real scoring
    engine (so a later rescore, e.g. after a meeting, keeps it there)."""
    from cortex.l4_reasoning.score_service import score_opportunity

    now = datetime.now(UTC)
    ids = {k: str(uuid.uuid4()) for k in ("self", "cp", "opp")}
    src = json.dumps({"kind": "manual_entry", "entered_by": "integration"})
    profile = {
        "country": "US", "stage": "seed", "strategic_priorities": ["energy storage"], "sectors": ["energy"],
        "tech_tags": ["energy storage", "grid batteries", "research"], "esg_tags": ["climate"],
        "description": "Grid-scale energy storage research and batteries", "raise_target": {"min": 100000, "max": 400000, "currency": "USD"},
    }  # fmt: skip
    async with session_scope() as s:
        # the session-scoped database is shared with other tests: there is one self-organisation, use it
        existing = (
            await s.execute(text("SELECT id FROM organization WHERE kind = 'self' AND NOT is_demo LIMIT 1"))
        ).scalar()
        if existing:
            ids["self"] = str(existing)
            await s.execute(text("UPDATE organization SET profile = CAST(:p AS jsonb), country = 'US' WHERE id = :id"),
                            {"p": json.dumps(profile), "id": existing})  # fmt: skip
        else:
            await s.execute(
                text("INSERT INTO organization (id, name, normalized_name, kind, country, profile, source_ref) VALUES "
                     "(:id, 'Inspironics Test', 'inspironics test', 'self', 'US', CAST(:p AS jsonb), CAST(:src AS jsonb))"),
                {"id": ids["self"], "p": json.dumps(profile), "src": src},
            )  # fmt: skip
        await s.execute(
            text("INSERT INTO organization (id, name, normalized_name, kind, country, source_ref) VALUES "
                 "(:id, 'Quorvane Foundation', 'quorvane foundation', 'counterparty', 'US', CAST(:src AS jsonb))"),
            {"id": ids["cp"], "src": src},
        )  # fmt: skip
        await s.execute(
            text(
                "INSERT INTO opportunity (id, title, description, class, class_source, classification_confidence, counterparty_id, "
                "geography, stage_fit, sectors, esg_tags, amount_min, amount_max, currency, deadline, pipeline_stage, source_ref) VALUES "
                "(:id, 'Clean energy storage research grant', 'Non-dilutive grant for grid energy storage research and batteries', "
                "'grant', 'rule', 0.95, :cp, ARRAY['US'], ARRAY['seed'], ARRAY['energy_storage'], ARRAY['climate'], 100000, 400000, "
                "'USD', :dl, 'qualified', CAST(:src AS jsonb))"
            ),
            {"id": ids["opp"], "cp": ids["cp"], "dl": now + timedelta(days=45), "src": src},
        )
        c = await score_opportunity(s, ids["opp"])
    assert c.band == "high", (c.score, c.completeness, c.band_reason)
    return ids


async def test_phase2_definition_of_done(env, make_token, verifier):
    client, sent = env
    analyst_tok = make_token(["analyst"], sub="analyst-1", username="ana", auth_age=5)
    approver_tok = make_token(["approver"], sub="approver-1", username="apo", auth_age=5)
    ha = {"Authorization": f"Bearer {analyst_tok}"}
    hp = {"Authorization": f"Bearer {approver_tok}"}
    ids = await _seed_high_opportunity()

    # --- relationship memory: a consented contact and a meeting → warmth, a commitment milestone
    r = await client.post("/v1/contacts", headers=ha, json={"name": "Ines Quade", "organization_id": ids["cp"], "role": "Programme Manager",
                                                            "emails": ["ines@quorvane.example"], "consent_basis": "legitimate_interest"})  # fmt: skip
    assert r.status_code == 201, r.text
    contact = r.json()["id"]
    r = await client.post("/v1/meetings", headers=ha, json={
        "contact_ids": [contact], "occurred_at": (datetime.now(UTC) - timedelta(days=3)).isoformat(), "summary": "Intro call",
        "opportunity_id": ids["opp"], "commitments": [{"text": "Send eligibility letter", "by": "them"}], "next_steps": "Share deck",
    })  # fmt: skip
    assert r.status_code == 201, r.text
    assert len(r.json()["milestones"]) == 2
    tl = (await client.get(f"/v1/relationships/{contact}/timeline", headers=ha)).json()
    assert 0.6 < tl["warmth"] < 0.65 and any(e["type"] == "interaction" for e in tl["events"])

    # --- council run: queued by the analyst, executed as the worker does (under the analyst's verified token)
    r = await client.post("/v1/agents/run", headers=ha, json={"opportunity_id": ids["opp"]})
    assert r.status_code == 202, r.text
    run_id = r.json()["run_id"]
    envelopes = await streams.get_bus().r.xrange("agents.jobs")
    assert len(envelopes) == 1 and json.loads(envelopes[0][1][b"payload"])["run_id"] == run_id
    result = await run_council(run_id, verifier.verify_sync(analyst_tok))
    assert result["status"] in ("succeeded", "partial"), result
    positions = [e for _, e in await run_events.read(run_id, "0", block_ms=1) if e["type"] == "agent.position"]
    assert result["stance"] == "pursue" and result["approval_id"] and result["outbox_id"], [
        (p["agent"], p["stance"], p["blockers"], p["citation"], p["error"]) for p in positions
    ]

    # --- live stream: every stage of the deliberation was emitted, in order
    events = [e for _, e in await run_events.read(run_id, "0", block_ms=1)]
    types = [e["type"] for e in events]
    for t in ("run.started", "plan", "agent.started", "tool.result", "agent.position", "converge", "citation.result", "policy",
              "approval.requested", "run.finished"):  # fmt: skip
        assert t in types, (t, types)
    assert (
        types.index("plan") < types.index("converge") < types.index("approval.requested") < types.index("run.finished")
    )
    plan = next(e for e in events if e["type"] == "plan")
    assert {"grant", "relationship", "forecasting"} <= {a["name"] for a in plan["agents"]}
    positions = [e for e in events if e["type"] == "agent.position"]
    assert all(p["mode"] == "deterministic" for p in positions), "no LLM configured → labelled deterministic mode"
    assert all(c["evidence"] or c["basis"] for p in positions for c in p["claims"])

    # --- recommendation: explainable at creation (I2), every claim verified (I1/I7)
    rec = (await client.get(f"/v1/recommendations/{result['recommendation_id']}", headers=ha)).json()
    assert rec["evidence"] and rec["reasoning"]["positions"] and rec["citation_report"]["status"] in ("pass", "gaps")
    assert rec["citation_report"]["passed"] >= 3 and rec["status"] == "pending_approval"
    assert rec["inference_id"], "the recommendation is a declared inference over its evidence refs"

    # --- approval inbox
    inbox = (await client.get("/v1/approvals", headers=hp)).json()
    item = next(i for i in inbox["items"] if i["id"] == result["approval_id"])
    assert item["channel"] == "email" and item["outbox_status"] == "pending"
    det = (await client.get(f"/v1/approvals/{result['approval_id']}", headers=hp)).json()
    assert det["content_current"] and det["citation_report"]["status"] in ("pass", "gaps")
    assert "outbound_requires_approval" in det["policy_result"]["deny"], "before any decision, policy denies release"

    # --- I3: the requester can't approve their own request; stale auth needs step-up; no token → blocked
    self_try = await client.post(
        f"/v1/approvals/{result['approval_id']}/decision", headers=ha, json={"decision": "approved"}
    )
    assert self_try.status_code == 403
    stale = make_token(["approver"], sub="approver-1", username="apo", auth_age=3600)
    r = await client.post(f"/v1/approvals/{result['approval_id']}/decision", headers={"Authorization": f"Bearer {stale}"},
                          json={"decision": "approved"})  # fmt: skip
    assert r.status_code == 403 and r.json()["step_up"] is True
    r = await client.post(f"/v1/outbox/{result['outbox_id']}/send", headers=hp)
    assert r.json()["status"] == "blocked" and "outbound_requires_approval" in r.json()["reasons"]
    # blocked → re-request (the analyst) → approve (the approver, fresh MFA) → released
    r = await client.post(f"/v1/outbox/{result['outbox_id']}/request-approval", headers=ha)
    approval_id = r.json()["approval_id"]
    r = await client.post(
        f"/v1/approvals/{approval_id}/decision", headers=hp, json={"decision": "approved", "comment": "ok"}
    )
    assert r.status_code == 200 and r.json()["status"] == "approved" and r.json()["release"] == "queued", r.text
    rel = [e for e in await streams.get_bus().r.xrange("system.jobs") if b"outbox.release" in e[1][b"type"]]
    assert rel, "auto-release job queued under the approver's token"
    out = await outbox_mod.release(verifier.verify_sync(approver_tok), result["outbox_id"])
    assert out["status"] == "sent", out
    assert sent and sent[0]["to"] == "ines@quorvane.example" and result["outbox_id"] in sent[0]["id"]
    async with session_scope() as s:
        row = (await s.execute(text("SELECT token_used_at FROM approval WHERE id = :id"), {"id": approval_id})).scalar()
        assert row is not None, "the token is single-use"
    r = await client.patch(
        f"/v1/outbox/{result['outbox_id']}", headers=ha, json={"payload": {"to": "x@y.co", "body": "late"}}
    )
    assert r.status_code == 409, "a sent item is immutable"

    # --- editing after approval invalidates it (second draft, via the recommendation's export path)
    r = await client.post("/v1/outbox", headers=ha, json={"channel": "email", "opportunity_id": ids["opp"],
                                                         "payload": {"to": "ines@quorvane.example", "subject": "Hi", "body": "v1"}})  # fmt: skip
    oid = r.json()["id"]
    aid = (await client.post(f"/v1/outbox/{oid}/request-approval", headers=ha)).json()["approval_id"]
    assert (await client.post(f"/v1/approvals/{aid}/decision", headers=hp, json={"decision": "approved"})).json()[
        "status"
    ] == "approved"
    r = await client.patch(
        f"/v1/outbox/{oid}",
        headers=ha,
        json={"payload": {"to": "ines@quorvane.example", "subject": "Hi", "body": "v2"}},
    )
    assert r.json() == {"id": oid, "status": "draft", "approval_invalidated": True}
    async with session_scope() as s:
        d = (await s.execute(text("SELECT decision FROM approval WHERE id = :id"), {"id": aid})).scalar()
    assert d == "invalidated"
    r = await client.post(f"/v1/outbox/{oid}/send", headers=hp)
    assert r.json()["status"] == "blocked"

    # --- a forged token (right subject and hash, wrong key) is refused
    aid2 = (await client.post(f"/v1/outbox/{oid}/request-approval", headers=ha)).json()["approval_id"]
    assert (await client.post(f"/v1/approvals/{aid2}/decision", headers=hp, json={"decision": "approved"})).json()[
        "status"
    ] == "approved"
    async with session_scope() as s:
        good = (await s.execute(text("SELECT approval_token FROM outbox WHERE id = :id"), {"id": oid})).scalar()
        claims = jwt.decode(good, KEY, algorithms=["HS256"], audience="cortex-outbox")
        forged = jwt.encode(claims, "attacker-key-attacker-key-attacker-key", algorithm="HS256")
        await s.execute(text("UPDATE outbox SET approval_token = :t WHERE id = :id"), {"t": forged, "id": oid})
    r = await client.post(f"/v1/outbox/{oid}/send", headers=hp)
    assert r.json()["status"] == "blocked" and "approval_token_invalid" in r.json()["reasons"]

    # --- audit: every step recorded and the chain intact
    audit_h = {"Authorization": f"Bearer {make_token(['auditor'], auth_age=5)}"}
    actions = {i["action"] for i in (await client.get("/v1/audit?limit=200", headers=audit_h)).json()["items"]}
    assert {"council.run.requested", "recommendation.created", "approval.requested", "approval.approved", "outbox.sent",
            "outbox.blocked", "outbox.edited"} <= actions  # fmt: skip
    assert (await client.get("/v1/audit/verify", headers=audit_h)).json()["ok"] is True


async def test_alerts_and_outcomes_feedback_edge(env, make_token):
    client, _ = env
    h = {"Authorization": f"Bearer {make_token(['admin', 'approver'], sub='admin-1', auth_age=5)}"}
    ids = await _seed_high_opportunity()
    r = await client.post("/v1/milestones", headers=h, json={"kind": "follow_up", "title": "Chase eligibility letter",
                                                            "due_at": (datetime.now(UTC) - timedelta(days=2)).isoformat(),
                                                            "opportunity_id": ids["opp"]})  # fmt: skip
    assert r.status_code == 201
    out = (await client.post("/v1/alerts/evaluate", headers=h)).json()
    assert (
        out["created"] >= 2
    )  # deadline T-60 bucket is outside 30 → only when ≤ 30; the overdue follow-up + new high opp
    feed = (await client.get("/v1/alerts", headers=h)).json()
    kinds = {a["kind"] for a in feed["items"]}
    assert {"follow_up", "new_opp"} <= kinds
    again = (await client.post("/v1/alerts/evaluate", headers=h)).json()
    assert again["created"] == 0, "dedup: re-evaluation never duplicates alerts"
    fu = next(a for a in feed["items"] if a["kind"] == "follow_up")
    assert (await client.post(f"/v1/alerts/{fu['id']}/ack", headers=h)).json()["status"] == "acked"
    # outcome on the L8→L1 edge: realised label, opportunity closed, retrain flagged
    r = await client.post(
        "/v1/outcomes", headers=h, json={"opportunity_id": ids["opp"], "result": "won", "amount": 250000}
    )
    assert r.status_code == 201 and r.json()["label_source"] == "realised"
    assert (
        await client.post("/v1/outcomes", headers=h, json={"opportunity_id": ids["opp"], "result": "won"})
    ).status_code == 422
    # one realised outcome per opportunity: a contradicting second label is refused, not stored
    r = await client.post("/v1/outcomes", headers=h, json={"opportunity_id": ids["opp"], "result": "lost"})
    assert r.status_code == 409, r.text
    assert len((await client.get(f"/v1/outcomes?opportunity_id={ids['opp']}", headers=h)).json()["items"]) == 1
    assert await streams.get_bus().r.get("ml:retrain_needed")
    r = await client.post("/v1/ml/models/train", headers=h, json={"demo": False})
    assert r.status_code == 422 and "realised" in r.json()["detail"], (
        "one outcome is not enough to train, and it says so"
    )
    cal = (await client.get("/v1/calendar/events", headers=h)).json()
    assert any(e["type"] == "follow_up" for e in cal["events"])
    ics = await client.get("/v1/calendar/export.ics", headers=h)
    assert ics.status_code == 200 and "BEGIN:VCALENDAR" in ics.text
