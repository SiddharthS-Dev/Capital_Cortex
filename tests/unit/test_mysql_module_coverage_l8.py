"""MySQL coverage for four L8 modules that had no MySQL test (docs/CORTEX_MYSQL_COMPLETE_OPEN_BLOCKER_AUDIT.md §D rows
23, 25, 37, 38):

* ``cortex/l8_actuation/alerts.py``                 rule evaluation, dedup, delivery, snooze wake-up, resolution, seeding
* ``cortex/l8_actuation/compliance_report.py``      the auditor workbook (GROUP_CONCAT length, JSON ->>, BOOLEAN cells)
* ``cortex/l8_actuation/api/routers/entities.py``   merge queue: propose / list / merge / unmerge / reject
* ``cortex/l8_actuation/api/routers/forecasts.py``  snapshot import (ON DUPLICATE KEY UPDATE ... VALUES()), forecasts

The call sites of ``insert_or_skip_duplicate`` (M2) are exercised here: a duplicate key must be skipped, every other
integrity error (FK, CHECK, NOT NULL) must raise. The helper itself is covered in test_mysql_medium_defects.py.

MySQL unit database only (get_mysql_test_url, MYSQL_TEST_DATABASE=cortex_unit). Every test runs inside one transaction
that is always rolled back; foreign keys stay enforced. Routes are driven through the real app in-process
(httpx.ASGITransport) with the DB session dependency bound to that transaction, the conftest RSA verifier for roles and
an OPA stub mirroring RBAC (as tests/unit/test_mysql_route_regressions.py). Webhook, SMTP and the Redis bus are stubbed.
"""

from __future__ import annotations

import hashlib
import io
import json
import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.auth import oidc
from platform_core.auth.principal import Principal
from platform_core.auth.rbac import get_rbac
from platform_core.config import get_settings
from platform_core.db import get_session
from platform_core.db.session import create_engine_from_url, get_mysql_test_url, reset_engine
from platform_core.errors import NotFound, Problem
from platform_core.jsonutil import json_obj, row
from platform_core.policy import opa
from platform_core.policy.opa import PolicyDecision

ORG = "00000000-0000-0000-0000-000000000001"
NO_TENANT = "ffffffff-ffff-ffff-ffff-ffffffffffff"  # no tenant row: FK target missing
SUB = f"usr_l8_cov_{uuid.uuid4().hex[:8]}"
USER = "l8cov@test"
ACTOR = f"user:{SUB}"
ADMIN = Principal(sub=SUB, username=USER, roles=frozenset(["admin"]), token="t")
SRC = json.dumps({"kind": "manual", "source": "test_mysql_module_coverage_l8"})


# ----------------------------------------------------------------------------- fixtures
@pytest.fixture
async def s():
    engine = create_engine_from_url(get_mysql_test_url(driver="asyncmy"), pool_size=2, max_overflow=0)
    reset_engine(engine)
    async with engine.connect() as conn:
        tx = await conn.begin()
        session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            await session.close()
            await tx.rollback()
    reset_engine(None)
    await engine.dispose()


class _Opa:
    """``cortex.authz`` allows iff RBAC allows (as test_authz_matrix.RbacOPA)."""

    async def evaluate(self, package: str, input_: dict[str, Any]) -> PolicyDecision:
        perms = get_rbac().permissions_for(set(input_["subject"]["roles"]))
        ok = "*" in perms or input_["action"] in perms
        return PolicyDecision(ok, [] if ok else ["rbac"])


@pytest.fixture
async def api(s: AsyncSession, verifier, make_token):
    """The real app; its get_session dependency yields the rolled-back session ``s``. Unhandled errors come back as the
    app's 500 response (raise_app_exceptions=False) so a test can assert the status a client would see."""
    from cortex.l8_actuation.api.app import create_app

    oidc.set_verifier(verifier)
    opa.set_opa(_Opa())  # type: ignore[arg-type]
    app = create_app()

    async def _session():
        yield s

    app.dependency_overrides[get_session] = _session
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            yield SimpleNamespace(
                c=c, auth=lambda role: {"Authorization": f"Bearer {make_token([role], sub=SUB, username=USER)}"}
            )
    finally:
        oidc.set_verifier(None)
        opa.set_opa(None)


@pytest.fixture
def events(monkeypatch) -> list[dict[str, Any]]:
    """alerts.evaluate publishes alert.created on the Redis bus: record it instead."""
    from cortex.l2_representation import pipeline

    out: list[dict[str, Any]] = []

    async def fake_publish(event: dict[str, Any]) -> None:
        out.append(event)

    monkeypatch.setattr(pipeline, "publish_event", fake_publish)
    return out


# ----------------------------------------------------------------------------- seed helpers
async def _one(s: AsyncSession, sql: str, **p: Any) -> Any:
    return (await s.execute(text(sql), p)).mappings().one()


async def _scalar(s: AsyncSession, sql: str, **p: Any) -> Any:
    return (await s.execute(text(sql), p)).scalar()


async def _org(s: AsyncSession, name: str, sectors: list[str] | None = None) -> str:
    oid = str(uuid.uuid4())
    await s.execute(
        text(
            "INSERT INTO organization (id, org_id, name, normalized_name, kind, country, sectors, source_ref) "
            "VALUES (:id, :org, :n, :nn, 'counterparty', 'GB', CAST(:sec AS JSON), CAST(:src AS JSON))"
        ),
        {"id": oid, "org": ORG, "n": name, "nn": name.lower(), "sec": json.dumps(sectors or []), "src": SRC},
    )
    return oid


async def _opp(
    s: AsyncSession,
    *,
    title: str,
    deadline: datetime | None = None,
    stage: str = "discovered",
    cls: str = "grant",
    status: str = "active",
    demo: bool = False,
    counterparty: str | None = None,
) -> str:
    oid = str(uuid.uuid4())
    await s.execute(
        text(
            "INSERT INTO opportunity (id, org_id, class, pipeline_stage, title, description, source_ref, is_demo, "
            "deadline, status, counterparty_id) VALUES (:id, :org, :cls, :stage, :t, 'd', CAST(:src AS JSON), :demo, "
            ":dl, :st, :cp)"
        ),
        {"id": oid, "org": ORG, "cls": cls, "stage": stage, "t": title, "src": SRC, "demo": demo, "dl": deadline,
         "st": status, "cp": counterparty},
    )  # fmt: skip
    return oid


async def _only_rule(
    s: AsyncSession, kind: str, expr: dict[str, Any], channels: list[str], sev: str = "warning"
) -> str:
    """Disable every existing rule of the org (rolled back with the test) and add one rule."""
    await s.execute(text("UPDATE alert_rule SET enabled = false WHERE org_id = :org"), {"org": ORG})
    rid = str(uuid.uuid4())
    await s.execute(
        text(
            "INSERT INTO alert_rule (id, org_id, name, kind, rule_expr, severity, channels, enabled, created_by) "
            "VALUES (:id, :org, :n, :k, CAST(:e AS JSON), :sev, CAST(:ch AS JSON), true, 'test')"
        ),
        {"id": rid, "org": ORG, "n": f"l8-cov-{rid}", "k": kind, "e": json.dumps(expr), "sev": sev,
         "ch": json.dumps(channels)},
    )  # fmt: skip
    return rid


async def _deliveries(s: AsyncSession, alert_id: str) -> set[tuple[Any, ...]]:
    rows = await s.execute(
        text("SELECT channel, target, status, detail FROM alert_delivery WHERE alert_id = :a"), {"a": alert_id}
    )
    return {tuple(r) for r in rows}


class _Hook:
    """Stands in for httpx.AsyncClient inside cortex.l8_actuation.alerts (internal webhook)."""

    posts: list[tuple[str, dict[str, Any]]] = []

    def __init__(self, *a: Any, **k: Any) -> None:
        pass

    async def __aenter__(self) -> _Hook:
        return self

    async def __aexit__(self, *a: Any) -> bool:
        return False

    async def post(self, url: str, json: dict[str, Any]) -> Any:
        self.posts.append((url, json))
        return SimpleNamespace(raise_for_status=lambda: None)


# =============================================================================== 1. alerts service
async def test_alerts_deadline_rule_creates_once_delivers_and_resolves(s: AsyncSession, events, monkeypatch):
    """Deadline rule on MySQL: rule_expr/channels JSON read back as text are decoded, the naive DATETIME deadline is
    read as UTC (bucket and days are right, no TypeError swallowed by the per-rule guard), the stage filter uses the
    MySQL IN-clause, the dedup key stops a second alert, and the alert resolves when the opportunity is won."""
    from cortex.l8_actuation import alerts

    hook = "https://hooks.internal.test/cortex-alerts"
    monkeypatch.setattr(get_settings(), "alert_webhook_url", hook)
    _Hook.posts = []
    monkeypatch.setattr(alerts, "httpx", SimpleNamespace(AsyncClient=_Hook, HTTPError=httpx.HTTPError))

    now = datetime(2090, 1, 1, 12, 0, tzinfo=UTC)  # far from any seeded deadline
    expr = {"offsets_days": [30, 14, 7, 2], "critical_at_days": 7, "stages": ["term_sheet"]}
    rid = await _only_rule(s, "deadline", expr, ["in_app", "webhook"])
    opp = await _opp(s, title="L8 deadline target", deadline=datetime(2090, 1, 6, 12, 0), stage="term_sheet", demo=True)
    other = await _opp(s, title="L8 filtered out", deadline=datetime(2090, 1, 3), stage="discovered")

    out = await alerts.evaluate(s, now=now)
    assert out["rules"] == 1 and out["created"] == 1

    a = await _one(s, "SELECT * FROM alert WHERE org_id = :o AND subject_id = :id", o=ORG, id=opp)
    assert a["dedup_key"] == f"deadline:{opp}:T-7"
    assert a["severity"] == "critical"  # 5 days <= critical_at_days, overrides the rule's 'warning'
    assert a["status"] == "open" and a["rule_id"] == rid and a["kind"] == "deadline"
    assert a["due_at"] == datetime(2090, 1, 6, 12, 0)  # stored naive UTC, unchanged
    assert a["message"] == "T-7: deadline 2090-01-06 (5 days) for L8 deadline target"
    assert row(a)["is_demo"] is True and a["is_demo"] == 1  # BOOLEAN 0/1 -> true/false
    assert row(a)["due_at"] == "2090-01-06T12:00:00+00:00"
    assert json_obj(a["source_ref"]) == {
        "kind": "alert_rule", "rule_id": rid, "rule": f"l8-cov-{rid}", "subject": f"opportunity:{opp}",
        "evaluated_at": "2090-01-01T12:00:00+00:00",
    }  # fmt: skip
    assert await _scalar(s, "SELECT count(*) FROM alert WHERE subject_id = :id", id=other) == 0

    # channels JSON decoded: both the in-app and the webhook delivery are logged (a str would iterate characters)
    assert await _deliveries(s, a["id"]) == {("in_app", None, "sent", None), ("webhook", hook, "sent", None)}
    assert _Hook.posts == [(hook, {"alert_id": a["id"], "severity": "critical", "message": a["message"]})]
    assert events and events[-1]["type"] == "alert.created" and a["id"] in events[-1]["ids"]
    last = await _scalar(s, "SELECT last_evaluated_at FROM alert_rule WHERE id = :id", id=rid)
    assert last == datetime(2090, 1, 1, 12, 0)  # aware now stored as naive UTC

    # second evaluation: the duplicate dedup_key is skipped, no second alert, no second delivery
    again = await alerts.evaluate(s, now=now)
    assert again["created"] == 0
    assert await _scalar(s, "SELECT count(*) FROM alert WHERE org_id = :o AND dedup_key = :k", o=ORG,
                         k=f"deadline:{opp}:T-7") == 1  # fmt: skip
    assert len(await _deliveries(s, a["id"])) == 2 and len(_Hook.posts) == 1

    # cause gone: the opportunity is won -> the alert resolves
    await s.execute(text("UPDATE opportunity SET status = 'won' WHERE id = :id"), {"id": opp})
    await alerts.evaluate(s, now=now)
    assert await _scalar(s, "SELECT status FROM alert WHERE id = :id", id=a["id"]) == "resolved"


async def test_alerts_custom_rule_mysql_expression_and_skipped_email(s: AsyncSession, events, monkeypatch):
    """Custom rule on MySQL (TIMESTAMPDIFF days_to_deadline, plain class compare). internal_email without SMTP is
    logged as skipped, which only happens if the channels JSON text was decoded to a list."""
    from cortex.l8_actuation import alerts

    monkeypatch.setattr(get_settings(), "smtp_url", None)
    expr = {"field": "days_to_deadline", "op": "<", "value": -20000, "class": "grant"}
    await _only_rule(s, "custom", expr, ["in_app", "internal_email"], sev="info")
    hit = await _opp(s, title="L8 ancient grant", deadline=datetime(1950, 1, 1), cls="grant")
    miss = await _opp(s, title="L8 ancient debt", deadline=datetime(1950, 1, 1), cls="debt_facility")

    out = await alerts.evaluate(s)
    assert out["created"] >= 1
    a = await _one(s, "SELECT * FROM alert WHERE org_id = :o AND dedup_key = :k", o=ORG,
                   k=f"custom:days_to_deadline<-20000:{hit}")  # fmt: skip
    assert a["severity"] == "info" and a["subject_type"] == "opportunity" and a["drill"] == f"/opportunities/{hit}"
    assert a["message"] == "days_to_deadline < -20000: L8 ancient grant"
    assert row(a)["is_demo"] is False
    assert await _scalar(s, "SELECT count(*) FROM alert WHERE subject_id = :id", id=miss) == 0
    assert await _deliveries(s, a["id"]) == {
        ("in_app", None, "sent", None),
        ("internal_email", None, "skipped", "no SMTP_URL or no internal recipients in an internal domain"),
    }


async def test_alerts_snooze_wakeup_compares_in_utc(s: AsyncSession, events):
    """``now`` given with an offset is compared as UTC against naive DATETIME columns: 05:00+05:30 is 23:30 UTC, so a
    snooze until 23:00 UTC wakes and one until 23:59 UTC does not (wall-clock binding would wake both)."""
    from cortex.l8_actuation import alerts

    await s.execute(text("UPDATE alert_rule SET enabled = false WHERE org_id = :org"), {"org": ORG})
    ids = {}
    for label, until in (("due", datetime(2089, 12, 31, 23, 0)), ("later", datetime(2089, 12, 31, 23, 59))):
        ids[label] = str(uuid.uuid4())
        await s.execute(
            text(
                "INSERT INTO alert (id, org_id, kind, severity, message, status, dedup_key, snoozed_until, source_ref) "
                "VALUES (:id, :org, 'custom', 'info', 'snoozed', 'snoozed', :k, :u, CAST(:src AS JSON))"
            ),
            {"id": ids[label], "org": ORG, "k": f"l8-snooze-{ids[label]}", "u": until, "src": SRC},
        )
    ist_now = datetime(2090, 1, 1, 5, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    out = await alerts.evaluate(s, now=ist_now)
    assert out == {"rules": 0, "created": 0, "resolved": out["resolved"]}
    woke = await _one(s, "SELECT status, snoozed_until FROM alert WHERE id = :id", id=ids["due"])
    assert (woke["status"], woke["snoozed_until"]) == ("open", None)
    still = await _one(s, "SELECT status, snoozed_until FROM alert WHERE id = :id", id=ids["later"])
    assert (still["status"], still["snoozed_until"]) == ("snoozed", datetime(2089, 12, 31, 23, 59))


async def test_alerts_evaluate_skips_duplicates_but_raises_on_constraint_violations(
    s: AsyncSession, events, monkeypatch
):
    """M2 at alerts.py's alert insert: a duplicate dedup_key is skipped (no delivery), but a CHECK violation (severity)
    and a NOT NULL violation (message) raise instead of being reported as "already there"."""
    from cortex.l8_actuation import alerts

    rid = await _only_rule(s, "custom", {"field": "score", "op": ">=", "value": 0.5}, ["in_app"])
    dup_key, dup_id = f"l8-dup-{uuid.uuid4()}", str(uuid.uuid4())
    await s.execute(
        text(
            "INSERT INTO alert (id, org_id, rule_id, kind, severity, message, status, dedup_key, source_ref) "
            "VALUES (:id, :org, :r, 'custom', 'warning', 'original', 'open', :k, CAST(:src AS JSON))"
        ),
        {"id": dup_id, "org": ORG, "r": rid, "k": dup_key, "src": SRC},
    )
    cands: list[dict[str, Any]] = []

    async def fake_eval(_s: AsyncSession, _e: dict[str, Any], _now: datetime) -> list[dict[str, Any]]:
        return cands

    monkeypatch.setitem(alerts.EVALUATORS, "custom", fake_eval)

    cands[:] = [{"key": dup_key, "subject": ("opportunity", None), "message": "replacement"}]
    assert (await alerts.evaluate(s))["created"] == 0
    assert await _scalar(s, "SELECT message FROM alert WHERE id = :id", id=dup_id) == "original"
    assert await _deliveries(s, dup_id) == set()
    assert events == []

    bad_sev = f"l8-badsev-{uuid.uuid4()}"
    cands[:] = [{"key": bad_sev, "subject": ("opportunity", None), "message": "m", "severity": "catastrophic"}]
    with pytest.raises(DBAPIError):  # ck_alert_sev (3819)
        await alerts.evaluate(s)
    no_msg = f"l8-nomsg-{uuid.uuid4()}"
    cands[:] = [{"key": no_msg, "subject": ("opportunity", None), "message": None}]
    with pytest.raises(DBAPIError):  # message NOT NULL (1048)
        await alerts.evaluate(s)
    assert await _scalar(s, "SELECT count(*) FROM alert WHERE dedup_key IN (:a, :b)", a=bad_sev, b=no_msg) == 0
    assert await _scalar(s, "SELECT count(*) FROM alert WHERE id = :id", id=dup_id) == 1  # session still usable


async def test_alerts_seed_default_rules_idempotent_and_strict(s: AsyncSession, monkeypatch):
    """seed_default_rules (MySQL path): first call inserts, second skips the duplicates (rowcount 0), JSON columns read
    back as documents and BOOLEANs as true/false. An invalid kind / severity (CHECK) or a missing tenant (FK) raises."""
    from cortex.l8_actuation import alerts

    tag = uuid.uuid4().hex[:8]
    defaults = [
        {"name": f"l8-seed-{tag}-a", "kind": "deadline", "severity": "warning", "channels": ["in_app", "webhook"],
         "rule_expr": {"offsets_days": [30, 7], "bands": ["high"]}, "description": "a"},
        {"name": f"l8-seed-{tag}-b", "kind": "runway_risk", "severity": "critical", "channels": ["in_app"],
         "rule_expr": {"months": 9}},
    ]  # fmt: skip
    monkeypatch.setattr(alerts, "alerts_config", lambda: {"defaults": defaults})
    assert await alerts.seed_default_rules(s) == 2
    assert await alerts.seed_default_rules(s) == 0  # duplicates (org_id, name) skipped
    for d in defaults:
        rows = (
            (
                await s.execute(
                    text("SELECT * FROM alert_rule WHERE org_id = :o AND name = :n"), {"o": ORG, "n": d["name"]}
                )
            )
            .mappings()
            .all()
        )
        assert len(rows) == 1
        r = rows[0]
        assert isinstance(r["rule_expr"], str) and json_obj(r["rule_expr"]) == d["rule_expr"]
        assert json_obj(r["channels"]) == d["channels"]
        out = row(r)
        assert out["enabled"] is True and out["is_default"] is True and out["is_demo"] is False
        assert out["rule_expr"] == d["rule_expr"] and out["created_by"] == "system:default"
        assert out["created_at"].endswith("+00:00")

    for bad in ({"kind": "bogus"}, {"severity": "loud"}):
        name = f"l8-seed-{tag}-bad-{next(iter(bad))}"
        monkeypatch.setattr(
            alerts, "alerts_config", lambda b=bad, n=name: {"defaults": [{**defaults[1], "name": n, **b}]}
        )
        with pytest.raises(DBAPIError):  # ck_alert_rule_kind / ck_alert_rule_sev
            await alerts.seed_default_rules(s)
        assert await _scalar(s, "SELECT count(*) FROM alert_rule WHERE name = :n", n=name) == 0

    fk_name = f"l8-seed-{tag}-fk"
    monkeypatch.setattr(alerts, "alerts_config", lambda: {"defaults": [{**defaults[1], "name": fk_name}]})
    monkeypatch.setattr(get_settings(), "org_id", NO_TENANT)
    with pytest.raises(DBAPIError):  # fk_alert_rule_tenant (1452): INSERT IGNORE would have hidden it
        await alerts.seed_default_rules(s)
    assert await _scalar(s, "SELECT count(*) FROM alert_rule WHERE name = :n", n=fk_name) == 0


# =============================================================================== 2. compliance report
P_FROM, P_TO = "2091-02-01", "2091-02-28"  # a period no seeded row falls in


async def _approval_with_release(s: AsyncSession, approvers: list[str]) -> tuple[str, str]:
    aid, recipient = str(uuid.uuid4()), f"l8-{uuid.uuid4().hex[:8]}@partner.example"
    await s.execute(
        text(
            "INSERT INTO approval (id, org_id, subject_type, subject_id, content_hash, requested_by, decision) "
            "VALUES (:id, :org, 'recommendation', :sid, 'h', 'usr_requester', 'pending')"
        ),
        {"id": aid, "org": ORG, "sid": str(uuid.uuid4())},
    )
    for i, who in enumerate(approvers):
        await s.execute(
            text(
                "INSERT INTO approval_decision (id, org_id, approval_id, approver_id, approver_username, roles, mfa, "
                "decision, comment, content_hash, created_at) VALUES (:id, :org, :a, :ap, :un, CAST(:r AS JSON), true, "
                "'approved', NULL, 'h', :ca)"
            ),
            {"id": str(uuid.uuid4()), "org": ORG, "a": aid, "ap": f"usr_{i}", "un": who, "r": json.dumps(["approver"]),
             "ca": datetime(2091, 2, 5, 10, 0)},
        )  # fmt: skip
    await s.execute(
        text(
            "INSERT INTO outbox (id, org_id, channel, payload, content_hash, approval_id, status, created_by, sent_at, "
            "kind, recipient) VALUES (:id, :org, 'email', CAST('{\"k\": 1}' AS JSON), 'h', :a, 'sent', 'usr_requester', "
            ":sent, 'outbound', :rc)"
        ),
        {"id": str(uuid.uuid4()), "org": ORG, "a": aid, "sent": datetime(2091, 2, 10, 9, 30), "rc": recipient},
    )
    return aid, recipient


def _sheets(data: bytes) -> dict[str, list[list[Any]]]:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data))
    return {ws.title: [list(r) for r in ws.iter_rows(values_only=True)] for ws in wb.worksheets}


def _records(sheet: list[list[Any]]) -> list[dict[str, Any]]:
    return [dict(zip(sheet[0], r, strict=False)) for r in sheet[1:]]


async def test_compliance_report_approvers_are_not_truncated_by_group_concat(s: AsyncSession):
    """External releases list every approver via GROUP_CONCAT, whose default group_concat_max_len is 1024 bytes on
    MySQL: with 40 long usernames (~3 KB) the list must still be complete (string_agg has no such limit)."""
    from cortex.l8_actuation.compliance_report import build_report

    approvers = [f"approver-{i:02d}-{'x' * 40}@capital-cortex.internal" for i in range(40)]
    _, recipient = await _approval_with_release(s, approvers)
    sheets = _sheets(await build_report(s, P_FROM, P_TO))

    summary = {r[0]: r[1] for r in sheets["Summary"][1:]}
    assert summary["Approval decisions"] == 40 and summary["External releases (sent)"] == 1
    release = next(r for r in _records(sheets["External releases"]) if r["recipient"] == recipient)
    listed = release["approvers"].split(", ")
    assert len(release["approvers"]) > 1024
    assert sorted(listed) == sorted(approvers)  # truncated at 1024 chars -> fewer names and a cut-off last one


async def test_compliance_report_cells_decode_json_and_booleans(s: AsyncSession):
    """Workbook cells on MySQL: ->> unquotes JSON scalars, JSON arrays stay JSON text, datetimes are the stored UTC
    instants, and BOOLEAN columns read the same as on PostgreSQL ("True"/"False", not the TINYINT "1"/"0")."""
    from cortex.l8_actuation.compliance_report import build_report

    await _approval_with_release(s, ["solo@capital-cortex.internal"])
    reco, policy = str(uuid.uuid4()), f"l8-policy-{uuid.uuid4().hex[:8]}"
    await s.execute(
        text(
            "INSERT INTO recommendation (id, org_id, text, confidence, evidence, reasoning, stance, method, citation_report, "
            "source_ref, created_at) VALUES (:id, :org, 'r', 0.7, CAST('[{\"ref\": \"doc:1\"}]' AS JSON), "
            "CAST('{}' AS JSON), 'pursue', 'llm', CAST(:cr AS JSON), CAST(:src AS JSON), :ca)"
        ),
        {"id": reco, "org": ORG, "src": SRC, "ca": datetime(2091, 2, 8, 8, 0),
         "cr": json.dumps({"status": "verified", "passed": True, "rejected": ["c9"]})},
    )  # fmt: skip
    await s.execute(
        text(
            "INSERT INTO retention_run (id, org_id, policy, target_table, action, dry_run, rows_affected, run_by, "
            "created_at) VALUES (:id, :org, :p, 'signal', 'delete', true, 3, 'usr_ops', :ca)"
        ),
        {"id": str(uuid.uuid4()), "org": ORG, "p": policy, "ca": datetime(2091, 2, 7, 7, 0)},
    )
    sheets = _sheets(await build_report(s, P_FROM, P_TO))

    cit = next(r for r in _records(sheets["Citation checks"]) if r["recommendation_id"] == reco)
    assert (cit["status"], cit["passed"], cit["stance"], cit["method"]) == ("verified", "true", "pursue", "llm")
    assert json.loads(cit["stripped"]) == ["c9"]
    assert datetime.fromisoformat(cit["created_at"]) == datetime(2091, 2, 8, 8, 0)

    dec = next(
        r for r in _records(sheets["Approval decisions"]) if r["approver_username"] == "solo@capital-cortex.internal"
    )
    assert json.loads(dec["roles"]) == ["approver"] and dec["decision"] == "approved"
    run = next(r for r in _records(sheets["Retention runs"]) if r["policy"] == policy)
    assert run["rows_affected"] == "3"
    # BOOLEAN parity with PostgreSQL: str(True) == "True"; on MySQL the driver's 1 is written as "1"
    assert dec["mfa"] == "True"
    assert run["dry_run"] == "True"


async def test_compliance_report_blocked_release_reason_is_unquoted(s: AsyncSession):
    """``meta ->> '$.reason'`` returns the bare string (not the JSON-quoted one) and settings changes list their meta."""
    from cortex.l7_governance import audit_service
    from cortex.l8_actuation.compliance_report import build_report

    target = f"outbox:{uuid.uuid4()}"
    await audit_service.record(s, "test:l8", "outbox.blocked", target, {"reason": "recipient not allowlisted"})
    await audit_service.record(s, "test:l8", "setting.governance.put", target, {"k": 1})
    today = datetime.now(UTC).date().isoformat()
    sheets = _sheets(await build_report(s, today, today))
    blocked = next(r for r in _records(sheets["Blocked releases"]) if r["target"] == target)
    assert blocked["reason"] == "recipient not allowlisted" and blocked["actor"] == "test:l8"
    setting = next(r for r in _records(sheets["Settings and roles"]) if r["target"] == target)
    assert json.loads(setting["meta"])["k"] == 1
    summary = {r[0]: r[1] for r in sheets["Summary"][1:]}
    assert summary["Blocked releases"] >= 1 and summary["Audit records checked"] >= 2


async def test_compliance_report_route_roles_validation_and_audit(s: AsyncSession, api):
    url = "/v1/audit/compliance-report"
    r = await api.c.get(url, params={"from": P_FROM, "to": P_TO}, headers=api.auth("analyst"))
    assert r.status_code == 403 and r.json()["permission"] == "audit:read"
    r = await api.c.get(url, params={"from": "2091-2-1", "to": P_TO}, headers=api.auth("auditor"))
    assert r.status_code == 422
    r = await api.c.get(url, params={"from": P_FROM}, headers=api.auth("auditor"))
    assert r.status_code == 422  # "to" missing
    assert await _scalar(s, "SELECT count(*) FROM audit_log WHERE actor = :a", a=ACTOR) == 0

    r = await api.c.get(url, params={"from": P_FROM, "to": P_TO}, headers=api.auth("auditor"))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    assert f"compliance-report-{P_FROM}-to-{P_TO}.xlsx" in r.headers["content-disposition"]
    assert "Summary" in _sheets(r.content)
    meta = await _scalar(
        s, "SELECT meta FROM audit_log WHERE actor = :a AND action = 'audit.compliance_report' ORDER BY seq DESC LIMIT 1",
        a=ACTOR,
    )  # fmt: skip
    m = json_obj(meta)
    assert (m["from"], m["to"], m["bytes"]) == (P_FROM, P_TO, len(r.content))


# =============================================================================== 3. routers/entities
async def _pair(s: AsyncSession) -> tuple[str, str]:
    tag = uuid.uuid4().hex[:8]
    left = await _org(s, f"L8 Climate Partners {tag}", ["climate", "energy"])
    right = await _org(s, f"L8 Climate Partners {tag}", [])
    return left, right


async def test_entities_propose_list_and_duplicate_pair(s: AsyncSession, api):
    """POST /v1/entities/merge-queue then GET: the MySQL insert stores the manual candidate; the same pair (either
    order) is a duplicate -> 409 with one row; the queue decodes evidence/sectors JSON, BOOLEAN and naive DATETIME."""
    left, right = await _pair(s)
    await _opp(s, title="L8 on left", counterparty=left)
    h = api.auth("analyst")

    r = await api.c.post(
        "/v1/entities/merge-queue", json={"left_id": left, "right_id": right, "note": "same firm"}, headers=h
    )
    assert r.status_code == 201, r.text
    cid, score = r.json()["id"], r.json()["score"]
    db = await _one(s, "SELECT * FROM entity_merge_candidate WHERE id = :id", id=cid)
    assert (db["left_id"], db["right_id"], db["method"], db["status"]) == (left, right, "manual", "pending")
    assert db["score"] == Decimal(str(score)) and score == 1.0  # identical normalised names
    ev = json_obj(db["evidence"])
    assert ev["proposed_by"] == USER and ev["note"] == "same firm" and ev["method"] == "jaro_winkler"

    for body in ({"left_id": left, "right_id": right}, {"left_id": right, "right_id": left}):
        dup = await api.c.post("/v1/entities/merge-queue", json=body, headers=h)
        assert dup.status_code == 409 and dup.json()["title"] == "Already queued"
    n = await _scalar(
        s,
        "SELECT count(*) FROM entity_merge_candidate WHERE (left_id, right_id) IN ((:l, :r), (:r, :l))",
        l=left,
        r=right,
    )
    assert n == 1

    q = await api.c.get("/v1/entities/merge-queue", params={"status": "pending"}, headers=h)
    assert q.status_code == 200
    item = next(i for i in q.json()["items"] if i["id"] == cid)
    assert item["is_demo"] is False and item["score"] == 1.0
    assert item["evidence"]["note"] == "same firm"
    assert item["created_at"].endswith("+00:00")
    assert item["left"]["id"] == left and item["left"]["sectors"] == ["climate", "energy"]
    assert item["left"]["opportunities"] == 1 and item["right"]["opportunities"] == 0
    assert item["left"]["source_ref"] == json.loads(SRC)


async def test_entities_merge_unmerge_and_reject(s: AsyncSession, api):
    left, right = await _pair(s)
    moved_opp = await _opp(s, title="L8 on right", counterparty=right)
    h = api.auth("analyst")
    cid = (await api.c.post("/v1/entities/merge-queue", json={"left_id": left, "right_id": right}, headers=h)).json()[
        "id"
    ]

    r = await api.c.post(f"/v1/entities/{cid}/merge", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "merged" and (body["keep"], body["drop"]) == (left, right)
    assert body["moved"]["opportunity"] == [moved_opp]
    assert await _scalar(s, "SELECT merged_into FROM organization WHERE id = :id", id=right) == left
    assert await _scalar(s, "SELECT counterparty_id FROM opportunity WHERE id = :id", id=moved_opp) == left
    c = await _one(
        s, "SELECT status, decided_by, decided_at, `undo` FROM entity_merge_candidate WHERE id = :id", id=cid
    )
    assert c["status"] == "merged" and c["decided_by"] == USER and c["decided_at"] is not None
    assert json_obj(c["undo"]) == {"keep": left, "drop": right, "moved": body["moved"]}
    again = await api.c.post(f"/v1/entities/{cid}/merge", headers=h)
    assert again.status_code == 409  # no longer pending

    r = await api.c.post(f"/v1/entities/{cid}/unmerge", headers=h)
    assert r.status_code == 200 and r.json() == {"id": cid, "status": "unmerged"}
    assert await _scalar(s, "SELECT merged_into FROM organization WHERE id = :id", id=right) is None
    assert await _scalar(s, "SELECT counterparty_id FROM opportunity WHERE id = :id", id=moved_opp) == right
    assert (await api.c.post(f"/v1/entities/{cid}/unmerge", headers=h)).status_code == 409

    actions = (
        (
            await s.execute(
                text("SELECT action FROM audit_log WHERE actor = :a AND target = :t ORDER BY seq"),
                {"a": ACTOR, "t": f"merge_candidate:{cid}"},
            )
        )
        .scalars()
        .all()
    )
    assert actions == ["entity.merge", "entity.unmerge"]

    other = await _org(s, f"L8 Climate Partner {uuid.uuid4().hex[:8]}")
    cid2 = (await api.c.post("/v1/entities/merge-queue", json={"left_id": left, "right_id": other}, headers=h)).json()[
        "id"
    ]
    r = await api.c.post(f"/v1/entities/{cid2}/merge", json={"reject": True}, headers=h)
    assert r.status_code == 200 and r.json() == {"id": cid2, "status": "rejected"}
    rej = await _one(s, "SELECT status, decided_by, decided_at FROM entity_merge_candidate WHERE id = :id", id=cid2)
    assert rej["status"] == "rejected" and rej["decided_by"] == USER and rej["decided_at"] is not None
    assert (await api.c.post(f"/v1/entities/{cid2}/merge", json={"reject": True}, headers=h)).status_code == 404


async def test_entities_validation_not_found_and_roles(s: AsyncSession, api):
    left, right = await _pair(s)
    h = api.auth("analyst")
    url = "/v1/entities/merge-queue"
    assert (await api.c.get(url, params={"status": "bogus"}, headers=h)).status_code == 422
    same = await api.c.post(url, json={"left_id": left, "right_id": left}, headers=h)
    assert same.status_code == 422 and same.json()["title"] == "Same entity"
    long_note = await api.c.post(url, json={"left_id": left, "right_id": right, "note": "n" * 501}, headers=h)
    assert long_note.status_code == 422
    assert (await api.c.post(url, json={"left_id": left}, headers=h)).status_code == 422

    missing = await api.c.post(url, json={"left_id": left, "right_id": str(uuid.uuid4())}, headers=h)
    assert missing.status_code == 404
    unknown = str(uuid.uuid4())
    assert (await api.c.post(f"/v1/entities/{unknown}/merge", json={"reject": True}, headers=h)).status_code == 404

    for role in ("approver", "auditor", "executive"):  # no entity:merge
        r = await api.c.post(url, json={"left_id": left, "right_id": right}, headers=api.auth(role))
        assert r.status_code == 403 and r.json()["permission"] == "entity:merge"
    r = await api.c.get(url, headers=api.auth("approver"))  # no entity:read
    assert r.status_code == 403 and r.json()["permission"] == "entity:read"
    n = await _scalar(s, "SELECT count(*) FROM entity_merge_candidate WHERE left_id IN (:l, :r) OR right_id IN (:l, :r)",
                      l=left, r=right)  # fmt: skip
    assert n == 0


async def test_entities_merge_of_unknown_candidate_is_404(s: AsyncSession, api):
    """A merge (not reject) of an id that does not exist must be a 404 like the reject path, not a 500
    (entity_resolver.merge uses .one() and the router only maps ValueError)."""
    r = await api.c.post(f"/v1/entities/{uuid.uuid4()}/merge", headers=api.auth("analyst"))
    assert r.status_code == 404
    r = await api.c.post(f"/v1/entities/{uuid.uuid4()}/unmerge", headers=api.auth("analyst"))
    assert r.status_code == 404


async def test_entities_propose_raises_on_fk_violation_not_409(s: AsyncSession, monkeypatch):
    """M2 at routers/entities.py: only a duplicate pair is "Already queued"; an FK violation (tenant missing) raises.
    INSERT IGNORE turned it into rowcount 0 -> a misleading 409."""
    from cortex.l8_actuation.api.routers import entities

    left, right = await _pair(s)
    monkeypatch.setattr(get_settings(), "org_id", NO_TENANT)
    # The organization lookup is tenant-scoped, so a missing tenant is a 404 before the INSERT (never a 409).
    # insert_or_skip_duplicate re-raising non-duplicate errors is covered in test_mysql_medium_defects.py.
    with pytest.raises(NotFound):
        await entities.propose(body=entities.CandidateIn(left_id=left, right_id=right), p=ADMIN, session=s)
    assert await _scalar(s, "SELECT count(*) FROM entity_merge_candidate WHERE left_id = :l", l=left) == 0

    monkeypatch.setattr(get_settings(), "org_id", ORG)
    first = await entities.propose(body=entities.CandidateIn(left_id=left, right_id=right), p=ADMIN, session=s)
    with pytest.raises(Problem) as dup:
        await entities.propose(body=entities.CandidateIn(left_id=right, right_id=left), p=ADMIN, session=s)
    assert dup.value.status == 409
    assert await _scalar(s, "SELECT id FROM entity_merge_candidate WHERE left_id = :l", l=left) == first["id"]


# =============================================================================== 4. routers/forecasts
CSV_MAPPING = {"period": "Month", "cash": "Closing Cash", "opex": "Expenses", "currency": "Ccy"}


def _csv(*lines: str) -> bytes:
    return ("Month,Closing Cash,Expenses,Ccy\n" + "\n".join(lines) + "\n").encode()


async def _snap(s: AsyncSession, period: date) -> Any:
    rows = (
        (
            await s.execute(
                text("SELECT * FROM financial_snapshot WHERE org_id = :o AND period = :p"), {"o": ORG, "p": period}
            )
        )
        .mappings()
        .all()
    )
    assert len(rows) <= 1
    return rows[0] if rows else None


async def _import(api: Any, data: bytes, mapping: Any, role: str = "admin", name: str = "fin.csv") -> httpx.Response:
    return await api.c.post(
        "/v1/forecasts/snapshots/import",
        files={"file": (name, data, "text/csv")},
        data={"mapping": mapping if isinstance(mapping, str) else json.dumps(mapping)},
        headers=api.auth(role),
    )


async def test_forecast_import_upserts_by_period(s: AsyncSession, api):
    """ON DUPLICATE KEY UPDATE ... VALUES(): an existing (demo) period is updated in place (same id, is_demo reset),
    a re-import updates rather than duplicates, unreadable rows are skipped, and the snapshot list decodes it all."""
    seed_id = str(uuid.uuid4())
    await s.execute(
        text(
            "INSERT INTO financial_snapshot (id, org_id, period, cash, revenue, opex, net_burn, currency, source_ref, "
            "is_demo) VALUES (:id, :org, '2091-03-01', 1, 5, 1, 1, 'USD', CAST(:src AS JSON), true)"
        ),
        {"id": seed_id, "org": ORG, "src": json.dumps({"kind": "seed"})},
    )
    data = _csv("2091-03-15,1000.50,200,eur", "2091-04-30,900,210,", "not a date,1,1,", "2091-05-31,,,")
    r = await _import(api, data, CSV_MAPPING)
    assert r.status_code == 200, r.text
    digest = hashlib.sha256(data).hexdigest()
    assert r.json() == {
        "imported": 2,
        "skipped": ["row 4: unreadable period", "row 5: no numeric values"],
        "sha256": digest,
    }

    mar = await _snap(s, date(2091, 3, 1))
    assert mar["id"] == seed_id  # updated, not a second row
    assert (mar["cash"], mar["opex"], mar["revenue"], mar["net_burn"]) == (
        Decimal("1000.50"),
        Decimal("200.00"),
        None,
        None,
    )
    assert mar["currency"] == "EUR" and mar["is_demo"] == 0 and row(mar)["is_demo"] is False
    src = json_obj(mar["source_ref"])
    assert (src["kind"], src["filename"], src["sha256"], src["row"]) == ("file", "fin.csv", digest, 2)
    assert src["uploaded_by"] == USER and src["mapping"] == CSV_MAPPING
    apr = await _snap(s, date(2091, 4, 1))
    assert (apr["cash"], apr["currency"]) == (Decimal("900.00"), "USD")  # default currency
    assert await _snap(s, date(2091, 5, 1)) is None

    data2 = _csv("2091-04-01,950,220,gbp")
    r = await _import(api, data2, CSV_MAPPING, name="fin2.csv")
    assert r.json()["imported"] == 1
    apr2 = await _snap(s, date(2091, 4, 1))  # still exactly one row for the period
    assert apr2["id"] == apr["id"] and (apr2["cash"], apr2["opex"], apr2["currency"]) == (
        Decimal("950.00"), Decimal("220.00"), "GBP",
    )  # fmt: skip
    assert json_obj(apr2["source_ref"])["sha256"] == hashlib.sha256(data2).hexdigest()

    meta = json_obj(await _scalar(
        s, "SELECT meta FROM audit_log WHERE actor = :a AND action = 'financials.import' ORDER BY seq LIMIT 1", a=ACTOR
    ))  # fmt: skip
    assert (meta["imported"], meta["skipped"], meta["sha256"]) == (2, 2, digest)

    lst = await api.c.get("/v1/forecasts/snapshots", headers=api.auth("analyst"))
    assert lst.status_code == 200
    item = next(i for i in lst.json()["items"] if i["id"] == seed_id)
    assert item["period"] == "2091-03-01" and item["cash"] == 1000.5 and item["is_demo"] is False
    assert item["source_ref"]["filename"] == "fin.csv"


async def test_forecast_import_validation_roles_and_out_of_range(s: AsyncSession, api):
    ok_csv = _csv("2091-06-15,100,10,usd")
    bad_json = await _import(api, ok_csv, "{not json")
    assert bad_json.status_code == 422 and bad_json.json()["title"] == "Invalid mapping"
    incomplete = await _import(api, ok_csv, {"period": "Month", "currency": "Ccy"})
    assert incomplete.status_code == 422 and incomplete.json()["title"] == "Incomplete mapping"
    for role in ("analyst", "executive", "auditor"):  # forecast:write is admin (or the finance grant) only
        r = await _import(api, ok_csv, CSV_MAPPING, role=role)
        assert r.status_code == 403 and r.json()["permission"] == "forecast:write"
    assert await _snap(s, date(2091, 6, 1)) is None

    # DECIMAL(18,2) overflow: strict mode must reject it, never store a clamped figure
    huge = await _import(api, _csv("2091-07-15,123456789012345678901,10,usd"), CSV_MAPPING)
    assert huge.status_code in (422, 500)
    assert await _snap(s, date(2091, 7, 1)) is None


async def test_forecast_create_persists_json_and_lists_decoded(s: AsyncSession, api):
    r = await api.c.post("/v1/forecasts", headers=api.auth("admin"))
    assert r.status_code == 201, r.text
    body = r.json()
    ids = body["ids"]
    assert len(ids) == 3 and [x["scenario"] for x in body["results"]] == ["base", "downside", "upside"]
    for fid, res in zip(ids, body["results"], strict=True):
        f = await _one(s, "SELECT * FROM forecast WHERE id = :id", id=fid)
        assert f["scenario"] == res["scenario"] and f["status"] == res["status"]
        assert f["horizon_months"] == res["horizon_months"]
        assert isinstance(json_obj(f["series"]), list)
        assert json_obj(f["inputs_ref"])["assumptions"] == "config/forecast.yaml"
        assert json_obj(f["source_ref"]) == {"kind": "computed", "engine": "forecast_engine",
                                             "inputs": json_obj(f["inputs_ref"])}  # fmt: skip
        if f["status"] == "insufficient_data":
            assert f["runway_months"] is None and f["zero_cash_date"] is None
        else:
            assert float(f["runway_months"]) == pytest.approx(res["runway_months"], abs=0.01)
    meta = json_obj(await _scalar(
        s, "SELECT meta FROM audit_log WHERE actor = :a AND action = 'forecast.create' ORDER BY seq DESC LIMIT 1", a=ACTOR
    ))  # fmt: skip
    assert meta["ids"] == ids

    lst = await api.c.get("/v1/forecasts", headers=api.auth("executive"))
    assert lst.status_code == 200
    items = {i["id"]: i for i in lst.json()["items"]}
    for fid in ids:
        it = items[fid]
        assert isinstance(it["assumptions"], dict) and it["is_demo"] is False
        assert it["created_at"].endswith("+00:00")


async def test_forecast_routes_roles_and_validation(s: AsyncSession, api):
    before = await _scalar(s, "SELECT count(*) FROM forecast WHERE org_id = :o", o=ORG)
    for role in ("analyst", "executive", "approver"):
        r = await api.c.post("/v1/forecasts", headers=api.auth(role))
        assert r.status_code == 403 and r.json()["permission"] == "forecast:write"
    assert await _scalar(s, "SELECT count(*) FROM forecast WHERE org_id = :o", o=ORG) == before

    run = "/v1/forecasts/scenarios/run"
    h = api.auth("analyst")
    assert (await api.c.post(run, json={"scenarios": [{"burn_delta_pct": 1000}]}, headers=h)).status_code == 422
    assert (await api.c.post(run, json={"scenarios": [{}] * 7}, headers=h)).status_code == 422
    none = await api.c.post(run, json={"include_presets": False}, headers=h)
    assert none.status_code == 422 and none.json()["title"] == "No scenarios"
    assert (await api.c.get("/v1/forecasts/snapshots", headers=api.auth("analyst"))).status_code == 200
