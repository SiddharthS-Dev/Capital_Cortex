"""pgvector helpers. Embedding dimension is fixed per deployment (D-006)."""

from __future__ import annotations

from collections.abc import Sequence

EMBEDDING_DIM = 1024


def to_pgvector(vec: Sequence[float]) -> str:
    """Text form accepted by ``CAST(:v AS vector)``."""
    if len(vec) != EMBEDDING_DIM:
        raise ValueError(f"expected {EMBEDDING_DIM}-dim vector, got {len(vec)}")
    return "[" + ",".join(f"{float(x):.7g}" for x in vec) + "]"


# Cosine distance search, e.g.:
#   SELECT entity_id, 1 - (vector <=> CAST(:q AS vector)) AS similarity
#   FROM embedding WHERE model = :m ORDER BY vector <=> CAST(:q AS vector) LIMIT :k
COSINE_SEARCH_SQL = (
    "SELECT entity_id, entity_type, 1 - (vector <=> CAST(:q AS vector)) AS similarity "
    "FROM embedding WHERE org_id = :org AND model = :model "
    "ORDER BY vector <=> CAST(:q AS vector) LIMIT :k"
)
