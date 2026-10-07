"""Entity resolution for organisations (FR-02).

Blocking: trigram similarity on the normalised name, an exact domain match, and a compatible country.
Scoring: Jaro-Winkler on normalised names, 1.0 on an exact domain match, and a penalty for conflicting
countries. ≥ 0.92 reuses the existing organisation (auto-merge); 0.80–0.92 creates a new one and queues the
pair for human review; below that it is a new organisation. Merges are reversible and audited (see
``merge``/``unmerge``).
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from rapidfuzz.distance import JaroWinkler
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.config import get_settings

AUTO_MERGE = 0.92
REVIEW = 0.80
_LEGAL = re.compile(
    r"\b(inc|incorporated|llc|ltd|limited|plc|gmbh|ag|sa|sas|bv|nv|pte|pty|co|corp|corporation|company|"
    r"llp|lp|srl|oy|ab|as|kk|the)\b"
)
_NONALNUM = re.compile(r"[\W_]+")  # Unicode-aware: keeps letters of every script
# words that don't distinguish one organisation from another when comparing token sets
_STOP = frozenset({"of", "and", "for", "the", "de", "la", "le", "du", "des", "und", "fur", "di", "del", "y", "et"})
TOKEN_MATCH = 0.9  # two words count as the same word (typo) at this Jaro-Winkler similarity


def normalize_name(name: str) -> str:
    # strip accents only (NFKD + drop combining marks); an ASCII-only fold erased non-Latin names to ""
    n = "".join(c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c)).casefold()
    n = n.replace("&", " and ")
    n = " ".join(_NONALNUM.sub(" ", n).split())
    stripped = " ".join(_LEGAL.sub(" ", n).split())
    return stripped or n  # "The Company Ltd" keeps its words rather than collapsing to ""


def _tokens_agree(a_norm: str, b_norm: str) -> bool:
    """Every distinguishing word on each side has a near-identical word on the other (typos allowed, extra or
    different words not): "department of energy" vs "department of defense" disagree."""
    a = {t for t in a_norm.split() if t not in _STOP}
    b = {t for t in b_norm.split() if t not in _STOP}
    return all(any(JaroWinkler.similarity(x, y) >= TOKEN_MATCH for y in b) for x in a - b) and all(
        any(JaroWinkler.similarity(y, x) >= TOKEN_MATCH for x in a) for y in b - a
    )


def similarity(
    a_norm: str,
    b_norm: str,
    a_country: str | None = None,
    b_country: str | None = None,
    a_domain: str | None = None,
    b_domain: str | None = None,
) -> tuple[float, dict[str, Any]]:
    if a_domain and b_domain and a_domain.lower() == b_domain.lower():
        return 1.0, {"method": "domain", "domain": a_domain.lower()}
    if not a_norm or not b_norm:
        return 0.0, {"method": "jaro_winkler", "a": a_norm, "b": b_norm, "empty_name": True}
    s = JaroWinkler.similarity(a_norm, b_norm)
    ev: dict[str, Any] = {"method": "jaro_winkler", "a": a_norm, "b": b_norm, "jw": round(s, 4)}
    if s >= AUTO_MERGE and not _tokens_agree(a_norm, b_norm):
        # a long shared prefix inflates Jaro-Winkler: never auto-merge different words, let a person decide
        s = min(s, AUTO_MERGE - 0.0001)
        ev["token_mismatch"] = True
    if a_country and b_country and a_country != b_country:
        s *= 0.85
        ev["country_conflict"] = [a_country, b_country]
    return s, ev


@dataclass
class Resolution:
    organization_id: str
    decision: str  # matched | created | created_review
    score: float
    evidence: dict[str, Any]


async def resolve_organization(
    s: AsyncSession,
    *,
    name: str,
    kind: str,
    country: str | None,
    domain: str | None,
    source_ref: dict[str, Any],
    is_demo: bool = False,
) -> Resolution:
    org = get_settings().org_id
    norm = normalize_name(name)
    rows = (
        (
            await s.execute(
                text(
                    "SELECT id, name, normalized_name, country, domain FROM organization "
                    "WHERE org_id = :org AND merged_into IS NULL AND kind <> 'self' "
                    "AND (normalized_name % :norm OR normalized_name = :norm OR (CAST(:domain AS text) IS NOT NULL AND domain = :domain)) "
                    "ORDER BY similarity(normalized_name, :norm) DESC LIMIT 20"
                ),
                {"org": org, "norm": norm, "domain": domain},
            )
        )
        .mappings()
        .all()
    )
    best: tuple[float, dict[str, Any], Any] | None = None
    for r in rows:
        score, ev = similarity(norm, r["normalized_name"] or "", country, r["country"], domain, r["domain"])
        if best is None or score > best[0]:
            best = (score, ev, r)
    if best and best[0] >= AUTO_MERGE:
        return Resolution(str(best[2]["id"]), "matched", best[0], best[1])

    new_id = (
        await s.execute(
            text(
                "INSERT INTO organization (org_id, name, normalized_name, kind, country, domain, source_ref, is_demo) "
                "VALUES (:org, :name, :norm, :kind, :country, :domain, CAST(:src AS jsonb), :demo) RETURNING id"
            ),
            {
                "org": org,
                "name": name.strip()[:300],
                "norm": norm,
                "kind": kind,
                "country": country,
                "domain": domain,
                "src": json.dumps(source_ref),
                "demo": is_demo,
            },
        )
    ).scalar_one()
    if best and best[0] >= REVIEW:
        await s.execute(
            text(
                "INSERT INTO entity_merge_candidate (org_id, left_id, right_id, score, method, evidence, is_demo) "
                "VALUES (:org, :l, :r, :score, :m, CAST(:ev AS jsonb), :demo) ON CONFLICT DO NOTHING"
            ),
            {
                "org": org,
                "l": str(best[2]["id"]),
                "r": str(new_id),
                "score": round(best[0], 4),
                "m": best[1]["method"],
                "ev": json.dumps(best[1]),
                "demo": is_demo,
            },
        )
        return Resolution(str(new_id), "created_review", best[0], best[1])
    return Resolution(str(new_id), "created", best[0] if best else 0.0, best[1] if best else {})


async def merge(s: AsyncSession, candidate_id: str, decided_by: str) -> dict[str, Any]:
    """Merge right into left: repoint references, mark right as merged. The undo record allows unmerge."""
    c = (
        (await s.execute(text("SELECT * FROM entity_merge_candidate WHERE id = :id FOR UPDATE"), {"id": candidate_id}))
        .mappings()
        .one()
    )
    if c["status"] != "pending":
        raise ValueError(f"candidate is {c['status']}")
    keep, drop = str(c["left_id"]), str(c["right_id"])
    moved = {
        "opportunity": [
            str(r)
            for r in (
                await s.execute(
                    text("UPDATE opportunity SET counterparty_id = :keep WHERE counterparty_id = :drop RETURNING id"),
                    {"keep": keep, "drop": drop},
                )
            ).scalars()
        ],
        "investor": [
            str(r)
            for r in (
                await s.execute(
                    text("UPDATE investor SET organization_id = :keep WHERE organization_id = :drop RETURNING id"),
                    {"keep": keep, "drop": drop},
                )
            ).scalars()
        ],
        "contact": [
            str(r)
            for r in (
                await s.execute(
                    text("UPDATE contact SET organization_id = :keep WHERE organization_id = :drop RETURNING id"),
                    {"keep": keep, "drop": drop},
                )
            ).scalars()
        ],
    }
    await s.execute(text("UPDATE organization SET merged_into = :keep WHERE id = :drop"), {"keep": keep, "drop": drop})
    undo = {"keep": keep, "drop": drop, "moved": moved}
    await s.execute(
        text(
            "UPDATE entity_merge_candidate SET status = 'merged', decided_by = :by, decided_at = now(), "
            "undo = CAST(:undo AS jsonb) WHERE id = :id"
        ),
        {"by": decided_by, "undo": json.dumps(undo), "id": candidate_id},
    )
    return undo


async def unmerge(s: AsyncSession, candidate_id: str, decided_by: str) -> dict[str, Any]:
    c = (
        (await s.execute(text("SELECT * FROM entity_merge_candidate WHERE id = :id FOR UPDATE"), {"id": candidate_id}))
        .mappings()
        .one()
    )
    if c["status"] != "merged" or not c["undo"]:
        raise ValueError(f"candidate is {c['status']}")
    undo = c["undo"]
    drop = undo["drop"]
    for table, col in (
        ("opportunity", "counterparty_id"),
        ("investor", "organization_id"),
        ("contact", "organization_id"),
    ):
        ids = undo["moved"].get(table, [])
        if ids:
            await s.execute(
                text(f"UPDATE {table} SET {col} = :drop WHERE id = ANY(CAST(:ids AS uuid[]))"),  # noqa: S608
                {"drop": drop, "ids": ids},
            )
    await s.execute(text("UPDATE organization SET merged_into = NULL WHERE id = :drop"), {"drop": drop})
    await s.execute(
        text(
            "UPDATE entity_merge_candidate SET status = 'unmerged', decided_by = :by, decided_at = now() WHERE id = :id"
        ),
        {"by": decided_by, "id": candidate_id},
    )
    return undo
