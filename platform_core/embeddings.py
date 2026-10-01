"""Text embeddings. The default is a local, deterministic feature-hashing model: no LLM, no network (§11).

``hash-tf-1024-v1``: lower-cased word unigrams and bigrams, signed feature hashing into 1024 dimensions,
log(1+tf) weights, L2-normalised. It is a legitimate lexical-similarity embedding, and it is labelled as
such wherever it is used. A semantic model (e.g. Voyage, Azure OpenAI) can replace it via EMBEDDING_MODEL
without changing the schema, as long as it produces 1024 dims (D-006).
"""

from __future__ import annotations

import hashlib
import itertools
import math
import re
from collections import Counter

from platform_core.db.vector import EMBEDDING_DIM

MODEL = "hash-tf-1024-v1"
_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    "a an and are as at be by for from has have in is it its of on or that the this to was were will with "
    "we our you your their they this these those not may can all any each other such than into more".split()
)


def tokens(text: str) -> list[str]:
    words = [w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 1]
    return words + [f"{a}_{b}" for a, b in itertools.pairwise(words)]


def embed(text: str) -> list[float]:
    vec = [0.0] * EMBEDDING_DIM
    for tok, tf in Counter(tokens(text)).items():
        h = hashlib.blake2b(tok.encode(), digest_size=8).digest()
        idx = int.from_bytes(h[:4], "little") % EMBEDDING_DIM
        sign = 1.0 if h[4] & 1 else -1.0
        vec[idx] += sign * (1.0 + math.log(tf))
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


def shared_terms(a: str, b: str, limit: int = 8) -> list[str]:
    ta, tb = Counter(tokens(a)), Counter(tokens(b))
    common = [t for t in ta if t in tb and "_" not in t]
    return sorted(common, key=lambda t: -(ta[t] + tb[t]))[:limit]
