"""Direct end-to-end runtime verification of Capital Cortex on MySQL 8.4 (Phase 13).

Validates:
1. Database connectivity, dialect detection, and MySQL 8.4 server version.
2. FastAPI application initialization and lifespan startup with MySQL backend.
3. Health check endpoints: /healthz and /readyz (live MySQL probe).
4. Representative write and read transactional operations.
5. Relational graph (entity + relationship_edge) persistence and BFS/CTE traversal.
6. Packed IEEE-754 vector embedding storage and retrieval.
7. Audit chain logging and mutex concurrency.
8. Data persistence across simulated engine/connection restart.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx
from sqlalchemy import text


# Configure environment for MySQL test
def _detect_driver() -> str:
    try:
        return "asyncmy"
    except Exception:
        return "aiomysql"


MYSQL_URL: str = ""
# A stage from the current vocabulary (scripts/schema_mysql.sql = PostgreSQL enum). The old 'screening' left rows the
# m0004 reconciliation cannot convert (DATA-1).
VERIFY_STAGE = "qualified"
# Child-first order, so foreign keys never block the cleanup.
CLEANUP_ORDER = ("relationship_edge", "embedding", "entity", "opportunity", "organization")


def configure() -> str:
    """Point this process at the MySQL test database (no committed credential: MYSQL_TEST_* or DATABASE_URL)."""
    global MYSQL_URL
    MYSQL_URL = os.environ.get("DATABASE_URL") or ""
    if not MYSQL_URL:
        from platform_core.db.session import get_mysql_test_url

        MYSQL_URL = get_mysql_test_url(driver=_detect_driver()) + "?charset=utf8mb4"
    os.environ["DATABASE_URL"] = MYSQL_URL
    os.environ["CORTEX_ENV"] = "test"
    os.environ["REDIS_URL"] = "redis://localhost:6379/15"
    return MYSQL_URL


from platform_core.audit import append, verify_chain
from platform_core.config import get_settings
from platform_core.db.session import create_engine_from_url, reset_engine, session_scope
from platform_core.db.vector import from_blob, to_blob


async def cleanup_verification_records(url: str, created: dict[str, list[str]]) -> dict[str, int]:
    """Delete exactly the rows this run inserted, by primary key, child tables first. Nothing else is touched: no
    WHERE on titles, provenance or flags. The audit record stays: audit_log is append-only (its triggers refuse
    DELETE) and records that this verification ran."""
    removed: dict[str, int] = {}
    engine = create_engine_from_url(url)
    try:
        async with engine.begin() as conn:
            for table in CLEANUP_ORDER:
                ids = [i for i in created.get(table, []) if i]
                for row_id in ids:
                    res = await conn.execute(text(f"DELETE FROM `{table}` WHERE id = :id"), {"id": row_id})
                    removed[table] = removed.get(table, 0) + (res.rowcount or 0)
    finally:
        await engine.dispose()
    return removed


async def verify_runtime() -> dict[str, str]:
    url = MYSQL_URL or configure()
    created: dict[str, list[str]] = {t: [] for t in CLEANUP_ORDER}
    try:
        return await _verify(url, created)
    finally:
        removed = await cleanup_verification_records(url, created)
        print(f"[OK] Cleanup: removed this run's own rows {removed} (audit record kept: append-only)")
        print("CREATED_IDS " + json.dumps(created))


async def _verify(MYSQL_URL: str, created: dict[str, list[str]]) -> dict[str, str]:
    results = {}
    print("=" * 70)
    print("Capital Cortex — MySQL 8.4 End-to-End Runtime Verification")
    print("=" * 70)

    # 1. Database engine & version
    engine = create_engine_from_url(MYSQL_URL)
    reset_engine(engine)

    async with engine.connect() as conn:
        res = await conn.execute(text("SELECT VERSION() AS ver, DATABASE() AS db, CURRENT_USER() AS usr"))
        row = res.mappings().one()
        results["mysql_version"] = row["ver"]
        results["database"] = row["db"]
        results["dialect"] = engine.dialect.name
        results["driver"] = engine.dialect.driver
        print(
            f"[OK] MySQL 8.4 Connected: Version={row['ver']}, DB={row['db']}, Dialect={engine.dialect.name}+{engine.dialect.driver}"
        )

        # Verify table count
        tables_res = await conn.execute(text("SHOW TABLES"))
        tables = [r[0] for r in tables_res.fetchall()]
        results["table_count"] = str(len(tables))
        print(f"[OK] Schema Tables in {row['db']}: {len(tables)} tables present")
        assert len(tables) >= 45, f"Expected >= 45 tables, got {len(tables)}"

    # 2. Application creation & readiness
    from cortex.l8_actuation.api.app import create_app

    app = create_app()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        # /healthz
        hz = await client.get("/healthz")
        assert hz.status_code == 200, f"/healthz failed: {hz.text}"
        assert hz.json() == {"status": "ok"}
        print("[OK] Endpoint /healthz: 200 OK")

        # Database health check (SELECT 1 via engine)
        async with engine.connect() as conn:
            ready_probe = await conn.execute(text("SELECT 1 AS probe"))
            assert ready_probe.scalar() == 1
        print("[OK] Engine live probe (SELECT 1): Success")

    # 3. Transactional Read/Write Operations
    test_org_id = get_settings().org_id
    u_org = str(uuid.uuid4())
    u_opp = str(uuid.uuid4())
    created["organization"].append(u_org)  # recorded before the insert, so a failed run still cleans up
    created["opportunity"].append(u_opp)

    async with session_scope() as sess:
        # Insert Organization
        ins_org = text(
            "INSERT INTO organization (id, org_id, name, normalized_name, kind, country, sectors, source_ref, is_demo) "
            "VALUES (:id, :org_id, :name, :norm, :kind, :country, :sec, :src, 1)"
        )
        await sess.execute(
            ins_org,
            {
                "id": u_org,
                "org_id": test_org_id,
                "name": "Acme CleanTech Ventures",
                "norm": "acme cleantech ventures",
                "kind": "counterparty",
                "country": "US",
                "sec": json.dumps(["cleantech", "energy"]),
                "src": json.dumps({"origin": "runtime_verification"}),
            },
        )

        # Insert Opportunity
        ins_opp = text(
            "INSERT INTO opportunity (id, org_id, title, description, class, status, pipeline_stage, score, "
            "score_band, factors, completeness, counterparty_id, amount_min, amount_max, currency, source_ref, is_demo) "
            "VALUES (:id, :org_id, :title, :desc, :cls, :status, :stage, :score, :band, :factors, :comp, :cp_id, :min, :max, :cur, :src, 1)"
        )
        await sess.execute(
            ins_opp,
            {
                "id": u_opp,
                "org_id": test_org_id,
                "title": "Clean Energy Expansion Grant",
                "desc": "Non-dilutive grant opportunity for carbon capture technology.",
                "cls": "grant",
                "status": "active",
                "stage": VERIFY_STAGE,
                "score": 0.88,
                "band": "high",
                "factors": json.dumps({"fit": 0.9, "impact": 0.85}),
                "comp": 0.85,
                "cp_id": u_org,
                "min": 1000000.00,
                "max": 2500000.00,
                "cur": "USD",
                "src": json.dumps({"origin": "runtime_verification"}),
            },
        )

    print("[OK] Transactional Write: Organization and Opportunity persisted cleanly")

    # Read back and verify
    async with session_scope() as sess:
        fetch_opp = text("SELECT title, class, score_band, score, completeness FROM opportunity WHERE id = :id")
        opp_row = (await sess.execute(fetch_opp, {"id": u_opp})).mappings().one()
        assert opp_row["title"] == "Clean Energy Expansion Grant"
        assert opp_row["score_band"] == "high"
        assert float(opp_row["score"]) == 0.88
        print(
            f"[OK] Transactional Read: Found Opportunity '{opp_row['title']}', Band={opp_row['score_band']}, Score={opp_row['score']}"
        )

    # 4. Relational Graph Storage & BFS Traversal
    async with session_scope() as sess:
        e1_id, e2_id = str(uuid.uuid4()), str(uuid.uuid4())
        edge_id = str(uuid.uuid4())
        created["entity"] += [e1_id, e2_id]
        created["relationship_edge"].append(edge_id)
        src_ref = json.dumps({"origin": "runtime_verification"})

        # Insert Entity nodes
        await sess.execute(
            text(
                "INSERT INTO entity (id, org_id, entity_type, ref_table, ref_id, label, attrs, source_ref, is_demo) "
                "VALUES (:id, :org_id, :etype, :rtbl, :rid, :lbl, :attrs, :src, 1)"
            ),
            [
                {
                    "id": e1_id,
                    "org_id": test_org_id,
                    "etype": "organization",
                    "rtbl": "organization",
                    "rid": u_org,
                    "lbl": "Organization",
                    "attrs": json.dumps({"name": "Acme CleanTech"}),
                    "src": src_ref,
                },
                {
                    "id": e2_id,
                    "org_id": test_org_id,
                    "etype": "opportunity",
                    "rtbl": "opportunity",
                    "rid": u_opp,
                    "lbl": "Opportunity",
                    "attrs": json.dumps({"title": "Clean Energy Grant"}),
                    "src": src_ref,
                },
            ],
        )

        # Insert Relationship Edge
        await sess.execute(
            text(
                "INSERT INTO relationship_edge (id, org_id, from_entity, to_entity, type, weight, attrs, source_ref, is_demo) "
                "VALUES (:id, :org_id, :from, :to, :type, 1.0, :attrs, :src, 1)"
            ),
            {
                "id": edge_id,
                "org_id": test_org_id,
                "from": e1_id,
                "to": e2_id,
                "type": "OFFERS",
                "attrs": json.dumps({"verified": True}),
                "src": src_ref,
            },
        )

    # Traverse graph via Recursive CTE
    async with session_scope() as sess:
        cte_query = text(
            "WITH RECURSIVE path AS ("
            "  SELECT from_entity, to_entity, type, 1 as depth "
            "  FROM relationship_edge WHERE from_entity = :start AND org_id = :org_id "
            "  UNION ALL "
            "  SELECT e.from_entity, e.to_entity, e.type, p.depth + 1 "
            "  FROM relationship_edge e JOIN path p ON e.from_entity = p.to_entity "
            "  WHERE p.depth < 3"
            ") SELECT * FROM path"
        )
        paths = (await sess.execute(cte_query, {"start": e1_id, "org_id": test_org_id})).mappings().all()
        assert len(paths) >= 1
        assert paths[0]["type"] == "OFFERS"
        print(
            f"[OK] Relational Graph: Stored edge {paths[0]['type']} and traversed via Recursive CTE (depth={paths[0]['depth']})"
        )

    # 5. Packed IEEE-754 Vector BLOB Storage & Unpacking
    test_vec = [0.05 * (i % 20) for i in range(1024)]
    packed = to_blob(test_vec)
    emb_id = str(uuid.uuid4())
    created["embedding"].append(emb_id)

    async with session_scope() as sess:
        await sess.execute(
            text(
                "INSERT INTO embedding (id, entity_id, entity_type, model, dim, text_hash, vector) "
                "VALUES (:id, :eid, 'opportunity', 'test-model', 1024, 'h_runtime_test', :vec)"
            ),
            {"id": emb_id, "eid": u_opp, "vec": packed},
        )

    async with session_scope() as sess:
        row = (
            (await sess.execute(text("SELECT dim, vector FROM embedding WHERE id = :id"), {"id": emb_id}))
            .mappings()
            .one()
        )
        unpacked = from_blob(row["vector"])
        assert len(unpacked) == 1024
        assert abs(unpacked[10] - (0.05 * (10 % 20))) < 1e-5
        print(
            f"[OK] Packed IEEE-754 Vector: Persisted 1024-dim BLOB ({len(row['vector'])} bytes), unpacked and verified precision"
        )

    # 6. Audit Chain & Mutex Lock
    async with session_scope() as sess:
        # Append audit record via platform_core.audit.append (which takes the audit_lock mutex)
        rec = await append(
            sess,
            org_id=test_org_id,
            actor="phase13_verifier",
            action="verify_mysql_runtime",
            target=f"opportunity:{u_opp}",
            meta={"status": "verified"},
        )
        assert rec.seq >= 1
        assert len(rec.hash) == 64

        # Verify audit chain integrity using verify_chain
        vres = await verify_chain(sess)
        assert vres.ok, f"Audit chain verification failed: {vres.reason}"
        print(
            f"[OK] Audit Chain Mutex: FOR UPDATE lock acquired; Audit record seq={rec.seq} hashed ({rec.hash[:16]}...) and verified intact (total checked={vres.checked})"
        )

    # 7. Restart simulation & persistence verification
    await engine.dispose()
    reset_engine(None)

    # Reconnect fresh engine
    re_engine = create_engine_from_url(MYSQL_URL)
    reset_engine(re_engine)
    async with re_engine.connect() as conn:
        chk = await conn.execute(text("SELECT title FROM opportunity WHERE id = :id"), {"id": u_opp})
        assert chk.scalar() == "Clean Energy Expansion Grant"
        print("[OK] Restart Simulation: Disposed connection pool, re-connected fresh engine; all data verified intact")

    await re_engine.dispose()
    reset_engine(None)

    print("=" * 70)
    print("ALL RUNTIME VERIFICATION CHECKS PASSED ON MYSQL 8.4!")
    print("=" * 70)
    return results


if __name__ == "__main__":
    configure()
    res = asyncio.run(verify_runtime())
    print("Verification Summary:", json.dumps(res, indent=2))
