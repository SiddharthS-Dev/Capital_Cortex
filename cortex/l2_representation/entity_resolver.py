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
import uuid
from dataclasses import dataclass
from typing import Any

from rapidfuzz.distance import JaroWinkler
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.config import get_settings
from platform_core.db.compat import in_clause, insert_or_skip_duplicate, is_mysql_session

AUTO_MERGE = 0.92
REVIEW = 0.80
_LEGAL = re.compile(
    r"\b(inc|incorporated|llc|ltd|limited|plc|gmbh|ag|sa|sas|bv|nv|pte|pty|co|corp|corporation|company|"
    r"llp|lp|srl|oy|ab|as|kk|the)\b"
)
_NONALNUM = re.compile(r"[^a-z0-9 ]+")


def normalize_name(name: str) -> str:
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    n = n.replace("&", " and ")
    n = _NONALNUM.sub(" ", n)
    n = _LEGAL.sub(" ", n)
    return " ".join(n.split())


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
    s = JaroWinkler.similarity(a_norm, b_norm)
    ev: dict[str, Any] = {"method": "jaro_winkler", "a": a_norm, "b": b_norm, "jw": round(s, 4)}
    if a_country and b_country and a_country != b_country:
        s *= 0.85
        ev["country_conflict"] = [a_country, b_country]
    return s, ev


ORG_NAME_MAX = 255  # MySQL organization.name / normalized_name width


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
    if is_mysql_session(s):
        # organization.name / normalized_name are VARCHAR(255) on MySQL (text on PostgreSQL). Long counterparty strings
        # (e.g. a UKRI call listing several funders) failed the whole signal with error 1406. Cap the normalised key
        # here too, so the same long name matches its existing row instead of creating a new one each run.
        norm = norm[:ORG_NAME_MAX]
        rows = (
            (
                await s.execute(
                    text(
                        "SELECT id, name, normalized_name, country, domain FROM organization "
                        "WHERE org_id = :org AND merged_into IS NULL AND kind <> 'self' "
                        "AND (normalized_name LIKE :norm_like OR normalized_name = :norm OR (:domain IS NOT NULL AND domain = :domain)) "
                        "ORDER BY (normalized_name = :norm) DESC LIMIT 50"
                    ),
                    {"org": org, "norm": norm, "norm_like": f"%{norm}%", "domain": domain},
                )
            )
            .mappings()
            .all()
        )
    else:
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

    if is_mysql_session(s):
        new_id = str(uuid.uuid4())
        await s.execute(
            text(
                "INSERT INTO organization (id, org_id, name, normalized_name, kind, country, domain, source_ref, is_demo) "
                "VALUES (:id, :org, :name, :norm, :kind, :country, :domain, CAST(:src AS JSON), :demo)"
            ),
            {
                "id": new_id,
                "org": org,
                "name": name.strip()[:ORG_NAME_MAX],
                "norm": norm,
                "kind": kind,
                "country": country,
                "domain": domain,
                "src": json.dumps(source_ref),
                "demo": is_demo,
            },
        )
    else:
        new_id = str(
            (
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
        )
    if best and best[0] >= REVIEW:
        if is_mysql_session(s):
            cand_id = str(uuid.uuid4())
            await insert_or_skip_duplicate(
                s,
                text(
                    "INSERT INTO entity_merge_candidate (id, org_id, left_id, right_id, score, method, evidence, is_demo) "
                    "VALUES (:id, :org, :l, :r, :score, :m, CAST(:ev AS JSON), :demo)"
                ),
                {
                    "id": cand_id,
                    "org": org,
                    "l": str(best[2]["id"]),
                    "r": str(new_id),
                    "score": round(best[0], 4),
                    "m": best[1]["method"],
                    "ev": json.dumps(best[1]),
                    "demo": is_demo,
                },
            )
        else:
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
    if is_mysql_session(s):
        opp_ids = [
            str(r)
            for r in (
                await s.execute(text("SELECT id FROM opportunity WHERE counterparty_id = :drop"), {"drop": drop})
            ).scalars()
        ]
        if opp_ids:
            await s.execute(
                text("UPDATE opportunity SET counterparty_id = :keep WHERE counterparty_id = :drop"),
                {"keep": keep, "drop": drop},
            )
        inv_ids = [
            str(r)
            for r in (
                await s.execute(text("SELECT id FROM investor WHERE organization_id = :drop"), {"drop": drop})
            ).scalars()
        ]
        if inv_ids:
            await s.execute(
                text("UPDATE investor SET organization_id = :keep WHERE organization_id = :drop"),
                {"keep": keep, "drop": drop},
            )
        cnt_ids = [
            str(r)
            for r in (
                await s.execute(text("SELECT id FROM contact WHERE organization_id = :drop"), {"drop": drop})
            ).scalars()
        ]
        if cnt_ids:
            await s.execute(
                text("UPDATE contact SET organization_id = :keep WHERE organization_id = :drop"),
                {"keep": keep, "drop": drop},
            )
        moved = {
            "opportunity": opp_ids,
            "investor": inv_ids,
            "contact": cnt_ids,
        }
    else:
        moved = {
            "opportunity": [
                str(r)
                for r in (
                    await s.execute(
                        text(
                            "UPDATE opportunity SET counterparty_id = :keep WHERE counterparty_id = :drop RETURNING id"
                        ),
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
    # MySQL: `undo` is quoted with backticks; PostgreSQL rejects backticks (RB-1) and `undo` is not reserved there
    json_type, undo_col = ("JSON", "`undo`") if is_mysql_session(s) else ("jsonb", "undo")
    await s.execute(
        text(
            f"UPDATE entity_merge_candidate SET status = 'merged', decided_by = :by, decided_at = now(), "
            f"{undo_col} = CAST(:undo AS {json_type}) WHERE id = :id"
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
    if isinstance(undo, str):
        undo = json.loads(undo)
    drop = undo["drop"]
    for table, col in (
        ("opportunity", "counterparty_id"),
        ("investor", "organization_id"),
        ("contact", "organization_id"),
    ):
        ids = undo["moved"].get(table, [])
        if ids:
            if is_mysql_session(s):
                p_unmerge: dict[str, Any] = {"drop": drop}
                id_filter = in_clause("id", "ids", ids, p_unmerge)
                await s.execute(
                    text(f"UPDATE {table} SET {col} = :drop WHERE {id_filter}"),
                    p_unmerge,
                )
            else:
                await s.execute(
                    text(f"UPDATE {table} SET {col} = :drop WHERE id = ANY(CAST(:ids AS uuid[]))"),
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
