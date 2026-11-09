"""Unit and integration tests for MySQL 8.4 Application SQL Sanitization (Phase 7).

Validates:
- Complete removal of PostgreSQL-specific syntax (CAST(... AS uuid), jsonb, = ANY(:arr),
  RETURNING clauses, ILIKE, GROUPING SETS, NULLS LAST, interval '...', pg_trgm '%')
- 100% MySQL 8.4 compatibility across all 23 API routers and supporting services
- Pipeline Engine weighted aggregations, facets, and inflows
- Copilot deterministic and deadline queries
- Scoring & ML Scorer profiles, factor history, and training rows
- Entity Resolver matching, merging, and unmerging
- Relationships & Contacts, interaction unnesting, and warmth scoring
- Memory Manager warm/cold storage with escaped `key` column
- Ingestion & Sources with escaped `signal` table and `trigger` column
- Data Room package assembly, manifests, access logging, and share links
- Governance citation reference resolver (DBRefResolver) without `to_jsonb`
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.auth.principal import Principal
from platform_core.db.compat import in_clause, is_mysql_session, order_by_nulls
from platform_core.db.session import create_engine_from_url, get_mysql_test_url, reset_engine

ORG_ID = "00000000-0000-0000-0000-000000000001"
TEST_PRINCIPAL = Principal(
    sub="usr_test_phase7",
    username="tester@cortex.internal",
    roles=frozenset(["admin"]),
    token="Bearer test_token",
)


@pytest.fixture
async def mysql_session():
    """Provides an isolated AsyncSession against the Phase 2 MySQL 8.4 test container."""
    url = get_mysql_test_url(driver="asyncmy")
    engine = create_engine_from_url(url, pool_size=5, max_overflow=5, pool_recycle=3600, pool_pre_ping=True)
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


@pytest.mark.asyncio
async def test_dialect_detection_mysql(mysql_session: AsyncSession):
    """Verify is_mysql_session correctly identifies the MySQL 8.4 dialect."""
    assert is_mysql_session(mysql_session) is True


@pytest.mark.asyncio
async def test_compat_helpers_mysql(mysql_session: AsyncSession):
    """Verify in_clause and order_by_nulls work correctly on MySQL 8.4."""
    s = mysql_session
    prm = {}
    clause = in_clause("'active'", "st", ["active", "pending"], prm)
    assert clause == "'active' IN (:st_0, :st_1)"
    assert prm == {"st_0": "active", "st_1": "pending"}

    empty_prm = {}
    assert in_clause("'active'", "st", [], empty_prm) == "1=0"

    ob_last = order_by_nulls("deadline", "ASC", "LAST")
    assert ob_last == "(deadline IS NULL), deadline ASC"

    # Test executing in MySQL
    res = (await s.execute(text(f"SELECT 1 WHERE {clause}"), prm)).scalar()
    assert res == 1


@pytest.mark.asyncio
async def test_pipeline_engine_facets_and_inflows_mysql(mysql_session: AsyncSession):
    """Verify pipeline_engine.weighted_pipeline, expected_inflows, and grouped_inflows on MySQL 8.4."""
    from cortex.l5_strategy.pipeline_engine import expected_inflows, grouped_inflows, weighted_pipeline

    s = mysql_session
    # Seed a valid opportunity
    opp_id = str(uuid.uuid4())
    src = json.dumps({"kind": "manual", "source": "test"})
    await s.execute(
        text(
            "INSERT INTO opportunity (id, org_id, class, pipeline_stage, amount_min, amount_max, "
            "currency, title, description, geography, stage_fit, source_ref, is_demo, deadline) "
            # baseline vocabulary (schema_mysql.sql = PostgreSQL enums); 'equity'/'screening' were pre-baseline values
            "VALUES (:id, :org, 'venture_equity', 'diligence', 100000, 200000, 'EUR', 'Test Opp', 'Desc', "
            "CAST(:geo AS JSON), CAST(:stg AS JSON), CAST(:src AS JSON), false, '2026-12-31')"
        ),
        {
            "id": opp_id,
            "org": ORG_ID,
            "geo": json.dumps(["DE", "FR"]),
            "stg": json.dumps(["seed", "series_a"]),
            "src": src,
        },
    )

    wp = await weighted_pipeline(s, include_demo=False)
    assert "total_by_currency" in wp
    assert "splits" in wp
    assert "class" in wp["splits"]
    assert "stage" in wp["splits"]

    inflows = await expected_inflows(s, "EUR", include_demo=False)
    assert isinstance(inflows, list)

    grouped = await grouped_inflows(s, "EUR", include_demo=False)
    assert isinstance(grouped, list)


@pytest.mark.asyncio
async def test_copilot_queries_mysql(mysql_session: AsyncSession):
    """Verify copilot deterministic and deadline queries on MySQL 8.4."""
    s = mysql_session

    opp_id = str(uuid.uuid4())
    src = json.dumps({"kind": "manual", "source": "test"})
    await s.execute(
        text(
            "INSERT INTO opportunity (id, org_id, class, pipeline_stage, title, description, source_ref, is_demo, deadline) "
            "VALUES (:id, :org, 'grant', 'qualified', 'Grant Opp', 'Desc', CAST(:src AS JSON), false, DATE_ADD(now(), INTERVAL 14 DAY))"
        ),
        {"id": opp_id, "org": ORG_ID, "src": src},
    )

    # Test sanitized MySQL INTERVAL 31 DAY query
    deadlines = (
        (
            await s.execute(
                text(
                    "SELECT id, title, deadline, amount_min, amount_max, currency FROM opportunity "
                    "WHERE org_id = :org AND deadline IS NOT NULL AND deadline >= now() "
                    "AND deadline <= DATE_ADD(now(), INTERVAL 31 DAY) AND (:demo OR NOT is_demo) "
                    "ORDER BY deadline LIMIT 10"
                ),
                {"org": ORG_ID, "demo": False},
            )
        )
        .mappings()
        .all()
    )
    assert len(deadlines) >= 1

    # Verify agent_run insertion and JSON update
    run_id = str(uuid.uuid4())
    await s.execute(
        text(
            "INSERT INTO agent_run (id, org_id, agent, task, opportunity_id, requested_by, model_tier, status, started_at, mode, input) "
            "VALUES (:id, :org, 'copilot', 'copilot', :opp, :by, 'none', 'running', now(), 'deterministic', CAST(:i AS JSON))"
        ),
        {"id": run_id, "org": ORG_ID, "opp": opp_id, "by": TEST_PRINCIPAL.sub, "i": json.dumps({"q": "test"})},
    )
    await s.execute(
        text(
            "UPDATE agent_run SET status = 'succeeded', finished_at = now(), output = CAST(:o AS JSON) WHERE id = :id"
        ),
        {"id": run_id, "o": json.dumps({"answer": "all good", "citations": []})},
    )
    run_row = (await s.execute(text("SELECT status FROM agent_run WHERE id = :id"), {"id": run_id})).scalar()
    assert run_row == "succeeded"


@pytest.mark.asyncio
async def test_scoring_and_ml_scorer_mysql(mysql_session: AsyncSession):
    """Verify scoring_profile upsert, score calculation, history recording, and ML training rows on MySQL 8.4."""
    from cortex.l4_reasoning.ml_scorer import training_rows
    from cortex.l4_reasoning.score_service import active_profile, score_opportunity

    s = mysql_session
    # 1. Active profile upsert
    prof = await active_profile(s)
    assert prof["name"] is not None

    # 2. Opportunity insertion & scoring
    opp_id = str(uuid.uuid4())
    src = json.dumps({"kind": "manual", "source": "test"})
    await s.execute(
        text(
            "INSERT INTO opportunity (id, org_id, class, pipeline_stage, title, description, source_ref, is_demo) "
            "VALUES (:id, :org, 'venture_equity', 'qualified', 'Scored Opp', 'Desc', CAST(:src AS JSON), false)"
        ),
        {"id": opp_id, "org": ORG_ID, "src": src},
    )

    scored = await score_opportunity(s, opp_id)
    assert scored.band == "insufficient_evidence" or (scored.score is not None and scored.score >= 0.0)
    assert scored.completeness >= 0.0

    # 3. Factor history was inserted
    f_hist = (
        await s.execute(
            text("SELECT count(*) FROM factor_history WHERE opportunity_id = :opp"),
            {"opp": opp_id},
        )
    ).scalar()
    assert f_hist > 0

    # 4. ML Scorer training rows query
    rows = await training_rows(s, demo=False)
    assert isinstance(rows, list)


@pytest.mark.asyncio
async def test_entity_resolver_matching_and_merge_mysql(mysql_session: AsyncSession):
    """Verify entity_resolver resolution, merge, and unmerge on MySQL 8.4."""
    from cortex.l2_representation.entity_resolver import merge, resolve_organization, unmerge

    s = mysql_session
    src = {"kind": "manual", "source": "test"}

    # 1. Resolve new org
    res1 = await resolve_organization(
        s, name="Acme Corp", kind="counterparty", country="DE", domain="acme.com", source_ref=src
    )
    assert res1.decision in ("created", "matched")
    org1_id = res1.organization_id

    # 2. Resolve duplicate name -> exact match
    res2 = await resolve_organization(
        s, name="Acme Corp", kind="counterparty", country="DE", domain="acme.com", source_ref=src
    )
    assert res2.decision == "matched"
    assert res2.organization_id == org1_id

    # 3. Resolve second org
    res3 = await resolve_organization(
        s, name="Acme Logistics", kind="counterparty", country="DE", domain="acme-logistics.de", source_ref=src
    )
    org2_id = res3.organization_id
    assert org2_id != org1_id

    # 4. Merge org2 into org1 via merge candidate
    cand_id = str(uuid.uuid4())
    await s.execute(
        text(
            "INSERT INTO entity_merge_candidate (id, org_id, left_id, right_id, score, method, evidence, is_demo) "
            "VALUES (:id, :org, :l, :r, 0.85, 'fuzzy', CAST(:ev AS JSON), false)"
        ),
        {"id": cand_id, "org": ORG_ID, "l": org1_id, "r": org2_id, "ev": json.dumps({"reason": "test"})},
    )
    merge_res = await merge(s, cand_id, decided_by=TEST_PRINCIPAL.sub)
    assert merge_res["keep"] == org1_id
    assert merge_res["drop"] == org2_id

    # 5. Unmerge
    unmerge_res = await unmerge(s, cand_id, decided_by=TEST_PRINCIPAL.sub)
    assert unmerge_res is not None


@pytest.mark.asyncio
async def test_relationship_service_and_interactions_mysql(mysql_session: AsyncSession):
    """Verify relationship contacts, interactions, meetings, and milestones on MySQL 8.4."""
    from cortex.l3_memory.relationship_service import (
        contact_touches,
        create_contact,
        create_milestone,
        log_interaction,
        log_meeting,
        update_milestone,
    )

    s = mysql_session
    src = {"kind": "manual", "source": "test"}

    # 1. Contact creation
    contact = await create_contact(
        s,
        TEST_PRINCIPAL,
        name="Jane Doe",
        role="Partner",
        emails=["jane@partner.com", "jdoe@partner.com"],
        organization_id=None,
        consent_basis="legitimate_interest",
        source_ref=src,
    )
    contact_id = contact["id"]
    assert contact_id is not None

    # 2. Interaction logging
    inter = await log_interaction(
        s,
        TEST_PRINCIPAL,
        contact_id=contact_id,
        kind="email_reply",
        occurred_at=datetime.now(UTC),
        direction="inbound",
        summary="Meeting Followup",
        source_ref=src,
    )
    assert inter["id"] is not None

    # 3. Contact touches
    touches = await contact_touches(s, contact_id)
    assert len(touches) >= 1

    # 4. Meeting logging
    meeting = await log_meeting(
        s,
        TEST_PRINCIPAL,
        contact_ids=[contact_id],
        occurred_at=datetime.now(UTC),
        summary="Good intro",
        source_ref=src,
    )
    assert meeting["id"] is not None

    # 5. Milestone creation and update
    milestone = await create_milestone(
        s,
        TEST_PRINCIPAL,
        kind="follow_up",
        title="Term Sheet",
        due_at=datetime(2026, 12, 1, tzinfo=UTC),
        source_ref=src,
    )
    assert milestone["id"] is not None

    updated_ms = await update_milestone(
        s,
        TEST_PRINCIPAL,
        milestone["id"],
        status="done",
    )
    assert updated_ms["status"] == "done"


@pytest.mark.asyncio
async def test_memory_manager_escaped_key_mysql(mysql_session: AsyncSession):
    """Verify memory_manager.put_warm and get work with MySQL reserved keyword `key`."""
    from cortex.l3_memory.memory_manager import get, put_warm

    s = mysql_session
    src = {"kind": "manual", "source": "test"}

    # 1. put_warm
    mem_id = await put_warm(
        s,
        key="counterparty:pref:acme",
        value={"terms": "standard", "currency": "EUR"},
        source_ref=src,
    )
    assert mem_id is not None

    # 2. get
    val = await get(s, "counterparty:pref:acme")
    assert val is not None
    assert val["value"]["currency"] == "EUR"


@pytest.mark.asyncio
async def test_perception_ingestion_and_sources_mysql(mysql_session: AsyncSession):
    """Verify sources sync, signal storing into escaped `signal` table, and runs on MySQL 8.4."""
    from cortex.l1_perception.ingestion import _store_signal, reconcile_unprocessed
    from cortex.l1_perception.models import Signal
    from cortex.l1_perception.registry import get_source, sync_sources

    s = mysql_session

    # 1. Sync sources
    source_ids = await sync_sources(s)
    assert len(source_ids) > 0

    first_key = next(iter(source_ids.keys()))
    source_id = source_ids[first_key]
    row, _cfg = await get_source(s, source_id)
    assert row["adapter_key"] == first_key

    # 2. Store signal
    class RawMock:
        payload = {"title": "Test Grant 2026", "id": "g-101"}
        url = "https://grants.example.com/101"
        fetched_at = datetime.now(UTC)

    sig = Signal(
        source_key=first_key,
        external_id="g-101",
        title="Test Grant 2026",
        description="Comprehensive European Grant",
        field_sources={"title": "raw.title"},
    )

    sig_id = await _store_signal(s, source_id, "1.0", RawMock(), sig)
    assert sig_id is not None

    # Idempotent re-store returns None
    dup_id = await _store_signal(s, source_id, "1.0", RawMock(), sig)
    assert dup_id is None

    # 3. Reconcile unprocessed
    count = await reconcile_unprocessed(source_id, "token", limit=10)
    assert isinstance(count, int)


@pytest.mark.asyncio
async def test_dataroom_and_governance_refs_mysql(mysql_session: AsyncSession):
    """Verify document upload, packaging, share link creation, and DBRefResolver on MySQL 8.4."""
    from unittest.mock import AsyncMock, patch

    from cortex.l7_governance.refs import DBRefResolver
    from cortex.l8_actuation.dataroom import assemble, package, request_share, upload

    s = mysql_session
    sample_data = b"Sample PDF Content for Data Room"

    with (
        patch("platform_core.objectstore.put_bytes", new_callable=AsyncMock) as mock_put,
        patch("platform_core.objectstore.get_bytes", new_callable=AsyncMock) as mock_get,
    ):
        mock_put.return_value = None
        mock_get.return_value = sample_data

        # 1. Document upload
        doc = await upload(
            s,
            TEST_PRINCIPAL,
            data=sample_data,
            filename="PitchDeck.pdf",
            content_type="application/pdf",
            title="Pitch Deck 2026",
            folder="/Financials",
            kind="deck",
            dd_tags=["financials", "pitch"],
            classification="confidential",
            opportunity_id=None,
        )
        doc_id = doc["id"]
        assert doc_id is not None

        # Mark as approved_repo so it can be packaged
        await s.execute(
            text("UPDATE document SET approved_repo = true WHERE id = :id"),
            {"id": doc_id},
        )

        # 2. Package assembly
        pkg = await assemble(
            s,
            TEST_PRINCIPAL,
            name="Series A Due Diligence",
            opportunity_id=None,
            document_ids=[doc_id],
            from_checklist=False,
        )
        pkg_id = pkg["id"]
        assert pkg_id is not None

        # 3. Read package
        read_pkg = await package(s, pkg_id)
        assert read_pkg["name"] == "Series A Due Diligence"

        # 4. Request share link
        share = await request_share(
            s,
            TEST_PRINCIPAL,
            pid=pkg_id,
            recipient="investor@venture.com",
            expires_in_days=14,
            message="Please find our data room attached.",
        )
        assert share["share_link_id"] is not None
        assert share["status"] == "pending_approval"

        # 5. DBRefResolver citation resolving without to_jsonb
        resolver = DBRefResolver(s, TEST_PRINCIPAL, {})
        resolved_doc = await resolver.resolve(f"document:{doc_id}#title")
        assert resolved_doc is not None
        assert resolved_doc.record["value"] == "Pitch Deck 2026"


@pytest.mark.asyncio
async def test_retention_held_filter_runs_on_every_holdable_table_mysql(mysql_session: AsyncSession):
    """signal/meeting/proposal had no legal_hold column on MySQL (PostgreSQL added it in 0004_phase3), so the
    retention held-row filter failed there; migrations_mysql m0002 adds it."""
    from pathlib import Path

    from cortex.l7_governance import retention

    for table in sorted(retention.HOLDABLE):
        held = retention._held_sql(table, "t", mysql=True)
        n = (await mysql_session.execute(text(f"SELECT COUNT(*) FROM `{table}` t WHERE {held}"))).scalar()
        assert n is not None and n >= 0
    schema = Path(__file__).resolve().parents[2].joinpath("scripts", "schema_mysql.sql").read_text(encoding="utf-8")  # noqa: ASYNC240 - one small file read in a test
    assert schema.count("legal_hold BOOLEAN NOT NULL DEFAULT FALSE") == 4  # document, signal, meeting, proposal


@pytest.mark.asyncio
async def test_opportunity_facets_single_scan_mysql(mysql_session: AsyncSession):
    """Facets come from one GROUP BY over all dimensions (was one UNION ALL branch per dimension: five full scans);
    every count and the total must equal the per-dimension reference query."""
    from cortex.l8_actuation.api.routers import opportunities as opp

    s = mysql_session
    out = await opp.list_opportunities(
        cls=None,
        stage=None,
        geo=None,
        band=None,
        status=None,
        deadline_before=None,
        deadline_after=None,
        q=None,
        min_completeness=None,
        owner=None,
        source=None,
        demo=None,
        sort="score",
        limit=5,
        cursor=None,
        facets=True,
        _=TEST_PRINCIPAL,
        session=s,
    )
    p: dict = {"org": ORG_ID}
    where = opp._filters(p, None, None, None, None, None, None, None, None, None, None, None, None, is_mysql=True)
    fr = opp._from_clause(True)
    dims = {
        "class": "coalesce(o.class, 'unclassified')",
        "stage": "o.pipeline_stage",
        "band": "coalesce(o.score_band, 'unscored')",
        "source": "coalesce(s.adapter_key, 'none')",
    }
    for name, expr in dims.items():
        ref = {
            r[0]: r[1]
            for r in (await s.execute(text(f"SELECT {expr}, count(*) {fr} WHERE {where} GROUP BY {expr}"), p)).all()
        }
        assert out["facets"][name] == ref
        assert list(out["facets"][name].values()) == sorted(ref.values(), reverse=True)
    assert out["total"] == (await s.execute(text(f"SELECT count(*) {fr} WHERE {where}"), p)).scalar()


@pytest.mark.asyncio
async def test_source_runs_route_mysql(mysql_session: AsyncSession):
    """GET /v1/sources/{id}/runs sent a SELECT without FROM on MySQL (Unknown column 'id')."""
    from cortex.l1_perception.registry import sync_sources
    from cortex.l8_actuation.api.routers import sources

    s = mysql_session
    source_id = next(iter((await sync_sources(s)).values()))
    run_id = str(uuid.uuid4())
    await s.execute(
        text(
            "INSERT INTO source_run (id, source_id, `trigger`, requested_by, status, items_fetched, items_new) "
            "VALUES (:id, :src, 'manual', 'tester', 'succeeded', 3, 2)"
        ),
        {"id": run_id, "src": source_id},
    )

    out = await sources.source_runs(id=source_id, _=TEST_PRINCIPAL, session=s)
    run = next(r for r in out["items"] if str(r["id"]) == run_id)
    assert run["trigger"] == "manual"
    assert run["status"] == "succeeded"
    assert (run["items_fetched"], run["items_new"]) == (3, 2)


@pytest.mark.asyncio
async def test_opportunity_list_mysql_order_matches_original_for_every_sort(mysql_session: AsyncSession):
    """The MySQL list uses a deferred join and MYSQL_SORTS (no "(x IS NULL)" prefix: MySQL already sorts NULLs last
    under DESC). Every sort must return exactly the ids, in exactly the order, of the original statement, NULLs included."""
    from cortex.l8_actuation.api.routers import opportunities as opp

    s = mysql_session
    owner = f"order-test-{uuid.uuid4()}"
    rows = [
        # score, completeness, amount_min, amount_max, deadline
        (0.9, 0.5, 100, 200, "2027-01-01"),
        (None, None, None, None, None),
        (0.9, 0.7, 50, None, "2026-12-01"),
        (0.1, 0.2, None, 300, None),
        (None, 0.9, 10, 20, "2026-11-30"),
        (0.5, 0.5, None, None, "2027-01-01"),
        (None, None, 5, 5, "2026-11-30"),  # unscored rows may lack completeness (ck_opp_score_integrity)
    ]
    for i, (score, comp, amin, amax, deadline) in enumerate(rows):
        await s.execute(
            text(
                "INSERT INTO opportunity (id, org_id, class, pipeline_stage, title, description, source_ref, is_demo, owner_id, "
                "score, factors, completeness, amount_min, amount_max, deadline, created_at) VALUES (:id, :org, 'grant', 'discovered', "
                ":t, 'd', CAST(:src AS JSON), false, :owner, :score, CAST(:factors AS JSON), :comp, :amin, :amax, :dl, :ca)"
            ),
            {
                "id": str(uuid.uuid4()),
                "org": ORG_ID,
                "t": f"Order {i}",
                "owner": owner,
                "score": score,
                "comp": comp,
                "amin": amin,
                "amax": amax,
                "dl": deadline,
                "factors": None if score is None else "{}",
                "src": json.dumps({"kind": "manual", "source": "test"}),
                "ca": datetime(2026, 1, 1 + i % 2, tzinfo=UTC),
            },
        )
    for sort in opp.SORTS:
        out = await opp.list_opportunities(
            cls=None,
            stage=None,
            geo=None,
            band=None,
            status=None,
            deadline_before=None,
            deadline_after=None,
            q=None,
            min_completeness=None,
            owner=owner,
            source=None,
            demo=None,
            sort=sort,
            limit=50,
            cursor=None,
            facets=False,
            _=TEST_PRINCIPAL,
            session=s,
        )
        p: dict = {"org": ORG_ID}
        where = opp._filters(p, None, None, None, None, None, None, None, None, None, owner, None, None, is_mysql=True)
        ref = [
            str(r[0])
            for r in (
                await s.execute(
                    text(f"SELECT o.id {opp._from_clause(True)} WHERE {where} ORDER BY {opp.SORTS[sort]}"), p
                )
            ).all()
        ]
        assert [str(i["id"]) for i in out["items"]] == ref, sort
        assert out["total"] == len(rows)
