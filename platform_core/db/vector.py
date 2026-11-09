"""Vector embedding helpers for MySQL 8.4 (binary BLOB storage) and in-memory retrieval.

Embedding dimension is fixed at 1024 (D-006). Embeddings are stored as 4096-byte IEEE-754
float32 little-endian binary arrays in MySQL BLOB columns. Retrieval is an exact brute-force cosine
search over a float32 matrix in application memory (one matrix-vector product per query) with hard
tenant isolation.
"""

from __future__ import annotations

import os

# Clamp OpenBLAS threads to 1 on Windows to prevent virtual address exhaustion
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import asyncio
import logging
import math
import struct
import time
from collections.abc import Sequence
from typing import Any

import numpy as np
from sqlalchemy import text

from platform_core.db.compat import in_clause

log = logging.getLogger(__name__)

EMBEDDING_DIM = 1024
BLOB_BYTE_SIZE = EMBEDDING_DIM * 4  # 4096 bytes
BYTE_ORDER = "<"  # Little-endian IEEE-754 float32
STRUCT_FORMAT = f"{BYTE_ORDER}{EMBEDDING_DIM}f"

# Legacy SQL string retained for backward-compatibility with PostgreSQL integration tests
COSINE_SEARCH_SQL = (
    "SELECT entity_id, entity_type, 1 - (vector <=> CAST(:q AS vector)) AS similarity "
    "FROM embedding WHERE org_id = :org AND model = :model "
    "ORDER BY vector <=> CAST(:q AS vector) LIMIT :k"
)


def validate_vector(vec: Sequence[float]) -> list[float]:
    """Validate that a vector has exactly EMBEDDING_DIM finite numeric elements."""
    if len(vec) != EMBEDDING_DIM:
        raise ValueError(f"expected {EMBEDDING_DIM}-dim vector, got {len(vec)}")
    clean = []
    for idx, x in enumerate(vec):
        val = float(x)
        if not math.isfinite(val):
            raise ValueError(f"vector contains non-finite value at index {idx}: {x}")
        clean.append(val)
    return clean


def validate_blob(raw: bytes) -> None:
    """Validate that a raw binary blob is exactly 4096 bytes."""
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise TypeError(f"expected bytes-like object, got {type(raw).__name__}")
    if len(raw) != BLOB_BYTE_SIZE:
        raise ValueError(f"expected {BLOB_BYTE_SIZE} bytes, got {len(raw)}")


def to_blob(vec: Sequence[float]) -> bytes:
    """Pack 1024 float32 numbers into 4096 bytes (IEEE-754 little-endian)."""
    clean_vec = validate_vector(vec)
    return struct.pack(STRUCT_FORMAT, *clean_vec)


def from_blob(raw: bytes) -> list[float]:
    """Unpack 4096 bytes into 1024 float32 numbers."""
    validate_blob(raw)
    vals = list(struct.unpack(STRUCT_FORMAT, raw))
    for idx, v in enumerate(vals):
        if not math.isfinite(v):
            raise ValueError(f"BLOB unpacked non-finite float at index {idx}: {v}")
    return vals


def to_pgvector(vec: Sequence[float]) -> str:
    """PostgreSQL (pgvector) text form accepted by ``CAST(:v AS vector)``. MySQL uses :func:`to_blob`.

    Kept for the PostgreSQL rollback build (RB-1); it must not return the MySQL BLOB format."""
    clean_vec = validate_vector(vec)
    return "[" + ",".join(f"{float(x):.7g}" for x in clean_vec) + "]"


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity for L2-normalized vectors is the dot product, clamped to [-1.0, 1.0]."""
    dot = float(sum(x * y for x, y in zip(a, b, strict=True)))
    return max(-1.0, min(1.0, dot))


class VectorIndex:
    """In-memory exact cosine index for tenant-isolated vector search."""

    def __init__(self, metric: str = "cosine") -> None:
        self.metric = metric
        self._norms: np.ndarray | None = None
        self._ids: list[str] = []
        self._metadata: list[dict[str, Any]] = []
        self._vectors: np.ndarray | None = None
        self._built_at: float = 0.0
        self.generation: bytes | str | None = None  # change counter seen just before this index was built

    @property
    def size(self) -> int:
        return len(self._ids)

    @property
    def is_empty(self) -> bool:
        return len(self._ids) == 0

    @property
    def built_at(self) -> float:
        return self._built_at

    def fit(self, records: Sequence[dict[str, Any]]) -> VectorIndex:
        """Fit index with candidate records.

        Each record must contain:
          - "id": entity identifier (str)
          - "vector": 4096-byte binary BLOB or Sequence[float]
          - optional metadata keys ("title", "score", "score_band", "counterparty", etc.)
        """
        self._ids.clear()
        self._metadata.clear()
        self._norms = None
        self._vectors = None

        if not records:
            self._built_at = time.time()
            return self

        valid_ids: list[str] = []
        valid_meta: list[dict[str, Any]] = []
        # Decode straight into one float32 matrix: building Python float lists first costs ~32 bytes per
        # element (about 6 GB for 200k x 1024) before the conversion, versus 4 bytes here.
        vectors = np.empty((len(records), EMBEDDING_DIM), dtype=np.float32)
        count = 0

        for r in records:
            rec_id = str(r["id"])
            v_raw = r.get("vector")
            if not v_raw:
                continue
            try:
                if isinstance(v_raw, (bytes, bytearray, memoryview)):
                    validate_blob(v_raw)  # type: ignore[arg-type]
                    row = np.frombuffer(bytes(v_raw), dtype=f"{BYTE_ORDER}f4")
                elif isinstance(v_raw, (list, tuple)):
                    row = np.asarray(validate_vector(v_raw), dtype=np.float32)
                else:
                    log.warning("Skipping vector of unrecognized type %s for entity %s", type(v_raw), rec_id)
                    continue
                if not np.isfinite(row).all():
                    raise ValueError(f"vector contains non-finite value at index {int(np.argmin(np.isfinite(row)))}")
            except Exception as exc:
                log.warning("Skipping malformed vector for entity %s: %s", rec_id, exc)
                continue

            vectors[count] = row
            count += 1
            valid_ids.append(rec_id)
            valid_meta.append({k: v for k, v in r.items() if k != "vector"})

        if count == 0:
            self._built_at = time.time()
            return self

        self._ids = valid_ids
        self._metadata = valid_meta
        self._vectors = vectors[:count]

        # Row norms once at build time; each query is then a single matrix-vector product. Measured on
        # 50k x 1024: ~15 ms per query versus ~356 ms for scikit-learn NearestNeighbors(metric="cosine").
        self._norms = np.linalg.norm(self._vectors, axis=1)
        self._built_at = time.time()
        return self

    def search(
        self,
        q_vec: Sequence[float],
        top_k: int = 5,
        min_similarity: float = 0.2,
        exclude_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Search nearest neighbors for a query vector."""
        if self.is_empty or self._norms is None or self._vectors is None:
            return []

        q_arr = np.asarray(validate_vector(q_vec), dtype=np.float32)
        exclude = exclude_ids or set()

        k = min(self.size, top_k + len(exclude))
        if k <= 0:
            return []

        # Cosine similarity; a zero vector (query or row) has similarity 0, as with scikit-learn's cosine metric.
        denom = self._norms * np.float32(np.linalg.norm(q_arr))
        sims = np.divide(self._vectors @ q_arr, denom, out=np.zeros(self.size, dtype=np.float32), where=denom > 0)
        top = np.argpartition(-sims, k - 1)[:k] if k < self.size else np.arange(self.size)
        indices = top[np.argsort(-sims[top], kind="stable")]
        results: list[dict[str, Any]] = []

        for idx in indices:
            sim = float(sims[idx])
            if sim < min_similarity:
                continue

            rec_id = self._ids[idx]
            if rec_id in exclude:
                continue

            meta = dict(self._metadata[idx])
            meta["id"] = rec_id
            meta["similarity"] = round(sim, 6)
            results.append(meta)

            if len(results) >= top_k:
                break

        return results


# Global in-memory cache of tenant indexes: (org_id, is_demo) -> VectorIndex
_TENANT_INDEX_CACHE: dict[tuple[str, bool], VectorIndex] = {}

CACHE_TTL_SECONDS = 300  # upper bound on staleness if a change signal is lost or Redis is unreachable
GENERATION_TIMEOUT_SECONDS = 0.5  # a slow Redis must not hold up a search; the TTL covers that case
REVALIDATE_OVERFETCH = 20  # extra candidates fetched so that hits dropped by the live check can be replaced


def _generation_key(org_id: str) -> str:
    return f"cortex:vector:generation:{org_id}"


async def _read_generation(org_id: str) -> bytes | str | None:
    """The tenant's change counter in Redis, or None when it is unset or Redis cannot answer in time."""
    from platform_core.bus import get_bus

    try:
        return await asyncio.wait_for(get_bus().r.get(_generation_key(org_id)), GENERATION_TIMEOUT_SECONDS)
    except Exception as exc:  # any Redis or event-loop failure degrades to the TTL; search keeps working
        log.warning("vector generation unavailable, relying on the %ss TTL: %s", CACHE_TTL_SECONDS, type(exc).__name__)
        return None


async def publish_vector_change(org_id: str) -> None:
    """Tell every process (API and workers) that this tenant's vector index is stale. Call it after the commit."""
    from platform_core.bus import get_bus

    invalidate_vector_cache(org_id)
    try:
        await asyncio.wait_for(get_bus().r.incr(_generation_key(org_id)), GENERATION_TIMEOUT_SECONDS)
    except Exception as exc:
        log.warning("vector change not published, other processes refresh within the TTL: %s", type(exc).__name__)


def invalidate_vector_cache(org_id: str | None = None) -> None:
    """Invalidate cached in-memory vector indexes for a tenant or globally."""
    if org_id is None:
        _TENANT_INDEX_CACHE.clear()
    else:
        keys_to_del = [k for k in _TENANT_INDEX_CACHE if k[0] == org_id]
        for k in keys_to_del:
            _TENANT_INDEX_CACHE.pop(k, None)


async def search_opportunity_embeddings(
    s: Any,
    org_id: str,
    q_vec: Sequence[float],
    include_demo: bool = False,
    limit: int = 5,
    min_similarity: float = 0.2,
    exclude_ids: set[str] | None = None,
    force_refresh: bool = False,
) -> list[dict[str, Any]]:
    """Retrieve and rank opportunity embeddings by exact cosine similarity (VectorIndex).

    Loads eligible candidates from MySQL, builds/uses an in-memory VectorIndex, and returns
    ranked opportunity matches above min_similarity. The index is rebuilt when another process has published a
    change or the TTL has passed. Hits are then re-read from the database, so an archived opportunity is never
    returned and titles and scores are current even while the index is older than the data.
    """
    cache_key = (org_id, include_demo)
    index = _TENANT_INDEX_CACHE.get(cache_key)
    generation = await _read_generation(org_id)  # read before the rows: a later change makes this index stale

    if (
        index is None
        or force_refresh
        or time.time() - index.built_at > CACHE_TTL_SECONDS
        or (generation is not None and generation != index.generation)
    ):
        # Parameterized query with strict tenant and demo boundary enforcement
        query = (
            "SELECT o.id, o.title, o.score, o.score_band, cp.name AS counterparty, e.vector "
            "FROM embedding e "
            "JOIN opportunity o ON o.id = e.entity_id "
            "LEFT JOIN organization cp ON cp.id = o.counterparty_id "
            "WHERE e.org_id = :org AND e.entity_type = 'opportunity' "
            "AND (:demo OR NOT o.is_demo) AND o.status IN ('active', 'watchlist') "
            # e.entity_id = o.id, so the order is identical; ix_embedding_lookup delivers it without a
            # filesort (ORDER BY o.id forced a temporary table of every 4 KB vector: ~5x slower at 200k).
            "ORDER BY e.entity_id ASC"
        )
        rows = (
            (
                await s.execute(
                    text(query),
                    {"org": org_id, "demo": include_demo},
                )
            )
            .mappings()
            .all()
        )

        candidates = [dict(r) for r in rows]
        index = VectorIndex(metric="cosine")
        index.fit(candidates)
        index.generation = generation
        _TENANT_INDEX_CACHE[cache_key] = index

    hits = index.search(
        q_vec=q_vec,
        top_k=limit + REVALIDATE_OVERFETCH,
        min_similarity=min_similarity,
        exclude_ids=exclude_ids,
    )
    if not hits:
        return []
    params: dict[str, Any] = {"org": org_id, "demo": include_demo}
    id_in = in_clause("o.id", "hit", [h["id"] for h in hits], params)
    rows = await s.execute(
        text(
            "SELECT o.id, o.title, o.score, o.score_band, cp.name AS counterparty FROM opportunity o "  # noqa: S608
            "LEFT JOIN organization cp ON cp.id = o.counterparty_id "
            f"WHERE o.org_id = :org AND o.status IN ('active', 'watchlist') AND (:demo OR NOT o.is_demo) AND {id_in}"
        ),
        params,
    )
    live = {str(r["id"]): dict(r) for r in rows.mappings().all()}
    return [{**h, **live[h["id"]], "id": h["id"]} for h in hits if h["id"] in live][:limit]
