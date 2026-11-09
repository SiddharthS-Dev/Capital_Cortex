"""Unit and concurrency tests for MySQL 8.4 Triggers, Invariants, and Mutex Migration (Phase 6).

Validates:
- Invariant I1 (No-Fabrication & Provenance CHECK constraints across knowledge tables)
- Invariant I2 (Recommendation evidence & confidence constraints)
- Invariant I3 (Outbox approval validation, edit invalidation, and sent payload immutability)
- Invariant I3b (Recommendation invalidation on content_hash modification)
- Audit log append-only triggers (UPDATE and DELETE blocking)
- Partial unique index emulations via virtual generated columns (active profile, latest document, merge pairs)
- Audit mutex table (`audit_lock`) row-level locking semantics (`FOR UPDATE`)
- Mutex lock release on commit and exception/rollback
- Concurrent multi-session audit append stress testing with SHA-256 hash chain verification
"""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.audit import append, verify_chain
from platform_core.db.session import create_engine_from_url, get_mysql_test_url, reset_engine

ORG_ID = "00000000-0000-0000-0000-000000000001"
VALID_SOURCE = json.dumps({"kind": "manual", "source": "unit_test", "id": "t1"})


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
async def test_i1_provenance_check_mysql(mysql_session: AsyncSession):
    """Verify Invariant I1 (no fabrication): records must cite a valid source_ref or inference_id."""
    s = mysql_session

    # 1. Reject missing source_ref and missing inference_id
    with pytest.raises((IntegrityError, OperationalError)):
        async with s.begin_nested():
            await s.execute(
                text(
                    "INSERT INTO organization (id, org_id, name, kind) VALUES (:id, :org, 'NoSource', 'counterparty')"
                ),
                {"id": str(uuid.uuid4()), "org": ORG_ID},
            )

    # 2. Reject empty JSON object '{}'
    with pytest.raises((IntegrityError, OperationalError)):
        async with s.begin_nested():
            await s.execute(
                text(
                    "INSERT INTO organization (id, org_id, name, kind, source_ref) "
                    "VALUES (:id, :org, 'EmptySourceObj', 'counterparty', '{}')"
                ),
                {"id": str(uuid.uuid4()), "org": ORG_ID},
            )

    # 3. Reject empty JSON array '[]'
    with pytest.raises((IntegrityError, OperationalError)):
        async with s.begin_nested():
            await s.execute(
                text(
                    "INSERT INTO organization (id, org_id, name, kind, source_ref) "
                    "VALUES (:id, :org, 'EmptySourceArr', 'counterparty', '[]')"
                ),
                {"id": str(uuid.uuid4()), "org": ORG_ID},
            )

    # 4. Accept valid non-empty source_ref JSON
    org_id1 = str(uuid.uuid4())
    await s.execute(
        text(
            "INSERT INTO organization (id, org_id, name, kind, source_ref) "
            "VALUES (:id, :org, 'SourcedOrg', 'counterparty', :src)"
        ),
        {"id": org_id1, "org": ORG_ID, "src": VALID_SOURCE},
    )
    row = (await s.execute(text("SELECT name FROM organization WHERE id = :id"), {"id": org_id1})).scalar()
    assert row == "SourcedOrg"

    # 5. Inference basis requirement
    with pytest.raises((IntegrityError, OperationalError)):
        async with s.begin_nested():
            await s.execute(
                text(
                    "INSERT INTO inference (id, org_id, method, produced_by, basis_refs) "
                    "VALUES (:id, :org, 'rule', 'test', '[]')"
                ),
                {"id": str(uuid.uuid4()), "org": ORG_ID},
            )

    inf_id = str(uuid.uuid4())
    await s.execute(
        text(
            "INSERT INTO inference (id, org_id, method, produced_by, basis_refs) "
            "VALUES (:id, :org, 'rule', 'test', :basis)"
        ),
        {"id": inf_id, "org": ORG_ID, "basis": json.dumps([{"signal": "s1"}])},
    )

    # 6. Sourced via inference_id with null source_ref succeeds
    org_id2 = str(uuid.uuid4())
    await s.execute(
        text(
            "INSERT INTO organization (id, org_id, name, kind, inference_id) "
            "VALUES (:id, :org, 'InferredOrg', 'counterparty', :inf)"
        ),
        {"id": org_id2, "org": ORG_ID, "inf": inf_id},
    )
    row2 = (await s.execute(text("SELECT name FROM organization WHERE id = :id"), {"id": org_id2})).scalar()
    assert row2 == "InferredOrg"


@pytest.mark.asyncio
async def test_i2_recommendation_evidence_and_confidence_mysql(mysql_session: AsyncSession):
    """Verify Invariant I2: recommendations require non-empty evidence array and confidence in [0, 1]."""
    s = mysql_session

    # 1. Reject empty evidence array
    with pytest.raises((IntegrityError, OperationalError)):
        async with s.begin_nested():
            await s.execute(
                text(
                    "INSERT INTO recommendation (id, org_id, text, confidence, evidence, reasoning, source_ref) "
                    "VALUES (:id, :org, 'Reco', 0.8, '[]', '{}', :src)"
                ),
                {"id": str(uuid.uuid4()), "org": ORG_ID, "src": VALID_SOURCE},
            )

    # 2. Reject confidence > 1.0
    with pytest.raises((IntegrityError, OperationalError)):
        async with s.begin_nested():
            await s.execute(
                text(
                    "INSERT INTO recommendation (id, org_id, text, confidence, evidence, reasoning, source_ref) "
                    "VALUES (:id, :org, 'Reco', 1.5, :ev, '{}', :src)"
                ),
                {"id": str(uuid.uuid4()), "org": ORG_ID, "ev": json.dumps([{"fact": "f1"}]), "src": VALID_SOURCE},
            )

    # 3. Accept valid recommendation
    reco_id = str(uuid.uuid4())
    await s.execute(
        text(
            "INSERT INTO recommendation (id, org_id, text, confidence, evidence, reasoning, source_ref) "
            "VALUES (:id, :org, 'RecoValid', 0.85, :ev, '{}', :src)"
        ),
        {"id": reco_id, "org": ORG_ID, "ev": json.dumps([{"fact": "f1"}]), "src": VALID_SOURCE},
    )
    res = (await s.execute(text("SELECT text, confidence FROM recommendation WHERE id = :id"), {"id": reco_id})).one()
    assert res.text == "RecoValid"
    assert float(res.confidence) == 0.85


@pytest.mark.asyncio
async def test_i3_outbox_trigger_behavior_mysql(mysql_session: AsyncSession):
    """Verify Invariant I3: outbox approval enforcement, payload edit invalidation, and sent immutability."""
    s = mysql_session

    appr_id = str(uuid.uuid4())
    await s.execute(
        text(
            "INSERT INTO approval (id, org_id, subject_type, subject_id, content_hash, requested_by, approver_id, decision) "
            "VALUES (:id, :org, 'outbox', :subj, 'hash_initial', 'alice', 'bob', 'approved')"
        ),
        {"id": appr_id, "org": ORG_ID, "subj": str(uuid.uuid4())},
    )

    # 1. Reject outbox with status='approved' but approval_id IS NULL
    with pytest.raises((IntegrityError, OperationalError)):
        async with s.begin_nested():
            await s.execute(
                text(
                    "INSERT INTO outbox (id, org_id, channel, payload, content_hash, status, created_by) "
                    "VALUES (:id, :org, 'email', '{\"msg\": 1}', 'hash_initial', 'approved', 'alice')"
                ),
                {"id": str(uuid.uuid4()), "org": ORG_ID},
            )

    # 2. Insert valid approved outbox referencing approval
    ob_id = str(uuid.uuid4())
    await s.execute(
        text(
            "INSERT INTO outbox (id, org_id, channel, payload, content_hash, approval_id, status, created_by) "
            "VALUES (:id, :org, 'email', '{\"body\": \"v1\"}', 'hash_initial', :appr, 'approved', 'alice')"
        ),
        {"id": ob_id, "org": ORG_ID, "appr": appr_id},
    )

    # 3. Edit payload -> trigger trg_outbox_invalidate resets status to draft, clears approval_id, marks approval invalidated
    await s.execute(
        text("UPDATE outbox SET payload = '{\"body\": \"v2\"}', content_hash = 'hash_v2' WHERE id = :id"),
        {"id": ob_id},
    )
    ob_row = (await s.execute(text("SELECT status, approval_id FROM outbox WHERE id = :id"), {"id": ob_id})).one()
    assert ob_row.status == "draft"
    assert ob_row.approval_id is None

    appr_dec = (await s.execute(text("SELECT decision FROM approval WHERE id = :id"), {"id": appr_id})).scalar()
    assert appr_dec == "invalidated"

    # 4. Re-approve and transition to 'sent'
    await s.execute(text("UPDATE approval SET decision = 'approved' WHERE id = :id"), {"id": appr_id})
    await s.execute(
        text("UPDATE outbox SET approval_id = :appr, status = 'sent' WHERE id = :id"),
        {"id": ob_id, "appr": appr_id},
    )

    # 5. Non-payload updates on sent outbox (e.g. error or delivery) succeed
    await s.execute(text("UPDATE outbox SET attempts = attempts + 1 WHERE id = :id"), {"id": ob_id})
    attempts = (await s.execute(text("SELECT attempts FROM outbox WHERE id = :id"), {"id": ob_id})).scalar()
    assert attempts == 1

    # 6. Payload modification on 'sent' outbox is rejected by trigger
    with pytest.raises(DBAPIError, match="outbox payload is immutable once sent"):
        async with s.begin_nested():
            await s.execute(
                text('UPDATE outbox SET payload = \'{"body": "v3"}\' WHERE id = :id'),
                {"id": ob_id},
            )


@pytest.mark.asyncio
async def test_recommendation_invalidation_trigger_mysql(mysql_session: AsyncSession):
    """Verify trg_recommendation_invalidate: editing content_hash resets status to proposed and invalidates approval."""
    s = mysql_session

    reco_id = str(uuid.uuid4())
    appr_id = str(uuid.uuid4())

    await s.execute(
        text(
            "INSERT INTO recommendation (id, org_id, text, confidence, evidence, reasoning, source_ref, content_hash, status) "
            "VALUES (:id, :org, 'Pursue deal', 0.95, :ev, '{}', :src, 'rh1', 'approved')"
        ),
        {"id": reco_id, "org": ORG_ID, "ev": json.dumps([{"e": 1}]), "src": VALID_SOURCE},
    )
    await s.execute(
        text(
            "INSERT INTO approval (id, org_id, subject_type, subject_id, content_hash, requested_by, approver_id, decision) "
            "VALUES (:id, :org, 'recommendation', :reco, 'rh1', 'alice', 'bob', 'approved')"
        ),
        {"id": appr_id, "org": ORG_ID, "reco": reco_id},
    )

    # Edit recommendation content hash
    await s.execute(
        text("UPDATE recommendation SET content_hash = 'rh2' WHERE id = :id"),
        {"id": reco_id},
    )

    r_status = (await s.execute(text("SELECT status FROM recommendation WHERE id = :id"), {"id": reco_id})).scalar()
    assert r_status == "proposed"

    a_dec = (await s.execute(text("SELECT decision FROM approval WHERE id = :id"), {"id": appr_id})).scalar()
    assert a_dec == "invalidated"


@pytest.mark.asyncio
async def test_audit_log_immutability_triggers_mysql(mysql_session: AsyncSession):
    """Verify trg_audit_no_update and trg_audit_no_delete prevent modifying or deleting audit records."""
    s = mysql_session

    # Append a test record
    rec = await append(s, org_id=ORG_ID, actor="system", action="test.immutable", target="t1", meta={"x": 1})
    assert rec.seq >= 1

    # Attempt UPDATE
    with pytest.raises(DBAPIError, match="audit_log is append-only"):
        async with s.begin_nested():
            await s.execute(
                text("UPDATE audit_log SET actor = 'malicious' WHERE seq = :seq"),
                {"seq": rec.seq},
            )

    # Attempt DELETE
    with pytest.raises(DBAPIError, match="audit_log is append-only"):
        async with s.begin_nested():
            await s.execute(
                text("DELETE FROM audit_log WHERE seq = :seq"),
                {"seq": rec.seq},
            )


@pytest.mark.asyncio
async def test_partial_unique_index_emulations_mysql(mysql_session: AsyncSession):
    """Verify partial unique constraint emulations using virtual generated columns."""
    s = mysql_session

    # Isolation: the shared test database can already hold an active profile for ORG_ID (score_service auto-creates
    # `syrs_default` when scoring runs). Deactivate it inside this test's transaction, which the fixture rolls back,
    # so the scenario below starts from "no active profile" without changing the database.
    await s.execute(text("UPDATE scoring_profile SET active = FALSE WHERE org_id = :org AND active"), {"org": ORG_ID})

    # 1. Scoring profile: only 1 active profile per org_id
    prof1 = str(uuid.uuid4())
    prof2 = str(uuid.uuid4())
    prof3 = str(uuid.uuid4())

    # Two inactive profiles are allowed
    await s.execute(
        text(
            "INSERT INTO scoring_profile (id, org_id, name, version, weights, thresholds, active) "
            "VALUES (:id, :org, 'p1', 1, '{}', '{}', FALSE)"
        ),
        {"id": prof1, "org": ORG_ID},
    )
    await s.execute(
        text(
            "INSERT INTO scoring_profile (id, org_id, name, version, weights, thresholds, active) "
            "VALUES (:id, :org, 'p2', 1, '{}', '{}', FALSE)"
        ),
        {"id": prof2, "org": ORG_ID},
    )

    # First active profile succeeds
    await s.execute(
        text(
            "INSERT INTO scoring_profile (id, org_id, name, version, weights, thresholds, active) "
            "VALUES (:id, :org, 'p3', 1, '{}', '{}', TRUE)"
        ),
        {"id": prof3, "org": ORG_ID},
    )

    # Second active profile for same org fails unique constraint ux_scoring_profile_active
    with pytest.raises((IntegrityError, OperationalError)):
        async with s.begin_nested():
            await s.execute(
                text(
                    "INSERT INTO scoring_profile (id, org_id, name, version, weights, thresholds, active) "
                    "VALUES (:id, :org, 'p4', 1, '{}', '{}', TRUE)"
                ),
                {"id": str(uuid.uuid4()), "org": ORG_ID},
            )

    # 2. Entity merge candidate: unordered pair uniqueness LEAST/GREATEST
    left_id = str(uuid.uuid4())
    right_id = str(uuid.uuid4())
    mc1 = str(uuid.uuid4())

    await s.execute(
        text(
            "INSERT INTO entity_merge_candidate (id, org_id, left_id, right_id, score, method, evidence) "
            "VALUES (:id, :org, :l, :r, 0.9, 'fuzzy', '{}')"
        ),
        {"id": mc1, "org": ORG_ID, "l": left_id, "r": right_id},
    )

    # Inverted pair (right, left) must be rejected by ux_merge_pair
    with pytest.raises((IntegrityError, OperationalError)):
        async with s.begin_nested():
            await s.execute(
                text(
                    "INSERT INTO entity_merge_candidate (id, org_id, left_id, right_id, score, method, evidence) "
                    "VALUES (:id, :org, :l, :r, 0.95, 'fuzzy', '{}')"
                ),
                {"id": str(uuid.uuid4()), "org": ORG_ID, "l": right_id, "r": left_id},
            )


@pytest.mark.asyncio
async def test_audit_mutex_lock_acquisition_and_release():
    """Verify audit_lock row-level locking: exclusive hold and immediate release upon commit."""
    url = get_mysql_test_url(driver="asyncmy")
    engine = create_engine_from_url(url, pool_size=5, max_overflow=5)

    async with engine.connect() as conn1:
        tx1 = await conn1.begin()
        # Session 1 acquires exclusive lock on row 1
        res1 = await conn1.execute(text("SELECT id FROM audit_lock WHERE id = 1 FOR UPDATE"))
        assert res1.scalar() == 1

        # Session 2 attempts to acquire lock with NOWAIT -> should fail immediately
        async with engine.connect() as conn2:
            tx2 = await conn2.begin()
            with pytest.raises(DBAPIError, match=r"(3572|Lock wait timeout|Statement aborted)"):
                await conn2.execute(text("SELECT id FROM audit_lock WHERE id = 1 FOR UPDATE NOWAIT"))
            await tx2.rollback()

        # Session 1 commits, releasing the lock
        await tx1.commit()

    # Session 2 can now acquire the lock immediately
    async with engine.connect() as conn3:
        tx3 = await conn3.begin()
        res3 = await conn3.execute(text("SELECT id FROM audit_lock WHERE id = 1 FOR UPDATE NOWAIT"))
        assert res3.scalar() == 1
        await tx3.rollback()

    await engine.dispose()


@pytest.mark.asyncio
async def test_audit_mutex_rollback_releases_lock_and_preserves_chain():
    """Verify rollback releases audit_lock and does not leave broken hash sequences."""
    url = get_mysql_test_url(driver="asyncmy")
    engine = create_engine_from_url(url, pool_size=5, max_overflow=5)

    # 1. Session 1 begins transaction, appends, but rolls back
    async with engine.connect() as conn1:
        tx1 = await conn1.begin()
        s1 = AsyncSession(bind=conn1)
        r1 = await append(s1, org_id=ORG_ID, actor="user:rollback", action="test.abort", target="target:rollback")
        rolled_back_seq = r1.seq
        await tx1.rollback()

    # 2. Session 2 begins transaction, appends, and commits
    async with engine.connect() as conn2:
        tx2 = await conn2.begin()
        s2 = AsyncSession(bind=conn2)
        r2 = await append(s2, org_id=ORG_ID, actor="user:commit", action="test.commit", target="target:commit")
        # Because session 1 rolled back, session 2 gets the exact rolled_back_seq without sequence gaps!
        assert r2.seq == rolled_back_seq
        await tx2.commit()

    # 3. Verify entire audit chain integrity
    async with engine.connect() as conn3:
        s3 = AsyncSession(bind=conn3)
        res = await verify_chain(s3)
        assert res.ok, f"Audit chain verification failed: {res.reason}"

    await engine.dispose()


@pytest.mark.asyncio
async def test_concurrent_audit_appends_stress_test():
    """Stress test: 8 concurrent tasks appending 5 audit records each under high mutex contention."""
    url = get_mysql_test_url(driver="asyncmy")
    engine = create_engine_from_url(url, pool_size=15, max_overflow=15, pool_recycle=3600)

    num_tasks = 8
    appends_per_task = 5
    total_appends = num_tasks * appends_per_task

    async def worker(worker_id: int):
        for i in range(appends_per_task):
            async with engine.connect() as conn:
                tx = await conn.begin()
                s = AsyncSession(bind=conn)
                try:
                    await append(
                        s,
                        org_id=ORG_ID,
                        actor=f"worker:{worker_id}",
                        action="stress.test",
                        target=f"record:{worker_id}:{i}",
                        meta={"worker": worker_id, "iteration": i, "ts": i * 1.5},
                    )
                    await tx.commit()
                except Exception:
                    await tx.rollback()
                    raise

    # Run all workers concurrently
    tasks = [asyncio.create_task(worker(w)) for w in range(num_tasks)]
    await asyncio.gather(*tasks)

    # Verify that the entire SHA-256 hash chain is continuous and valid
    async with engine.connect() as conn:
        s = AsyncSession(bind=conn)
        res = await verify_chain(s)
        assert res.ok, f"Concurrent audit chain failed verification: {res.reason} (at seq {res.first_broken_seq})"
        assert res.checked >= total_appends

    await engine.dispose()


@pytest.mark.asyncio
async def test_audit_append_after_earlier_read_sees_latest_head():
    """MySQL REPEATABLE READ: a request whose transaction read anything before appending saw a stale snapshot of
    the chain head after taking the audit_lock, so a concurrently committed append produced a duplicate seq
    (IntegrityError 1062 under the 1M-row benchmark). The head must be read with a locking read."""
    url = get_mysql_test_url(driver="asyncmy")
    engine = create_engine_from_url(url, pool_size=5, max_overflow=5)
    try:
        async with engine.connect() as c1, engine.connect() as c2:
            tx1 = await c1.begin()
            s1 = AsyncSession(bind=c1)
            await s1.execute(text("SELECT COUNT(*) FROM audit_log"))  # snapshot established, as in a real request

            tx2 = await c2.begin()
            other = await append(
                AsyncSession(bind=c2), org_id=ORG_ID, actor="test:other", action="snapshot.test", target="other"
            )
            await tx2.commit()

            mine = await append(s1, org_id=ORG_ID, actor="test:mine", action="snapshot.test", target="mine")
            await tx1.commit()

        assert mine.seq == other.seq + 1
        assert mine.prev_hash == other.hash
        async with engine.connect() as conn:
            assert (await verify_chain(AsyncSession(bind=conn))).ok
    finally:
        await engine.dispose()
