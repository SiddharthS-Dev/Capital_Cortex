"""Unit and integration tests for MySQL 8.4 Vector Subsystem Migration (Phase 5).

Validates IEEE-754 float32 BLOB packing/unpacking, dimension validation, non-finite value rejection,
Scikit-Learn NearestNeighbors in-memory indexing, MySQL 8.4 BLOB persistence, hard tenant isolation,
demo partitioning, Copilot context retrieval fallback, and cache lifecycle.
"""

from __future__ import annotations

import math
import time
import uuid

import numpy as np
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l5_strategy import copilot
from platform_core import embeddings
from platform_core.config import get_settings
from platform_core.db.session import create_engine_from_url, get_mysql_test_url, reset_engine
from platform_core.db.vector import (
    BLOB_BYTE_SIZE,
    EMBEDDING_DIM,
    VectorIndex,
    cosine_similarity,
    from_blob,
    invalidate_vector_cache,
    search_opportunity_embeddings,
    to_blob,
)


@pytest.fixture
async def mysql_session():
    """Provides an isolated AsyncSession against the Phase 2 MySQL 8.4 test container."""
    url = get_mysql_test_url(driver="asyncmy")
    engine = create_engine_from_url(url, pool_size=2, max_overflow=2, pool_recycle=3600, pool_pre_ping=True)
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
    invalidate_vector_cache()


# ---------------------------------------------------------------------------
# 1. Binary Serialization & Numeric Precision
# ---------------------------------------------------------------------------


def test_blob_serialization_and_deserialization_roundtrip():
    """Verify IEEE-754 float32 little-endian binary packing and unpacking."""
    raw_vec = [(float(i) * 0.001) - 0.5 for i in range(EMBEDDING_DIM)]
    norm = math.sqrt(sum(x * x for x in raw_vec))
    unit_vec = [x / norm for x in raw_vec]

    blob = to_blob(unit_vec)
    assert isinstance(blob, bytes)
    assert len(blob) == BLOB_BYTE_SIZE  # Exactly 4096 bytes

    recovered = from_blob(blob)
    assert len(recovered) == EMBEDDING_DIM

    for orig, rec in zip(unit_vec, recovered, strict=True):
        assert math.isclose(orig, rec, abs_tol=1e-6)


def test_blob_dimension_and_invalid_numeric_handling():
    """Verify dimension errors, non-finite floats, truncated bytes, and malformed inputs."""
    # Under-sized vector
    with pytest.raises(ValueError, match=f"expected {EMBEDDING_DIM}-dim vector"):
        to_blob([0.1] * (EMBEDDING_DIM - 1))

    # Over-sized vector
    with pytest.raises(ValueError, match=f"expected {EMBEDDING_DIM}-dim vector"):
        to_blob([0.1] * (EMBEDDING_DIM + 1))

    # NaN value rejection
    nan_vec = [0.1] * EMBEDDING_DIM
    nan_vec[42] = float("nan")
    with pytest.raises(ValueError, match="non-finite value"):
        to_blob(nan_vec)

    # Inf value rejection
    inf_vec = [0.1] * EMBEDDING_DIM
    inf_vec[100] = float("inf")
    with pytest.raises(ValueError, match="non-finite value"):
        to_blob(inf_vec)

    # Truncated BLOB
    with pytest.raises(ValueError, match=f"expected {BLOB_BYTE_SIZE} bytes"):
        from_blob(b"\x00" * (BLOB_BYTE_SIZE - 1))

    # Wrong type
    with pytest.raises(TypeError, match="expected bytes-like object"):
        from_blob("not-bytes")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. Similarity Ranking Parity (Scikit-Learn vs Pure-Python)
# ---------------------------------------------------------------------------


def test_cosine_similarity_ranking_and_precision():
    """Verify Scikit-Learn cosine distance vs pure-python cosine matches within 1e-5."""
    texts = [
        "sustainable aviation fuel SAF grant",
        "renewable jet fuel development incentive",
        "medieval European literature and architecture",
        "quantum computing superconducting qubits",
        "battery energy storage systems for grid balancing",
    ]
    vectors = [embeddings.embed(t) for t in texts]

    # Reference query
    q = "commercial aviation low carbon fuels"
    q_vec = embeddings.embed(q)

    # Pure Python reference scores
    py_scores = [embeddings.cosine(q_vec, v) for v in vectors]

    # Scikit-Learn NearestNeighbors via VectorIndex
    records = [{"id": f"doc_{i}", "vector": v, "title": texts[i]} for i, v in enumerate(vectors)]
    index = VectorIndex(metric="cosine").fit(records)

    results = index.search(q_vec, top_k=5, min_similarity=-1.0)
    assert len(results) == len(texts)

    for item in results:
        doc_idx = int(item["id"].split("_")[1])
        ref_sim = py_scores[doc_idx]
        sk_sim = item["similarity"]
        assert abs(ref_sim - sk_sim) < 1e-5, f"Mismatch for doc {doc_idx}: py={ref_sim}, sk={sk_sim}"

    # Top match should be sustainable aviation fuel
    assert results[0]["id"] in ("doc_0", "doc_1")


def test_identical_and_orthogonal_vectors():
    """Verify that identical vectors score 1.0 and orthogonal vectors score 0.0."""
    v1 = embeddings.embed("clean energy solar panel subsidy")
    sim_self = cosine_similarity(v1, v1)
    assert math.isclose(sim_self, 1.0, abs_tol=1e-6)

    # Construct orthogonal vector
    ortho_a = [0.0] * EMBEDDING_DIM
    ortho_b = [0.0] * EMBEDDING_DIM
    ortho_a[0] = 1.0
    ortho_b[1] = 1.0
    assert math.isclose(cosine_similarity(ortho_a, ortho_b), 0.0, abs_tol=1e-6)


# ---------------------------------------------------------------------------
# 3. VectorIndex Edge Cases & In-Memory Logic
# ---------------------------------------------------------------------------


def test_vector_index_empty_and_exclusion_handling():
    """Verify empty dataset, exclusion list, and min_similarity cutoff."""
    index = VectorIndex(metric="cosine")
    # Empty index
    index.fit([])
    assert index.is_empty
    assert index.size == 0
    q = embeddings.embed("test query")
    assert index.search(q) == []

    # Fit with valid vectors
    v1 = embeddings.embed("venture debt for SaaS companies")
    v2 = embeddings.embed("grant funding for academic research")
    records = [
        {"id": "opp_1", "vector": to_blob(v1), "title": "SaaS Debt"},
        {"id": "opp_2", "vector": to_blob(v2), "title": "Academic Grant"},
    ]
    index.fit(records)
    assert index.size == 2

    # Exclude opp_1
    res = index.search(v1, top_k=5, min_similarity=-1.0, exclude_ids={"opp_1"})
    assert len(res) == 1
    assert res[0]["id"] == "opp_2"

    # High min_similarity cutoff
    strict_res = index.search(v1, top_k=5, min_similarity=0.999)
    assert len(strict_res) == 1
    assert strict_res[0]["id"] == "opp_1"


def test_vector_index_malformed_record_tolerance():
    """Verify that malformed vectors are skipped safely without crashing the index."""
    v_good = embeddings.embed("good vector")
    records = [
        {"id": "bad_bytes", "vector": b"truncated", "title": "Bad 1"},
        {"id": "bad_type", "vector": 12345, "title": "Bad 2"},
        {"id": "good_doc", "vector": to_blob(v_good), "title": "Good Doc"},
    ]
    index = VectorIndex().fit(records)
    assert index.size == 1
    assert index.search(v_good)[0]["id"] == "good_doc"


# ---------------------------------------------------------------------------
# 4. MySQL 8.4 Integration: BLOB Storage & Retrieval
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mysql_embedding_crud_and_blob_storage(mysql_session: AsyncSession):
    """Verify inserting, querying, updating, and deleting BLOB embeddings in MySQL 8.4."""
    s = mysql_session
    org = get_settings().org_id
    opp_id = str(uuid.uuid4())
    org_ref_id = str(uuid.uuid4())

    # 1. Insert counterparty organization
    await s.execute(
        text(
            "INSERT INTO organization (id, org_id, name, kind, source_ref) "
            "VALUES (:id, :org, 'Alpha Renewable Tech', 'counterparty', JSON_OBJECT('origin', 'test'))"
        ),
        {"id": org_ref_id, "org": org},
    )

    # 2. Insert opportunity
    await s.execute(
        text(
            "INSERT INTO opportunity (id, org_id, title, counterparty_id, status, is_demo, source_ref) "
            "VALUES (:id, :org, 'Offshore Wind Innovation Grant', :cp, 'active', FALSE, JSON_OBJECT('origin', 'test'))"
        ),
        {"id": opp_id, "org": org, "cp": org_ref_id},
    )

    # 3. Insert embedding as BLOB
    v1 = embeddings.embed("Offshore Wind Innovation Grant turbine blades")
    b1 = to_blob(v1)

    await s.execute(
        text(
            "INSERT INTO embedding (id, org_id, entity_id, entity_type, model, dim, text_hash, vector, is_demo) "
            "VALUES (UUID(), :org, :eid, 'opportunity', :m, 1024, md5(:t), :vec, FALSE)"
        ),
        {"org": org, "eid": opp_id, "m": embeddings.MODEL, "t": "body text", "vec": b1},
    )

    # 4. Read back and verify BLOB
    row = (
        (
            await s.execute(
                text("SELECT vector, dim, model FROM embedding WHERE org_id = :org AND entity_id = :eid"),
                {"org": org, "eid": opp_id},
            )
        )
        .mappings()
        .one()
    )

    assert row["dim"] == 1024
    assert row["model"] == embeddings.MODEL
    unpacked = from_blob(row["vector"])
    assert len(unpacked) == 1024
    assert math.isclose(unpacked[0], v1[0], abs_tol=1e-6)

    # 5. Update embedding via ON DUPLICATE KEY UPDATE
    v2 = embeddings.embed("Updated deep sea floating wind platforms")
    b2 = to_blob(v2)
    await s.execute(
        text(
            "INSERT INTO embedding (org_id, entity_id, entity_type, model, dim, text_hash, vector, is_demo) "
            "VALUES (:org, :eid, 'opportunity', :m, 1024, md5('new'), :vec, FALSE) "
            "ON DUPLICATE KEY UPDATE vector = VALUES(vector)"
        ),
        {"org": org, "eid": opp_id, "m": embeddings.MODEL, "vec": b2},
    )

    updated_raw = (
        await s.execute(
            text("SELECT vector FROM embedding WHERE org_id = :org AND entity_id = :eid"),
            {"org": org, "eid": opp_id},
        )
    ).scalar_one()
    unpacked_updated = from_blob(updated_raw)
    assert math.isclose(unpacked_updated[0], v2[0], abs_tol=1e-6)


# ---------------------------------------------------------------------------
# 5. Tenant Isolation & Demo Partitioning in MySQL
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tenant_and_demo_isolation_in_mysql(mysql_session: AsyncSession):
    """Verify that search_opportunity_embeddings strictly isolates tenants and demo flags."""
    s = mysql_session
    org_a = "00000000-0000-0000-0000-000000000001"
    # Ensure second tenant exists in tenant table
    org_b = str(uuid.uuid4())
    await s.execute(
        text("INSERT INTO tenant (id, name) VALUES (:id, 'Tenant B')"),
        {"id": org_b},
    )

    opp_a_real = str(uuid.uuid4())
    opp_a_demo = str(uuid.uuid4())
    opp_b_real = str(uuid.uuid4())

    body = "advanced geothermal heat pump financing"
    vec = to_blob(embeddings.embed(body))

    # Tenant A - Real
    await s.execute(
        text(
            "INSERT INTO opportunity (id, org_id, title, status, is_demo, source_ref) "
            "VALUES (:id, :org, 'Geothermal Real A', 'active', FALSE, JSON_OBJECT('src', 't'))"
        ),
        {"id": opp_a_real, "org": org_a},
    )
    await s.execute(
        text(
            "INSERT INTO embedding (org_id, entity_id, entity_type, model, dim, text_hash, vector, is_demo) "
            "VALUES (:org, :id, 'opportunity', :m, 1024, 'h1', :v, FALSE)"
        ),
        {"org": org_a, "id": opp_a_real, "m": embeddings.MODEL, "v": vec},
    )

    # Tenant A - Demo
    await s.execute(
        text(
            "INSERT INTO opportunity (id, org_id, title, status, is_demo, source_ref) "
            "VALUES (:id, :org, 'Geothermal Demo A', 'active', TRUE, JSON_OBJECT('src', 't'))"
        ),
        {"id": opp_a_demo, "org": org_a},
    )
    await s.execute(
        text(
            "INSERT INTO embedding (org_id, entity_id, entity_type, model, dim, text_hash, vector, is_demo) "
            "VALUES (:org, :id, 'opportunity', :m, 1024, 'h2', :v, TRUE)"
        ),
        {"org": org_a, "id": opp_a_demo, "m": embeddings.MODEL, "v": vec},
    )

    # Tenant B - Real
    await s.execute(
        text(
            "INSERT INTO opportunity (id, org_id, title, status, is_demo, source_ref) "
            "VALUES (:id, :org, 'Geothermal Real B', 'active', FALSE, JSON_OBJECT('src', 't'))"
        ),
        {"id": opp_b_real, "org": org_b},
    )
    await s.execute(
        text(
            "INSERT INTO embedding (org_id, entity_id, entity_type, model, dim, text_hash, vector, is_demo) "
            "VALUES (:org, :id, 'opportunity', :m, 1024, 'h3', :v, FALSE)"
        ),
        {"org": org_b, "id": opp_b_real, "m": embeddings.MODEL, "v": vec},
    )

    q = embeddings.embed("geothermal drilling and heat pumps")

    # Query Tenant A, non-demo: MUST return only opp_a_real
    results_a_real = await search_opportunity_embeddings(
        s=s, org_id=org_a, q_vec=q, include_demo=False, force_refresh=True
    )
    matched_ids_a = {r["id"] for r in results_a_real}
    assert opp_a_real in matched_ids_a
    assert opp_a_demo not in matched_ids_a
    assert opp_b_real not in matched_ids_a

    # Query Tenant A, include_demo: MUST return both opp_a_real and opp_a_demo, but NOT opp_b
    results_a_demo = await search_opportunity_embeddings(
        s=s, org_id=org_a, q_vec=q, include_demo=True, force_refresh=True
    )
    matched_ids_demo = {r["id"] for r in results_a_demo}
    assert opp_a_real in matched_ids_demo
    assert opp_a_demo in matched_ids_demo
    assert opp_b_real not in matched_ids_demo

    # Query Tenant B: MUST return only opp_b_real
    results_b = await search_opportunity_embeddings(s=s, org_id=org_b, q_vec=q, include_demo=False, force_refresh=True)
    matched_ids_b = {r["id"] for r in results_b}
    assert opp_b_real in matched_ids_b
    assert opp_a_real not in matched_ids_b


# ---------------------------------------------------------------------------
# 6. Copilot Retrieval Integration & Contract Verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_copilot_retrieval_fallback_and_contract(mysql_session: AsyncSession):
    """Verify that copilot._retrieve falls back to Scikit-Learn vector search and preserves schema."""
    s = mysql_session
    org = get_settings().org_id
    opp_id = str(uuid.uuid4())
    org_id = str(uuid.uuid4())

    await s.execute(
        text(
            "INSERT INTO organization (id, org_id, name, kind, source_ref) "
            "VALUES (:id, :org, 'Helios Fusion Corp', 'counterparty', JSON_OBJECT('origin', 'test'))"
        ),
        {"id": org_id, "org": org},
    )
    await s.execute(
        text(
            "INSERT INTO opportunity (id, org_id, title, counterparty_id, score, score_band, completeness, factors, status, is_demo, source_ref) "
            "VALUES (:id, :org, 'Tokamak Magnet Milestone', :cp, 0.85, 'high', 0.8, JSON_OBJECT('alignment', 0.85), 'active', FALSE, JSON_OBJECT('origin', 'test'))"
        ),
        {"id": opp_id, "org": org, "cp": org_id},
    )

    vec = to_blob(embeddings.embed("Tokamak Magnet Milestone magnetic confinement plasma"))
    await s.execute(
        text(
            "INSERT INTO embedding (org_id, entity_id, entity_type, model, dim, text_hash, vector, is_demo) "
            "VALUES (:org, :eid, 'opportunity', :m, 1024, 'h-fusion', :v, FALSE)"
        ),
        {"org": org, "eid": opp_id, "m": embeddings.MODEL, "v": vec},
    )

    # Invalidate cache so it picks up the newly inserted data
    invalidate_vector_cache()

    # Query with semantic concept that does NOT match lexical words "Tokamak Magnet Milestone"
    # but has high vector similarity
    candidates = await copilot._retrieve(s, "magnetic confinement fusion plasma milestone", include_demo=False)
    assert len(candidates) > 0

    top = candidates[0]
    # Contract validation: verify required fields
    assert "id" in top
    assert "title" in top
    assert "score" in top
    assert "score_band" in top
    assert "counterparty" in top

    assert top["id"] == opp_id
    assert top["title"] == "Tokamak Magnet Milestone"
    assert top["counterparty"] == "Helios Fusion Corp"


# ---------------------------------------------------------------------------
# 7. Quality & Latency Benchmark
# ---------------------------------------------------------------------------


def test_vector_benchmark_and_latency():
    """Benchmark index fitting and query latency on synthetic 1024-dim embeddings."""
    n_records = 200
    rng = np.random.default_rng(42)
    raw_matrix = rng.standard_normal((n_records, EMBEDDING_DIM)).astype(np.float32)
    norms = np.linalg.norm(raw_matrix, axis=1, keepdims=True)
    unit_matrix = raw_matrix / norms

    records = [
        {"id": f"opp_{i}", "vector": unit_matrix[i].tobytes(), "title": f"Opportunity {i}"} for i in range(n_records)
    ]

    # Measure fit time
    t0 = time.perf_counter()
    index = VectorIndex().fit(records)
    fit_time_ms = (time.perf_counter() - t0) * 1000

    # Measure search latency
    q = unit_matrix[0].tolist()
    t1 = time.perf_counter()
    results = index.search(q, top_k=5, min_similarity=-1.0)
    query_time_ms = (time.perf_counter() - t1) * 1000

    assert len(results) == 5
    assert results[0]["id"] == "opp_0"
    assert math.isclose(results[0]["similarity"], 1.0, abs_tol=1e-5)

    print(f"\n[BENCHMARK] {n_records} vectors: fit={fit_time_ms:.2f}ms, query={query_time_ms:.2f}ms")
    # Gate: In-memory query must be < 50ms
    assert query_time_ms < 50.0


def test_vector_index_search_matches_exact_cosine_reference():
    """search() uses one float32 matrix-vector product (was scikit-learn NearestNeighbors, ~24x slower at 50k);
    it must return exactly the float64 reference cosine ranking, with zero vectors scoring 0."""
    rng = np.random.default_rng(11)
    mat = rng.standard_normal((300, EMBEDDING_DIM)).astype(np.float32)
    mat[17] = 0.0  # zero vector: similarity 0, never above a positive threshold
    records = [{"id": f"r{i}", "vector": mat[i].tobytes()} for i in range(len(mat))]
    index = VectorIndex(metric="cosine").fit(records)
    q = rng.standard_normal(EMBEDDING_DIM).astype(np.float32)

    ref = mat.astype(np.float64) @ q.astype(np.float64)
    norms = np.linalg.norm(mat.astype(np.float64), axis=1) * np.linalg.norm(q.astype(np.float64))
    ref = np.divide(ref, norms, out=np.zeros_like(ref), where=norms > 0)
    expected = [f"r{i}" for i in np.argsort(-ref, kind="stable") if f"r{i}" != "r3"][:10]

    got = index.search(q.tolist(), top_k=10, min_similarity=-1.0, exclude_ids={"r3"})
    assert [g["id"] for g in got] == expected
    for g in got:
        assert math.isclose(g["similarity"], float(ref[int(g["id"][1:])]), abs_tol=1e-5)
    assert all(g["id"] != "r17" for g in index.search(q.tolist(), top_k=300, min_similarity=0.0001))


def test_vector_index_fit_memory_stays_near_float32_size():
    """fit() used to build Python float lists first (~9x the float32 size; ~7 GB at 200k vectors) before the
    float32 conversion; it must now decode BLOBs straight into one float32 matrix."""
    import tracemalloc

    n = 2000
    rng = np.random.default_rng(7)
    blobs = rng.standard_normal((n, EMBEDDING_DIM)).astype("<f4")
    records = [{"id": f"o{i}", "vector": blobs[i].tobytes()} for i in range(n)]
    data_bytes = n * BLOB_BYTE_SIZE

    tracemalloc.start()
    index = VectorIndex(metric="cosine").fit(records)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert index.size == n
    assert index._vectors.dtype == np.float32 and index._vectors.shape == (n, EMBEDDING_DIM)
    np.testing.assert_array_equal(index._vectors[123], blobs[123])
    assert peak < 3 * data_bytes, f"fit peak {peak / 2**20:.1f} MiB for {data_bytes / 2**20:.1f} MiB of vectors"
