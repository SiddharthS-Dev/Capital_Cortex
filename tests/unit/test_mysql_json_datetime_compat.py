"""Regression tests for the MySQL JSON/DATETIME compatibility defects (H1–H12, docs/archive/migration-history/CORTEX_MYSQL_BLOCKER_CLOSURE_REGISTER.md).

Root cause: on MySQL (asyncmy) a JSON column read with text() SQL arrives as its *text*, and DATETIME arrives *naive*;
PostgreSQL jsonb/timestamptz arrive decoded/aware. Code written for PostgreSQL then iterated characters, double-encoded
documents or mixed naive and aware datetimes.

Part A tests the shared helpers (no database). Part B runs against the configured MySQL unit database (MYSQL_TEST_*,
e.g. MYSQL_TEST_DATABASE=cortex_unit) inside a transaction that is always rolled back.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.auth.principal import Principal
from platform_core.db.session import create_engine_from_url, get_mysql_test_url, reset_engine
from platform_core.jsonutil import as_utc, json_obj

ORG = "00000000-0000-0000-0000-000000000001"
P = Principal(sub="usr_compat_test", username="compat@cortex.internal", roles=frozenset(["admin"]), token="t")


# ----------------------------------------------------------------------------- A. helpers
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ('{"a": 1}', {"a": 1}),
        ("[]", []),
        ("{}", {}),
        ('["admin", "approver"]', ["admin", "approver"]),
        ('{"n": null, "b": true, "f": false, "i": 3, "x": 0.72, "s": "t", "l": [1, {"k": [null]}]}',
         {"n": None, "b": True, "f": False, "i": 3, "x": 0.72, "s": "t", "l": [1, {"k": [None]}]}),
        ('"pursue"', "pursue"),
        ("0.72", 0.72),
        ("null", None),
        (b'["a"]', ["a"]),
        (["already", "decoded"], ["already", "decoded"]),  # PostgreSQL jsonb
        ({"k": 1}, {"k": 1}),
    ],
)  # fmt: skip
def test_json_obj_decodes_text_and_passes_decoded_values(raw, expected):
    assert json_obj(raw) == expected


def test_json_obj_null_and_default():
    assert json_obj(None) is None
    assert json_obj(None, []) == []
    assert json_obj("[]", ["x"]) == []  # default only replaces SQL NULL, not an empty document


def test_json_obj_never_double_decodes_or_encodes():
    doc = {"status": "pass", "claims": [{"id": 1}]}
    once = json.dumps(doc)
    assert json_obj(once) == doc
    assert json.dumps(json_obj(once)) == once  # storing the decoded value again yields the same text


def test_json_obj_malformed_raises():
    with pytest.raises(ValueError):
        json_obj("{not json")


def test_json_obj_large_nested_document():
    doc: dict = {"v": 0}
    cur = doc
    for i in range(200):
        cur["c"] = {"v": i, "arr": list(range(50))}
        cur = cur["c"]
    assert json_obj(json.dumps(doc)) == doc


def test_as_utc():
    naive = datetime(2026, 11, 4, 10, 0, 0)
    assert as_utc(naive) == datetime(2026, 11, 4, 10, 0, 0, tzinfo=UTC)  # tagged, not shifted
    ist = datetime(2026, 11, 4, 15, 30, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    assert as_utc(ist) == datetime(2026, 11, 4, 10, 0, tzinfo=UTC) and as_utc(ist).tzinfo == UTC
    assert as_utc(date(2026, 11, 4)) == date(2026, 11, 4)  # date-only fields unchanged
    assert as_utc(None) is None
    # comparable/sortable with aware values after normalisation (the timeline bug)
    assert sorted([as_utc(naive), datetime(2026, 1, 1, tzinfo=UTC)])[0].year == 2026


# ----------------------------------------------------------------------------- B. MySQL
def _generate_source() -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parents[2] / "seed" / "generate.py").read_text(encoding="utf-8")


@pytest.fixture
async def s():
    engine = create_engine_from_url(get_mysql_test_url(driver="asyncmy"), pool_size=2, max_overflow=0)
    reset_engine(engine)
    async with engine.connect() as conn:
        tx = await conn.begin()
        session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint")
        # rows below reference parents that need not exist; FK checks are restored before the connection is closed
        await session.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        try:
            yield session
        finally:
            await session.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
            await session.close()
            await tx.rollback()
    reset_engine(None)
    await engine.dispose()


async def test_driver_facts_the_fixes_rely_on(s: AsyncSession):
    r = (
        (
            await s.execute(
                text(
                    "SELECT CAST('[1]' AS JSON) AS j, CAST('2026-11-04 10:00:00' AS DATETIME) AS d, @@session.time_zone AS tz"
                )
            )
        )
        .mappings()
        .one()
    )
    assert isinstance(r["j"], str)  # JSON arrives as text on MySQL
    assert r["d"].tzinfo is None  # DATETIME arrives naive
    assert r["tz"] == "+00:00"  # as_utc() relies on the server storing UTC


async def _decision(s: AsyncSession, approval_id: str, approver: str, roles: list[str]) -> None:
    await s.execute(
        text(
            "INSERT INTO approval_decision (approval_id, approver_id, approver_username, roles, grants, mfa, decision, "
            "comment, content_hash, created_at) VALUES (:a, :ap, :ap, :r, JSON_ARRAY(), true, 'approved', NULL, 'h', NOW())"
        ),
        {"a": approval_id, "ap": approver, "r": json.dumps(roles)},
    )


async def test_h2_decisions_return_real_role_lists(s: AsyncSession):
    from cortex.l7_governance.approval_service import _decisions, _opa_approvals

    aid = str(uuid.uuid4())
    await _decision(s, aid, "usr_admin", ["admin"])
    ds = await _decisions(s, aid)
    assert ds[0]["roles"] == ["admin"] and ds[0]["grants"] == []
    assert _opa_approvals(ds)[0]["roles"] == ["admin"]  # previously ['[', '"', 'a', ...]


@pytest.fixture
async def real_opa():
    """The real OPA (no mock), skipped if unreachable. The OPA client is process-wide and bound to the event loop that
    created it: reset it before and after, so neither this test nor a later one reuses a client from a closed loop."""
    import httpx

    from platform_core.config import get_settings
    from platform_core.policy import opa

    opa.set_opa(None)
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            (await c.get(f"{get_settings().opa_url}/health")).raise_for_status()
    except Exception as e:
        pytest.skip(f"OPA not reachable for the policy round-trip: {type(e).__name__}")
    try:
        yield
    finally:
        opa.set_opa(None)


async def _financial_terms_reasons(s: AsyncSession, approvals: list[tuple[str, list[str]]]) -> list[str]:
    from cortex.l7_governance.approval_service import _decisions, _opa_approvals
    from cortex.l7_governance.policy_engine import evaluate_release, release_input

    aid = str(uuid.uuid4())
    for who, roles in approvals:
        await _decision(s, aid, who, roles)
    inp = release_input(
        kind="internal", channel=None, subject_type="recommendation", recipient_external=False, digest="h",
        flags={"contains_financial_terms": True}, approvals=_opa_approvals(await _decisions(s, aid)),
        requested_by="usr_requester",
    )  # fmt: skip
    return [r for r in (await evaluate_release(inp)).reasons if r == "financial_terms_require_admin_and_legal"]


async def test_h2_financial_terms_permitted_with_admin_and_legal(s: AsyncSession, real_opa):
    reasons = await _financial_terms_reasons(s, [("usr_admin", ["admin"]), ("usr_legal", ["auditor", "approver"])])
    assert reasons == []  # was always denied on MySQL


async def test_h2_financial_terms_still_forbidden_without_admin(s: AsyncSession, real_opa):
    reasons = await _financial_terms_reasons(s, [("usr_a", ["analyst"]), ("usr_legal", ["auditor", "approver"])])
    assert reasons  # boundary preserved: no admin → denied


async def test_h2_financial_terms_still_forbidden_without_legal(s: AsyncSession, real_opa):
    assert await _financial_terms_reasons(s, [("usr_admin", ["admin"])])


async def test_h5_runs_return_decoded_stance_and_confidence(s: AsyncSession):
    from cortex.l8_actuation.api.routers.agents import runs

    opp = str(uuid.uuid4())
    await s.execute(
        text(
            "INSERT INTO agent_run (id, org_id, agent, task, opportunity_id, status, output) VALUES (:id, :org, 'council', "
            "'council', :opp, 'succeeded', :out)"
        ),
        {"id": str(uuid.uuid4()), "org": ORG, "opp": opp, "out": json.dumps({"stance": "pursue", "confidence": 0.72})},
    )
    items = (await runs(opportunity_id=opp, limit=5, _=P, session=s))["items"]
    assert items[0]["stance"] == "pursue" and items[0]["confidence"] == 0.72


async def test_h3_h4_h7_h8_h9_h10_h11_columns_decode_to_documents(s: AsyncSession):
    """Each fixed call site decodes its column with json_obj; prove the stored MySQL values decode to the documents the
    code indexes/iterates (and that '[]' is empty, which the old truthiness checks got wrong)."""
    docs = [
        ({"recommendation": "x", "k": [1]}, dict),  # H3 outbox.payload
        ({"status": "pass", "claims": []}, dict),  # H4 citation_report
        (["a@example.org"], list),  # H7 contact.emails
        ([], list),  # H7 empty -> falsy
        ({"rate": 0.05, "tenor": 36}, dict),  # H8 terms
        (["seed", "series_a"], list),  # H8 investor.stages
        (["financials", "legal"], list),  # H8/H11 dd_tags
        ({"auc": 0.8, "brier": 0.2}, dict),  # H9 metrics
        ({"note": "v", "n": None}, dict),  # H10 memory.value
    ]
    for v, typ in docs:
        raw = (await s.execute(text("SELECT CAST(:v AS JSON)"), {"v": json.dumps(v)})).scalar()
        assert isinstance(raw, str)
        assert json_obj(raw) == v and isinstance(json_obj(raw), typ)
    assert not json_obj((await s.execute(text("SELECT CAST('[]' AS JSON)"))).scalar())


async def test_h12_seed_never_overwrites_an_existing_period(s: AsyncSession):
    """generate.py's MySQL snapshot insert must behave like PostgreSQL ON CONFLICT DO NOTHING."""
    src = _generate_source()
    assert "ON DUPLICATE KEY UPDATE id = id" in src and "cash = VALUES(cash)" not in src
    period = date(1999, 1, 1)
    ins = (
        "INSERT INTO financial_snapshot (org_id, period, cash, revenue, opex, net_burn, currency, source_ref, is_demo) "
        "VALUES (:org, :p, :c, 1, 1, 0, 'USD', CAST('{\"kind\": \"test\"}' AS JSON), :demo) ON DUPLICATE KEY UPDATE id = id"
    )
    await s.execute(text(ins), {"org": ORG, "p": period, "c": 111, "demo": False})  # a real figure
    await s.execute(text(ins), {"org": ORG, "p": period, "c": 999, "demo": True})  # the seed's attempt
    cash = (
        await s.execute(
            text("SELECT cash FROM financial_snapshot WHERE org_id = :org AND period = :p"), {"org": ORG, "p": period}
        )
    ).scalar()
    assert float(cash) == 111.0


async def test_h6_dashboard_deadline_naive_datetime(s: AsyncSession):
    """The executive dashboard subtracts the deadline from an aware now(): a naive MySQL DATETIME must be read as UTC."""
    raw = (await s.execute(text("SELECT CAST('2026-11-10 00:00:00' AS DATETIME)"))).scalar()
    with pytest.raises(TypeError):
        _ = raw - datetime.now(UTC)  # the original defect
    assert isinstance((as_utc(raw) - datetime(2026, 11, 4, tzinfo=UTC)).days, int)


async def test_h1_idempotency_key_replays_on_mysql(monkeypatch):
    """H1: the MySQL lookup/insert quoted `key` (reserved word, error 1064 → every Idempotency-Key POST returned 500)
    and the replay returned the stored JSON as a string. Real middleware + MySQL; only token verification is stubbed."""
    import httpx
    from fastapi import FastAPI

    from platform_core import idempotency

    sub = f"usr_idem_{uuid.uuid4().hex[:8]}"

    class _Verifier:
        async def verify(self, _token: str) -> Principal:
            return Principal(sub=sub, username="idem@test", roles=frozenset(["analyst"]), token="t")

    monkeypatch.setattr(idempotency, "get_verifier", lambda: _Verifier())
    calls = {"n": 0}
    app = FastAPI()
    app.add_middleware(idempotency.IdempotencyMiddleware)

    @app.post("/v1/echo", status_code=201)
    async def echo(body: dict) -> dict:
        calls["n"] += 1
        return {"n": calls["n"], "body": body, "nested": {"ok": True, "none": None}}

    engine = create_engine_from_url(get_mysql_test_url(driver="asyncmy"), pool_size=2, max_overflow=0)
    reset_engine(engine)
    try:
        h = {"authorization": "Bearer t", "idempotency-key": "k-1"}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            first = await c.post("/v1/echo", json={"a": 1}, headers=h)
            again = await c.post("/v1/echo", json={"a": 1}, headers=h)
            other = await c.post("/v1/echo", json={"a": 2}, headers=h)
        assert first.status_code == 201 and again.status_code == 201
        assert again.headers.get("idempotent-replay") == "true"
        assert again.json() == first.json() == {"n": 1, "body": {"a": 1}, "nested": {"ok": True, "none": None}}
        assert calls["n"] == 1  # the replay did not run the endpoint again
        assert other.status_code == 422  # same key, different body
    finally:
        async with engine.begin() as conn:
            await conn.execute(text("DELETE FROM api_idempotency WHERE principal = :p"), {"p": sub})
        reset_engine(None)
        await engine.dispose()
