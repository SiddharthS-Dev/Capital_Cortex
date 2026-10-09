"""Regressions for the 2026-10-08 audit on the real Postgres and OPA: the author of content can't approve it
(segregation of duties beyond the requester), and a human edit of a recommendation is citation-checked before
it can go for approval."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from cortex.l6_agency.orchestrator import run_council
from cortex.l7_governance import outbox as outbox_mod
from cortex.l8_actuation import alerts as alerts_mod
from platform_core.auth import oidc
from platform_core.config import get_settings
from platform_core.db import session_scope
from tests.integration.test_phase2_flow import _seed_high_opportunity, env  # noqa: F401 (fixture)

pytestmark = pytest.mark.integration


async def test_author_cannot_approve_own_draft(env, make_token):  # noqa: F811
    client, _ = env
    admin = {"Authorization": f"Bearer {make_token(['admin'], sub='admin-1', username='adm', auth_age=5)}"}
    analyst = {"Authorization": f"Bearer {make_token(['analyst'], sub='analyst-1', username='ana', auth_age=5)}"}
    approver = {"Authorization": f"Bearer {make_token(['approver'], sub='approver-1', username='apo', auth_age=5)}"}
    r = await client.post("/v1/outbox", headers=admin, json={"channel": "email", "payload": {
        "to": "partner@example.org", "subject": "Hello", "body": "Following up on our call."}})  # fmt: skip
    assert r.status_code in (200, 201), r.text
    oid = r.json()["id"]
    r = await client.post(f"/v1/outbox/{oid}/request-approval", headers=analyst)
    aid = r.json()["approval_id"]
    r = await client.post(f"/v1/approvals/{aid}/decision", headers=admin, json={"decision": "approved"})
    assert r.status_code == 403 and "author_approval_denied" in r.json()["reasons"], r.text
    r = await client.post(f"/v1/approvals/{aid}/decision", headers=approver, json={"decision": "approved"})
    assert r.status_code == 200 and r.json()["status"] == "approved", r.text


async def test_recommendation_edit_is_citation_checked(env, make_token, verifier):  # noqa: F811
    client, _ = env
    analyst_tok = make_token(["analyst"], sub="analyst-1", username="ana", auth_age=5)
    ha = {"Authorization": f"Bearer {analyst_tok}"}
    ids = await _seed_high_opportunity()
    r = await client.post("/v1/agents/run", headers=ha, json={"opportunity_id": ids["opp"]})
    result = await run_council(r.json()["run_id"], verifier.verify_sync(analyst_tok))
    rid = result["recommendation_id"]
    rec = (await client.get(f"/v1/recommendations/{rid}", headers=ha)).json()

    # an invented figure and investor: the edit is stored, but its report says so and approval is refused
    r = await client.patch(f"/v1/recommendations/{rid}", headers=ha,
                           json={"text": "Valuation cap $40,000,000 agreed with Zyxwv Capital."})  # fmt: skip
    assert r.status_code == 200 and r.json()["citation_status"] != "pass", r.text
    assert any("Zyxwv Capital" in x or "40,000,000" in x for x in r.json()["citation_problems"])
    stored = (await client.get(f"/v1/recommendations/{rid}", headers=ha)).json()["citation_report"]
    assert stored["human_edit"] and stored["status"] != "pass"
    r = await client.post(f"/v1/recommendations/{rid}/approve", headers=ha)
    assert r.status_code == 409, r.text

    # rewording that sticks to the cited records passes and can go for approval again
    supported = rec["claims"][0]["text"]
    r = await client.patch(f"/v1/recommendations/{rid}", headers=ha, json={"text": supported})
    assert r.json()["citation_status"] == "pass", r.json()
    r = await client.post(f"/v1/recommendations/{rid}/approve", headers=ha)
    assert r.status_code == 200, r.text


async def _approved_email(client, make_token, to: str = "partner@example.org") -> tuple[str, object]:
    admin = {"Authorization": f"Bearer {make_token(['admin'], sub='admin-1', username='adm', auth_age=5)}"}
    analyst = {"Authorization": f"Bearer {make_token(['analyst'], sub='analyst-1', username='ana', auth_age=5)}"}
    approver_tok = make_token(["approver"], sub="approver-1", username="apo", auth_age=5)
    r = await client.post("/v1/outbox", headers=admin, json={"channel": "email", "payload": {
        "to": to, "subject": "Hello", "body": "Following up on our call."}})  # fmt: skip
    oid = r.json()["id"]
    aid = (await client.post(f"/v1/outbox/{oid}/request-approval", headers=analyst)).json()["approval_id"]
    r = await client.post(f"/v1/approvals/{aid}/decision", headers={"Authorization": f"Bearer {approver_tok}"},
                          json={"decision": "approved", "release": "manual"})  # fmt: skip
    assert r.json()["status"] == "approved", r.text
    return oid, oidc.get_verifier().verify_sync(approver_tok)


async def test_outbox_delivers_at_most_once(env, make_token, monkeypatch):  # noqa: F811
    client, sent = env
    # a timeout while the message was being handed over: it may have gone, so it is never retried automatically
    oid, approver = await _approved_email(client, make_token)
    calls: list = []

    def timed_out(msg):
        calls.append(msg)
        raise outbox_mod.DeliveryFailed("SMTP delivery failed: timed out", maybe_delivered=True)

    monkeypatch.setattr(outbox_mod, "_smtp_send", timed_out)
    out = await outbox_mod.release(approver, oid)
    assert out["status"] == "blocked" and out["reasons"] == ["delivery_outcome_unknown"], out
    out = await outbox_mod.release(approver, oid)
    assert out["status"] == "blocked" and len(calls) == 1, "a blocked item is never sent again"

    # a sender that died mid-delivery leaves its claim behind: after the in-flight window it blocks, never resends
    oid, approver = await _approved_email(client, make_token, "other@example.org")
    since = (datetime.now(UTC) - timedelta(seconds=outbox_mod.IN_FLIGHT_SECONDS + 60)).isoformat()
    async with session_scope() as s:
        await s.execute(text("UPDATE outbox SET delivery = CAST(:d AS jsonb) WHERE id = CAST(:id AS uuid)"),
                        {"d": json.dumps({"state": "sending", "since": since}), "id": oid})  # fmt: skip
    out = await outbox_mod.release(approver, oid)
    assert out["status"] == "blocked" and out["reasons"] == ["delivery_outcome_unknown"] and len(calls) == 1, out

    # a clean refusal sent nothing: retryable, and the next attempt delivers exactly once
    oid, approver = await _approved_email(client, make_token, "third@example.org")

    def refused(msg):
        raise outbox_mod.DeliveryFailed("SMTP delivery refused: 451")

    monkeypatch.setattr(outbox_mod, "_smtp_send", refused)
    out = await outbox_mod.release(approver, oid)
    assert out["status"] == "approved" and out["retryable"], out
    monkeypatch.setattr(outbox_mod, "_smtp_send", lambda msg: sent.append({"to": msg["To"]}) or "smtp://test")
    n = len(sent)
    assert (await outbox_mod.release(approver, oid))["status"] == "sent"
    assert (await outbox_mod.release(approver, oid)).get("already") and len(sent) == n + 1


async def test_failing_alert_rule_does_not_resend_other_alerts(env, make_token, monkeypatch):  # noqa: F811
    client, _ = env
    admin = {"Authorization": f"Bearer {make_token(['admin'], sub='admin-1', username='adm', auth_age=5)}"}
    await _seed_high_opportunity()
    st = get_settings()
    monkeypatch.setattr(st, "smtp_url", "smtp://mail.test:25")
    monkeypatch.setattr(st, "internal_email_domains", ["inspironics.net"])
    monkeypatch.setattr(alerts_mod, "alerts_config", lambda: {"internal_recipients": ["ops@inspironics.net"]})
    mails: list = []
    monkeypatch.setattr(alerts_mod, "_email", lambda to, subject, body: mails.append(subject))
    async with session_scope() as s:
        # sorts first and fails in SQL (malformed array literal): it must not abort the other rules' transaction
        for name, kind, expr, channels in (
            ("AAA broken deadline", "deadline", {"bands": "high"}, ["in_app"]),
            (
                "AAB new high with e-mail",
                "new_opp",
                {"min_score": 0.0, "within_hours": 48},
                ["in_app", "internal_email"],
            ),
        ):
            await s.execute(text(
                "INSERT INTO alert_rule (org_id, name, kind, severity, channels, rule_expr, enabled) "
                "VALUES (:org, :n, :k, 'info', :ch, CAST(:e AS jsonb), true)"),
                {"org": st.org_id, "n": name, "k": kind, "ch": channels, "e": json.dumps(expr)})  # fmt: skip
    first = (await client.post("/v1/alerts/evaluate", headers=admin)).json()
    assert first["created"] >= 1 and len(mails) >= 1 and first["delivered"] == len(mails), first
    n = len(mails)
    again = (await client.post("/v1/alerts/evaluate", headers=admin)).json()
    assert again["created"] == 0 and len(mails) == n, "a committed alert is never e-mailed again"


async def test_saved_forecasts_use_real_data_unless_asked(env, make_token):  # noqa: F811
    client, _ = env
    finance = {"Authorization": f"Bearer {make_token(['admin'], sub='admin-1', username='adm', auth_age=5)}"}
    async with session_scope() as s:
        await s.execute(text("DELETE FROM financial_snapshot"))
        for m in range(1, 7):  # demo financials only
            await s.execute(text(
                "INSERT INTO financial_snapshot (period, cash, revenue, opex, net_burn, currency, source_ref, is_demo) "
                "VALUES (make_date(2026, :m, 1), 900000, 10000, 60000, 50000, 'USD', '{\"kind\": \"synthetic_seed\"}', true)"),
                {"m": m})  # fmt: skip
    real = (await client.post("/v1/forecasts", headers=finance)).json()
    assert {r["status"] for r in real["results"]} == {"insufficient_data"}, "demo snapshots never feed a real forecast"
    demo = (await client.post("/v1/forecasts", headers=finance, json={"include_demo": True})).json()
    assert {r["status"] for r in demo["results"]} == {"ok"}
    rows = {x["id"]: x["is_demo"] for x in (await client.get("/v1/forecasts", headers=finance)).json()["items"]}
    assert not any(rows[i] for i in real["ids"]) and all(rows[i] for i in demo["ids"])
