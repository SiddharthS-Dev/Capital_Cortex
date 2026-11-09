"""Route/function-level regression tests for the High MySQL defects H3, H4 and H9 (COV-2 in
docs/CORTEX_MYSQL_COMPLETE_OPEN_BLOCKER_AUDIT.md; originals in docs/CORTEX_MYSQL_BLOCKER_CLOSURE_REGISTER.md):

* H3  PATCH /v1/recommendations/{id}: ``{**payload}`` on the portal-export draft's JSON column (text on MySQL) raised
      TypeError, so editing a recommendation with export drafts returned 500.
* H4  POST /v1/recommendations/{id}/approve: the citation report (text on MySQL) was ``json.dumps``-ed again, so the
      approval stored a JSON *string* and the approval inbox's ``citation_report ->> '$.status'`` was NULL.
* H9  ml_scorer.train with an active model and no holdout candidate: ``active["metrics"]`` (text on MySQL) was used
      with ``.get`` → AttributeError, so training aborted.

MySQL unit database only (get_mysql_test_url, MYSQL_TEST_DATABASE=cortex_unit). Every test runs inside one
transaction that is always rolled back; the full FastAPI app is driven in-process (httpx.ASGITransport) with its DB
session dependency bound to that transaction. Token verification uses the conftest RSA verifier, OPA is a stub that
mirrors RBAC for ``cortex.authz`` and denies release for ``cortex.governance``, and the Redis bus is stubbed.
"""

from __future__ import annotations

import json
import random
import re
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l4_reasoning import ml_scorer
from cortex.l7_governance.approval_service import recommendation_content
from platform_core.auth import oidc
from platform_core.auth.rbac import get_rbac
from platform_core.db import get_session
from platform_core.db.session import create_engine_from_url, get_mysql_test_url, reset_engine
from platform_core.jsonutil import json_obj
from platform_core.policy import opa
from platform_core.policy.opa import PolicyDecision
from platform_core.signing import content_hash

ORG = "00000000-0000-0000-0000-000000000001"
SUB = f"usr_route_reg_{uuid.uuid4().hex[:8]}"
GOV_DENY = "test: release needs an approval decision"


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
    ml_scorer._model_cache.clear()


class _Opa:
    """``cortex.authz`` allows iff RBAC allows (as test_authz_matrix.RbacOPA); ``cortex.governance`` never releases."""

    def __init__(self) -> None:
        self.packages: list[str] = []

    async def evaluate(self, package: str, input_: dict[str, Any]) -> PolicyDecision:
        self.packages.append(package)
        if package == "cortex.authz":
            perms = get_rbac().permissions_for(set(input_["subject"]["roles"]))
            ok = "*" in perms or input_["action"] in perms
            return PolicyDecision(ok, [] if ok else ["rbac"])
        return PolicyDecision(False, [GOV_DENY])


class _FakeRedis:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def get(self, k: str) -> None:
        self.calls.append(("get", k))

    async def set(self, k: str, _v: str) -> None:
        self.calls.append(("set", k))

    async def delete(self, k: str) -> None:
        self.calls.append(("delete", k))


@pytest.fixture
async def api(s: AsyncSession, verifier, make_token, monkeypatch):
    """The real app; its get_session dependency yields the rolled-back session ``s``."""
    from cortex.l8_actuation.api.app import create_app
    from cortex.l8_actuation.api.routers import agents, outcomes

    events: list[dict[str, Any]] = []

    async def fake_publish(event: dict[str, Any]) -> None:
        events.append(event)

    redis = _FakeRedis()
    monkeypatch.setattr(agents, "publish_event", fake_publish)
    monkeypatch.setattr(outcomes, "publish_event", fake_publish)
    monkeypatch.setattr(outcomes, "get_bus", lambda: SimpleNamespace(r=redis))
    stub = _Opa()
    oidc.set_verifier(verifier)
    opa.set_opa(stub)  # type: ignore[arg-type]
    app = create_app()

    async def _session():
        yield s

    app.dependency_overrides[get_session] = _session
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            yield SimpleNamespace(
                c=c,
                events=events,
                redis=redis,
                opa=stub,
                auth=lambda role: {"Authorization": f"Bearer {make_token([role], sub=SUB, username='reg@test')}"},
            )
    finally:
        oidc.set_verifier(None)
        opa.set_opa(None)


# ----------------------------------------------------------------------------- seed helpers
CLAIMS = [{"id": "c1", "text": "Fits the thesis", "refs": ["doc:1"], "supported": True}]
EVIDENCE = [{"ref": "doc:1", "quote": "Climate hardware, seed stage", "score": 0.75}]
GAPS = [{"id": "g1", "text": "No audited financials"}]
CITATION = {"status": "verified", "checked": 1, "unresolved": [], "claims": {"c1": {"ok": True, "refs": ["doc:1"]}}}
DRAFT = {
    "title": "Grant export pack",
    "recommendation": "Pursue the grant",
    "sections": [{"heading": "Summary", "order": 1}, {"heading": "Fit", "order": 2}],
    "meta": {"nested": {"ok": True, "none": None}},
}


def _reco_hash(txt: str) -> str:
    return content_hash(
        recommendation_content({"text": txt, "stance": "pursue", "claims": CLAIMS, "evidence": EVIDENCE, "gaps": GAPS})
    )


async def _seed_reco(
    s: AsyncSession, *, txt: str = "Pursue the grant", citation: Any = CITATION, stored_hash: str | None = None
) -> str:
    rid = str(uuid.uuid4())
    await s.execute(
        text(
            "INSERT INTO recommendation (id, org_id, source_ref, text, confidence, evidence, reasoning, status, stance, "
            "method, claims, gaps, citation_report, content_hash) VALUES (:id, :org, CAST(:src AS JSON), :t, 0.8, "
            "CAST(:ev AS JSON), CAST(:rs AS JSON), 'proposed', 'pursue', 'deterministic', CAST(:cl AS JSON), "
            "CAST(:gp AS JSON), CAST(:cit AS JSON), :h)"
        ),
        {
            "id": rid,
            "org": ORG,
            "src": json.dumps({"kind": "test", "suite": "route_regressions"}),
            "t": txt,
            "ev": json.dumps(EVIDENCE),
            "rs": json.dumps({"steps": ["fit", "risk"]}),
            "cl": json.dumps(CLAIMS),
            "gp": json.dumps(GAPS),
            "cit": json.dumps(citation) if citation is not None else None,
            "h": stored_hash or _reco_hash(txt),
        },
    )
    return rid


async def _seed_outbox(
    s: AsyncSession,
    rid: str,
    payload: dict[str, Any],
    *,
    channel: str = "portal_export",
    kind: str = "export",
    status: str = "draft",
    recipient: str | None = None,
    approval_id: str | None = None,
) -> str:
    oid = str(uuid.uuid4())
    await s.execute(
        text(
            "INSERT INTO outbox (id, org_id, channel, payload, content_hash, approval_id, status, created_by, kind, "
            "recipient, recipient_external, recommendation_id) VALUES (:id, :org, :ch, CAST(:p AS JSON), :h, :a, :st, "
            ":by, :k, :rcp, :ext, :rid)"
        ),
        {
            "id": oid,
            "org": ORG,
            "ch": channel,
            "p": json.dumps(payload),
            "h": content_hash(payload),
            "a": approval_id,
            "st": status,
            "by": SUB,
            "k": kind,
            "rcp": recipient,
            "ext": recipient is not None,
            "rid": rid,
        },
    )
    return oid


async def _one(s: AsyncSession, sql: str, **params: Any) -> dict[str, Any] | None:
    r = (await s.execute(text(sql), params)).mappings().first()
    return dict(r) if r is not None else None


async def _audit_meta(s: AsyncSession, action: str, target: str) -> dict[str, Any] | None:
    raw = (
        await s.execute(
            text("SELECT meta FROM audit_log WHERE action = :a AND target = :t ORDER BY seq DESC LIMIT 1"),
            {"a": action, "t": target},
        )
    ).scalar()
    return json_obj(raw) if raw is not None else None


async def _approvals_for(s: AsyncSession, subject_id: str) -> int:
    return int(
        (await s.execute(text("SELECT count(*) FROM approval WHERE subject_id = :id"), {"id": subject_id})).scalar()
    )


# ============================================================================= H3: PATCH /v1/recommendations/{id}
async def test_h3_patch_rewrites_portal_export_draft_as_json_document(s: AsyncSession, api):
    rid = await _seed_reco(s)
    draft = await _seed_outbox(s, rid, DRAFT)
    email = await _seed_outbox(
        s, rid, {"subject": "Hi", "body": "Pursue the grant"}, channel="email", kind="outbound", recipient="x@ex.org"
    )
    sent_payload = {**DRAFT, "title": "already sent"}
    sent_appr = str(uuid.uuid4())
    await s.execute(
        text(
            "INSERT INTO approval (id, org_id, subject_type, subject_id, content_hash, requested_by, decision, "
            "approver_id) VALUES (:id, :org, 'outbox', :sid, :h, 'seed', 'approved', 'seed-approver')"
        ),
        {"id": sent_appr, "org": ORG, "sid": str(uuid.uuid4()), "h": content_hash(sent_payload)},
    )
    sent = await _seed_outbox(s, rid, sent_payload, status="sent", approval_id=sent_appr)
    raw = (await s.execute(text("SELECT payload FROM outbox WHERE id = :id"), {"id": draft})).scalar()
    assert isinstance(raw, str | bytes)  # the MySQL condition behind H3: the driver hands back JSON text

    new_text = "Pursue the grant — revised after diligence"
    r = await api.c.patch(f"/v1/recommendations/{rid}", json={"text": new_text}, headers=api.auth("analyst"))

    assert r.status_code == 200, r.text  # was 500 (TypeError: 'str' object is not a mapping)
    expected_hash = _reco_hash(new_text)  # hashed over the decoded claims/evidence/gaps, not their JSON text
    assert r.json() == {"id": rid, "status": "proposed", "content_hash": expected_hash, "approvals_invalidated": 0}

    reco = await _one(s, "SELECT text, version, edited_by, content_hash FROM recommendation WHERE id = :id", id=rid)
    assert reco == {"text": new_text, "version": 2, "edited_by": SUB, "content_hash": expected_hash}

    out = await _one(
        s, "SELECT payload, JSON_TYPE(payload) AS jt, content_hash, status FROM outbox WHERE id = :id", id=draft
    )
    assert out is not None and out["jt"] == "OBJECT"  # a document, not a JSON string literal
    new_payload = {**DRAFT, "recommendation": new_text}
    assert json.loads(out["payload"]) == new_payload  # every other key of the draft kept, nested ones included
    assert out["content_hash"] == content_hash(new_payload) and out["status"] == "draft"

    # only unsent portal-export drafts are regenerated
    em = await _one(s, "SELECT payload, content_hash FROM outbox WHERE id = :id", id=email)
    assert em is not None and json.loads(em["payload"]) == {"subject": "Hi", "body": "Pursue the grant"}
    st = await _one(s, "SELECT payload, status, approval_id FROM outbox WHERE id = :id", id=sent)
    assert st is not None and json.loads(st["payload"]) == sent_payload
    assert (st["status"], st["approval_id"]) == ("sent", sent_appr)

    meta = await _audit_meta(s, "recommendation.edited", f"recommendation:{rid}")
    assert meta is not None and meta["content_hash"] == expected_hash and meta["approvals_invalidated"] == 0
    assert meta["username"] == "reg@test"
    assert api.events == [{"type": "recommendation.updated", "ids": [rid]}]


async def test_h3_patch_after_approval_invalidates_the_draft_approval(s: AsyncSession, api):
    rid = await _seed_reco(s)
    draft = await _seed_outbox(s, rid, DRAFT)
    appr = await api.c.post(f"/v1/recommendations/{rid}/approve", headers=api.auth("analyst"))
    assert appr.status_code == 200, appr.text
    aid = appr.json()["approvals"][0]["approval_id"]

    r = await api.c.patch(f"/v1/recommendations/{rid}", json={"text": "Watch instead"}, headers=api.auth("analyst"))

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["approvals_invalidated"] == 1
    assert body["status"] == "proposed"  # trg_recommendation_invalidate reset 'pending_approval'
    a = await _one(s, "SELECT decision FROM approval WHERE id = :id", id=aid)
    assert a == {"decision": "invalidated"}  # trg_outbox_invalidate
    out = await _one(
        s, "SELECT status, approval_id, JSON_TYPE(payload) AS jt, payload FROM outbox WHERE id = :id", id=draft
    )
    assert out is not None and (out["status"], out["approval_id"], out["jt"]) == ("draft", None, "OBJECT")
    assert json.loads(out["payload"])["recommendation"] == "Watch instead"


@pytest.mark.parametrize("body", [{"text": ""}, {"text": "x" * 8001}, {}, {"text": None}])
async def test_h3_patch_invalid_body_is_422_and_changes_nothing(s: AsyncSession, api, body):
    rid = await _seed_reco(s)
    draft = await _seed_outbox(s, rid, DRAFT)

    r = await api.c.patch(f"/v1/recommendations/{rid}", json=body, headers=api.auth("analyst"))

    assert r.status_code == 422
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["title"] == "Validation failed"
    reco = await _one(s, "SELECT text, version, edited_by FROM recommendation WHERE id = :id", id=rid)
    assert reco == {"text": "Pursue the grant", "version": 1, "edited_by": None}
    out = await _one(s, "SELECT payload FROM outbox WHERE id = :id", id=draft)
    assert out is not None and json.loads(out["payload"]) == DRAFT
    assert await _audit_meta(s, "recommendation.edited", f"recommendation:{rid}") is None
    assert api.events == []


async def test_h3_patch_unknown_recommendation_is_404(s: AsyncSession, api):
    missing = str(uuid.uuid4())

    r = await api.c.patch(f"/v1/recommendations/{missing}", json={"text": "x"}, headers=api.auth("analyst"))

    assert r.status_code == 404
    assert r.json()["title"] == "Not Found" and r.json()["detail"] == "recommendation not found"
    assert await _audit_meta(s, "recommendation.edited", f"recommendation:{missing}") is None
    assert api.events == []


async def test_h3_patch_without_recommendation_write_is_403(s: AsyncSession, api):
    rid = await _seed_reco(s)
    draft = await _seed_outbox(s, rid, DRAFT)

    r = await api.c.patch(f"/v1/recommendations/{rid}", json={"text": "hijack"}, headers=api.auth("approver"))

    assert r.status_code == 403
    assert r.json()["permission"] == "recommendation:write"
    reco = await _one(s, "SELECT text, version FROM recommendation WHERE id = :id", id=rid)
    assert reco == {"text": "Pursue the grant", "version": 1}
    out = await _one(s, "SELECT payload FROM outbox WHERE id = :id", id=draft)
    assert out is not None and json.loads(out["payload"]) == DRAFT
    assert api.events == []


# ============================================================================= H4: POST /v1/recommendations/{id}/approve
async def test_h4_approve_draft_stores_citation_report_once(s: AsyncSession, api):
    rid = await _seed_reco(s)
    draft = await _seed_outbox(s, rid, DRAFT)
    raw = (await s.execute(text("SELECT citation_report FROM recommendation WHERE id = :id"), {"id": rid})).scalar()
    assert isinstance(raw, str | bytes)  # the MySQL condition behind H4: JSON text, which used to be re-dumped

    r = await api.c.post(f"/v1/recommendations/{rid}/approve", headers=api.auth("analyst"))

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["recommendation_id"] == rid and len(body["approvals"]) == 1
    first = body["approvals"][0]
    assert first["status"] == "pending" and first["reused"] is False
    assert first["policy"]["allow"] is False and first["policy"]["deny"] == [GOV_DENY]
    aid = first["approval_id"]

    a = await _one(
        s,
        "SELECT subject_type, subject_id, requested_by, decision, content_hash, citation_report, "
        "JSON_TYPE(citation_report) AS cit_type, citation_report ->> '$.status' AS citation_status, "
        "JSON_TYPE(preview) AS preview_type, preview ->> '$.payload.recommendation' AS preview_text, "
        "JSON_TYPE(policy_result) AS policy_type FROM approval WHERE id = :id",
        id=aid,
    )
    assert a is not None
    assert (a["subject_type"], a["subject_id"], a["requested_by"], a["decision"]) == ("outbox", draft, SUB, "pending")
    assert a["content_hash"] == content_hash(DRAFT)
    assert a["cit_type"] == "OBJECT"  # was 'STRING' (double-encoded)
    assert json.loads(a["citation_report"]) == CITATION
    assert a["citation_status"] == "verified"  # the approval-inbox column; NULL before the fix
    assert (a["preview_type"], a["preview_text"], a["policy_type"]) == ("OBJECT", "Pursue the grant", "OBJECT")

    out = await _one(s, "SELECT status, approval_id, content_hash FROM outbox WHERE id = :id", id=draft)
    assert out == {"status": "pending", "approval_id": aid, "content_hash": content_hash(DRAFT)}
    reco = await _one(s, "SELECT status FROM recommendation WHERE id = :id", id=rid)
    assert reco == {"status": "pending_approval"}
    meta = await _audit_meta(s, "approval.requested", f"outbox:{draft}")
    assert meta is not None and meta["approval_id"] == aid and meta["policy"] == [GOV_DENY]
    assert api.events == [{"type": "approval.requested", "ids": [aid]}]

    again = await api.c.post(f"/v1/recommendations/{rid}/approve", headers=api.auth("analyst"))
    assert again.status_code == 200
    assert again.json()["approvals"] == [{"approval_id": aid, "status": "pending", "reused": True}]
    assert await _approvals_for(s, draft) == 1


async def test_h4_approve_without_drafts_requests_the_recommendation_itself(s: AsyncSession, api):
    rid = await _seed_reco(s)

    r = await api.c.post(f"/v1/recommendations/{rid}/approve", headers=api.auth("analyst"))

    assert r.status_code == 200, r.text
    aid = r.json()["approvals"][0]["approval_id"]
    a = await _one(
        s,
        "SELECT subject_type, subject_id, content_hash, JSON_TYPE(citation_report) AS cit_type, "
        "citation_report ->> '$.status' AS citation_status, preview ->> '$.recommendation.text' AS preview_text "
        "FROM approval WHERE id = :id",
        id=aid,
    )
    assert a == {
        "subject_type": "recommendation",
        "subject_id": rid,
        "content_hash": _reco_hash("Pursue the grant"),
        "cit_type": "OBJECT",
        "citation_status": "verified",
        "preview_text": "Pursue the grant",
    }
    reco = await _one(s, "SELECT status FROM recommendation WHERE id = :id", id=rid)
    assert reco == {"status": "pending_approval"}


async def test_patch_reports_the_recommendation_approval_its_trigger_invalidates(s: AsyncSession, api):
    """A recommendation without drafts is approved as itself; editing it lets trg_recommendation_invalidate invalidate
    that approval. The response and audit used to count only draft approvals and reported 0."""
    rid = await _seed_reco(s)
    r = await api.c.post(f"/v1/recommendations/{rid}/approve", headers=api.auth("analyst"))
    assert r.status_code == 200, r.text
    aid = r.json()["approvals"][0]["approval_id"]

    r = await api.c.patch(f"/v1/recommendations/{rid}", json={"text": "Pursue the grant, revised"},
                          headers=api.auth("analyst"))  # fmt: skip

    assert r.status_code == 200, r.text
    assert r.json()["approvals_invalidated"] == 1
    assert r.json()["status"] == "proposed"
    assert await _one(s, "SELECT decision FROM approval WHERE id = :id", id=aid) == {"decision": "invalidated"}


async def test_h4_approve_without_citation_report_stores_sql_null(s: AsyncSession, api):
    rid = await _seed_reco(s, citation=None)

    r = await api.c.post(f"/v1/recommendations/{rid}/approve", headers=api.auth("analyst"))

    assert r.status_code == 200, r.text
    aid = r.json()["approvals"][0]["approval_id"]
    a = await _one(s, "SELECT citation_report IS NULL AS is_null FROM approval WHERE id = :id", id=aid)
    assert a == {"is_null": 1}  # SQL NULL, not the JSON literal 'null' or the string "null"


async def test_h4_approve_with_stale_stored_hash_is_rejected(s: AsyncSession, api):
    """The route takes no body, so there is no 422; its input check is the stored-hash guard (409)."""
    rid = await _seed_reco(s, stored_hash="0" * 64)

    r = await api.c.post(f"/v1/recommendations/{rid}/approve", headers=api.auth("analyst"))

    assert r.status_code == 409
    assert r.json()["title"] == "Content hash mismatch"
    assert await _approvals_for(s, rid) == 0
    assert (await _one(s, "SELECT status FROM recommendation WHERE id = :id", id=rid)) == {"status": "proposed"}
    assert api.events == []


@pytest.mark.parametrize("missing", ["7e3f0c1a-0000-4000-8000-00000000c0de", "not-a-uuid"])
async def test_h4_approve_unknown_recommendation_is_404(s: AsyncSession, api, missing):
    r = await api.c.post(f"/v1/recommendations/{missing}/approve", headers=api.auth("analyst"))

    assert r.status_code == 404
    assert r.json()["detail"] == "recommendation not found"
    assert await _approvals_for(s, missing) == 0
    assert api.events == []


async def test_h4_approve_without_approval_request_is_403(s: AsyncSession, api):
    rid = await _seed_reco(s)
    draft = await _seed_outbox(s, rid, DRAFT)

    r = await api.c.post(f"/v1/recommendations/{rid}/approve", headers=api.auth("approver"))

    assert r.status_code == 403
    assert r.json()["permission"] == "approval:request"
    assert await _approvals_for(s, draft) == 0 and await _approvals_for(s, rid) == 0
    out = await _one(s, "SELECT status, approval_id FROM outbox WHERE id = :id", id=draft)
    assert out == {"status": "draft", "approval_id": None}
    assert "cortex.governance" not in api.opa.packages
    assert api.events == []


# ============================================================================= H9: ml_scorer.train, active-model branch
def _training_rows(n: int = 30, tail_won: int = 8) -> list[dict[str, Any]]:
    """Separable realised outcomes whose newest ``tail_won`` are all wins: the temporal holdout has one class only, so
    _holdout returns no candidate and train() compares against the active model's stored metrics (the H9 branch)."""
    names = ml_scorer.ml_config()["features"]["factors"]
    rnd = random.Random(7)
    t0 = datetime(2025, 1, 1, tzinfo=UTC)
    rows = []
    for i in range(n):
        won = i >= n - tail_won or i % 2 == 0
        fit = 0.8 + rnd.random() * 0.15 if won else 0.05 + rnd.random() * 0.15
        doc = {"factors": {k: {"value": fit if k == "strategic_fit" else 0.5, "available": True} for k in names}}
        rows.append(
            {
                "outcome_id": str(uuid.uuid4()),
                "result": "won" if won else "lost",
                "label_source": "realised",
                "closed_at": t0 + timedelta(days=i),
                "opportunity_id": str(uuid.uuid4()),
                "class": "grant",
                "factors": json.dumps(doc),  # as MySQL returns it
                "decision_time": 1,
                "completeness": 0.9,
                "amount": 250000,
            }
        )
    return rows


def _patch_rows(monkeypatch, rows: list[dict[str, Any]]) -> None:
    """Training-data SQL is covered by test_mysql_router_sql.test_scoring_and_ml_scorer_mysql; here it is fixed."""

    async def fake(_s: AsyncSession, _demo: bool) -> list[dict[str, Any]]:
        return rows

    monkeypatch.setattr(ml_scorer, "training_rows", fake)


async def _clear_active(s: AsyncSession, demo: bool) -> None:
    """Retire (inside the rolled-back transaction) any active model of this kind, so ours is the only one."""
    await s.execute(
        text(
            "UPDATE ml_model SET status = 'retired' WHERE org_id = :org AND name = :n AND trained_on_demo = :d "
            "AND status = 'active'"
        ),
        {"org": ORG, "n": ml_scorer.ml_config()["model_name"], "d": demo},
    )


async def _seed_active(s: AsyncSession, demo: bool, metrics: dict[str, Any]) -> tuple[str, int]:
    await _clear_active(s, demo)
    name = ml_scorer.ml_config()["model_name"]
    version = int(
        (
            await s.execute(
                text("SELECT COALESCE(max(version), 0) + 1 FROM ml_model WHERE org_id = :org AND name = :n"),
                {"org": ORG, "n": name},
            )
        ).scalar_one()
    )
    mid, blob = str(uuid.uuid4()), b"artifact-not-loaded-on-this-branch"
    await s.execute(
        text(
            "INSERT INTO ml_model (id, org_id, name, version, status, algorithm, features, metrics, trained_on_demo, "
            "n_samples, training_refs, artifact, artifact_sha256, trained_by, promoted_at, is_demo, label_source) "
            "VALUES (:id, :org, :n, :v, 'active', 'logistic_regression', CAST('[]' AS JSON), CAST(:m AS JSON), :d, "
            "30, CAST('[]' AS JSON), :blob, SHA2(:blob, 256), 'route-regression', NOW(6), :d, 'realised')"
        ),
        {"id": mid, "org": ORG, "n": name, "v": version, "m": json.dumps(metrics), "d": demo, "blob": blob},
    )
    raw = (await s.execute(text("SELECT metrics FROM ml_model WHERE id = :id"), {"id": mid})).scalar()
    assert isinstance(raw, str | bytes)  # the MySQL condition behind H9: active["metrics"] is JSON text
    return mid, version


async def _model_count(s: AsyncSession) -> int:
    return int(
        (
            await s.execute(
                text("SELECT count(*) FROM ml_model WHERE org_id = :org AND name = :n"),
                {"org": ORG, "n": ml_scorer.ml_config()["model_name"]},
            )
        ).scalar()
    )


async def test_h9_train_keeps_a_better_active_model(s: AsyncSession, monkeypatch):
    _patch_rows(monkeypatch, _training_rows())
    active_id, av = await _seed_active(s, False, {"auc": 1.0, "brier": 0.0, "n": 30})

    res = await ml_scorer.train(s, "user:route-regression", demo=False)  # was AttributeError: 'str' has no 'get'

    assert "candidate" not in res.metrics["holdout"]
    assert "cross-validation decides" in res.metrics["holdout"]["skipped"]
    assert res.status == "rejected" and res.version == av + 1
    assert re.search(rf"AUC [\d.]+ vs 1(\.0)?, Brier [\d.]+ vs 0(\.0)? \(active model v{av}\)", res.reason), res.reason
    assert res.reason.endswith("not better, kept as rejected")

    new = await _one(
        s,
        "SELECT status, version, decision_reason, promoted_at, trained_on_demo, JSON_TYPE(metrics) AS mt, "
        "metrics ->> '$.holdout.skipped' AS skipped, metrics ->> '$.n' AS n FROM ml_model WHERE id = :id",
        id=res.model_id,
    )
    assert new is not None
    assert (new["status"], new["version"], new["decision_reason"]) == ("rejected", av + 1, res.reason)
    assert new["promoted_at"] is None and new["trained_on_demo"] == 0
    assert (new["mt"], new["skipped"], new["n"]) == ("OBJECT", res.metrics["holdout"]["skipped"], "30")
    assert await _one(s, "SELECT status FROM ml_model WHERE id = :id", id=active_id) == {"status": "active"}


async def test_h9_train_replaces_a_worse_active_model(s: AsyncSession, monkeypatch):
    _patch_rows(monkeypatch, _training_rows())
    active_id, av = await _seed_active(s, False, {"auc": 0.0, "brier": 1.0, "n": 30})

    res = await ml_scorer.train(s, "user:route-regression", demo=False)

    assert res.status == "active" and res.reason.endswith("promoted")
    assert f"(active model v{av})" in res.reason
    assert await _one(s, "SELECT status FROM ml_model WHERE id = :id", id=active_id) == {"status": "retired"}
    new = await _one(
        s, "SELECT status, promoted_at IS NOT NULL AS promoted FROM ml_model WHERE id = :id", id=res.model_id
    )
    assert new == {"status": "active", "promoted": 1}  # ux_ml_model_active: the old one was retired first


async def test_h9_train_without_active_model_uses_the_baseline(s: AsyncSession, monkeypatch):
    """The no-record case: no active model to compare with, so the class-prior baseline is the reference."""
    _patch_rows(monkeypatch, _training_rows())
    await _clear_active(s, False)

    res = await ml_scorer.train(s, "user:route-regression", demo=False)

    assert "(the class-prior baseline)" in res.reason
    assert (res.status == "active") == res.reason.endswith("promoted")
    row_ = await _one(s, "SELECT status, decision_reason FROM ml_model WHERE id = :id", id=res.model_id)
    assert row_ == {"status": res.status, "decision_reason": res.reason}


async def test_h9_train_route_rejects_against_active_model(s: AsyncSession, api, monkeypatch):
    _patch_rows(monkeypatch, _training_rows())
    active_id, av = await _seed_active(s, True, {"auc": 1.0, "brier": 0.0, "n": 30})

    r = await api.c.post("/v1/ml/models/train", json={"demo": True}, headers=api.auth("admin"))

    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["status"], body["version"], body["rescored"]) == ("rejected", av + 1, 0)
    assert f"(active model v{av})" in body["reason"] and "candidate" not in body["metrics"]["holdout"]
    assert isinstance(body["metrics"]["candidates"], dict) and body["metrics"]["n"] == 30
    new = await _one(
        s, "SELECT status, trained_by, trained_on_demo, is_demo FROM ml_model WHERE id = :id", id=body["model_id"]
    )
    assert new == {"status": "rejected", "trained_by": SUB, "trained_on_demo": 1, "is_demo": 1}
    assert await _one(s, "SELECT status FROM ml_model WHERE id = :id", id=active_id) == {"status": "active"}
    meta = await _audit_meta(s, "ml_model.trained", f"ml_model:{body['model_id']}")
    assert meta is not None and (meta["status"], meta["version"], meta["rescored"]) == ("rejected", av + 1, 0)
    assert api.events == [] and api.redis.calls == []  # demo training: no rescore, no retrain-flag reset


@pytest.mark.parametrize("body", [{"demo": "maybe"}, {"demo": [1]}])
async def test_h9_train_route_invalid_body_is_422(s: AsyncSession, api, monkeypatch, body):
    _patch_rows(monkeypatch, _training_rows())
    before = await _model_count(s)

    r = await api.c.post("/v1/ml/models/train", json=body, headers=api.auth("admin"))

    assert r.status_code == 422 and r.json()["title"] == "Validation failed"
    assert await _model_count(s) == before


async def test_h9_train_route_insufficient_outcomes_is_422(s: AsyncSession, api, monkeypatch):
    _patch_rows(monkeypatch, _training_rows(n=6, tail_won=0))
    before = await _model_count(s)

    r = await api.c.post("/v1/ml/models/train", json={"demo": True}, headers=api.auth("admin"))

    assert r.status_code == 422
    assert r.json()["title"] == "Not enough realised outcomes"
    assert "6 realised won/lost outcomes" in r.json()["detail"]
    assert await _model_count(s) == before


async def test_h9_train_route_without_ml_train_is_403(s: AsyncSession, api, monkeypatch):
    _patch_rows(monkeypatch, _training_rows())
    before = await _model_count(s)

    r = await api.c.post("/v1/ml/models/train", json={"demo": True}, headers=api.auth("analyst"))

    assert r.status_code == 403 and r.json()["permission"] == "ml:train"
    assert await _model_count(s) == before
    assert api.redis.calls == []
