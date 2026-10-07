"""Eligibility gate register (FR-04-OUT, D-083): the workbook's G1…G8 as governed records.

Gates are imported from ``07_Eligibility_Gates`` (upsert by gate code; status and owner stay human-owned), changed
through audited CRUD, and linked to opportunities only by a person: ``affected_text`` is free text ("NSF / DOE rows"),
so links are *suggested* and confirmed, never automatic. An open or blocked gate is a warning in Radar, on the
opportunity and in the approval preview; it never changes the Capital Opportunity Score and never blocks approval.
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l1_perception.adapters.tabular import read_rows
from cortex.l1_perception.normalizer import norm_key
from cortex.l7_governance import audit_service
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.errors import NotFound, Problem

GATE_SHEET = "07_Eligibility_Gates"
STATUSES = ("open", "in_review", "cleared", "blocked", "not_applicable")
WARN_STATUSES = ("open", "blocked")
# workbook header (normalised) → column; the import refreshes these, never status / owner_id
COLUMNS = {
    "gate_id": "gate_code",
    "scope": "scope",
    "decision": "decision",
    "known_issue_assumption": "known_issue",
    "proposed_owner": "proposed_owner_text",
    "resolution_action": "resolution_action",
    "affected_prospects": "affected_text",
}
TEXT_FIELDS = ("scope", "decision", "known_issue", "proposed_owner_text", "resolution_action", "affected_text")
_GATE_CODE = re.compile(r"^G\d{1,3}$")


def _org() -> str:
    return get_settings().org_id


def parse_gate_rows(data: bytes, filename: str, sheet: str = GATE_SHEET) -> tuple[list[dict[str, Any]], list[str]]:
    """Rows of the gates sheet → gate dicts (+ per-row errors). Raises SheetNotFound for a missing sheet."""
    gates, errors = [], []
    for r in read_rows(data, filename, sheet, with_meta=True):
        row_no = r.get("_row")
        g = {
            COLUMNS[k]: (str(v).strip() if v is not None else None)
            for k, v in ((norm_key(k), v) for k, v in r.items())
            if k in COLUMNS
        }
        code = (g.get("gate_code") or "").upper()
        if not _GATE_CODE.match(code):
            errors.append(f"row {row_no}: no gate id (G1, G2, …)")
            continue
        g["gate_code"], g["_row"] = code, row_no
        gates.append(g)
    return gates, errors


async def import_gates(
    s: AsyncSession, actor: Principal, data: bytes, filename: str, sheet: str = GATE_SHEET, dry_run: bool = True
) -> dict[str, Any]:
    gates, errors = parse_gate_rows(data, filename, sheet)
    existing = {
        r["gate_code"]: dict(r)
        for r in (
            (await s.execute(text("SELECT * FROM eligibility_gate WHERE org_id = :org"), {"org": _org()}))
            .mappings()
            .all()
        )
    }
    created, updated, unchanged = [], [], []
    for g in gates:
        cur = existing.get(g["gate_code"])
        if cur is None:
            created.append(g["gate_code"])
        elif any((cur.get(f) or None) != (g.get(f) or None) for f in TEXT_FIELDS):
            updated.append(g["gate_code"])
        else:
            unchanged.append(g["gate_code"])
            continue
        if dry_run:
            continue
        src = {"kind": "workbook_import", "file": filename, "sheet": sheet, "row": g["_row"], "imported_by": actor.sub}
        await s.execute(
            text(
                "INSERT INTO eligibility_gate (org_id, gate_code, scope, decision, known_issue, proposed_owner_text, "
                "resolution_action, affected_text, source_ref) VALUES (:org, :gate_code, :scope, :decision, :known_issue, "
                ":proposed_owner_text, :resolution_action, :affected_text, CAST(:src AS jsonb)) "
                "ON CONFLICT (org_id, gate_code) DO UPDATE SET "
                + ", ".join(f"{f} = EXCLUDED.{f}" for f in TEXT_FIELDS)
                + ", source_ref = EXCLUDED.source_ref"
            ),
            {"org": _org(), **{f: g.get(f) for f in ("gate_code", *TEXT_FIELDS)}, "src": json.dumps(src)},
        )
    await audit_service.record(
        s,
        actor,
        "eligibility_gate.import",
        "eligibility_gate",
        {
            "dry_run": dry_run,
            "file": filename,
            "sheet": sheet,
            "created": created,
            "updated": updated,
            "unchanged": len(unchanged),
            "errors": errors,
        },
    )
    return {
        "dry_run": dry_run,
        "sheet": sheet,
        "created": created,
        "updated": updated,
        "unchanged": unchanged,
        "errors": errors,
    }


# ----------------------------------------------------------------------------------------- reads
_LINKS = (
    "(SELECT coalesce(json_agg(json_build_object('opportunity_id', l.opportunity_id, 'title', o.title, "
    "'linked_by', l.linked_by, 'linked_at', l.linked_at) ORDER BY o.title), '[]'::json) FROM eligibility_gate_link l "
    "JOIN opportunity o ON o.id = l.opportunity_id WHERE l.gate_id = g.id) AS links"
)


async def list_gates(s: AsyncSession) -> list[dict[str, Any]]:
    rows = (
        (
            await s.execute(
                text(
                    f"SELECT g.*, {_LINKS} FROM eligibility_gate g WHERE g.org_id = :org "
                    "ORDER BY length(g.gate_code), g.gate_code"
                ),
                {"org": _org()},
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


async def get_gate(s: AsyncSession, gate_id: str) -> dict[str, Any]:
    r = (
        (
            await s.execute(
                text(
                    f"SELECT g.*, {_LINKS} FROM eligibility_gate g WHERE g.id = CAST(:id AS uuid) AND g.org_id = :org"
                ),
                {"id": gate_id, "org": _org()},
            )
        )
        .mappings()
        .first()
    )
    if r is None:
        raise NotFound("eligibility gate not found")
    return dict(r)


async def gates_for(s: AsyncSession, opportunity_id: str, warn_only: bool = False) -> list[dict[str, Any]]:
    """Gates linked to an opportunity; ``warn_only`` keeps the open and blocked ones (the warnings)."""
    rows = (
        (
            await s.execute(
                text(
                    "SELECT g.id, g.gate_code, g.scope, g.decision, g.status, g.resolution_action FROM eligibility_gate_link l "
                    "JOIN eligibility_gate g ON g.id = l.gate_id WHERE l.opportunity_id = CAST(:id AS uuid) "
                    + ("AND g.status = ANY(:st) " if warn_only else "")
                    + "ORDER BY length(g.gate_code), g.gate_code"
                ),
                {"id": opportunity_id, **({"st": list(WARN_STATUSES)} if warn_only else {})},
            )
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def warning_text(g: dict[str, Any]) -> str:
    return f"{'Blocked' if g['status'] == 'blocked' else 'Open'} eligibility gate: {g['gate_code']} {g.get('scope') or ''}".strip()


# Words that say nothing about *which* rows a gate affects ("NSF / DOE rows", "All VC/PE rows").
_STOP = {"rows", "row", "all", "cc", "register", "routes", "route", "public", "programmes", "programme", "and", "the"}


async def suggest_links(s: AsyncSession, gate_id: str) -> dict[str, Any]:
    """Opportunities whose title, category or prospect id mention a term from ``affected_text``. Suggestions only:
    a person confirms each link. "All rows" style text suggests nothing (it would link everything)."""
    g = await get_gate(s, gate_id)
    terms = [t for t in re.split(r"[^\w&*]+", g.get("affected_text") or "") if len(t) >= 2 and t.lower() not in _STOP]
    if not terms:
        return {"gate_id": gate_id, "terms": [], "suggestions": [], "note": "affected text names no specific rows"}
    pattern = r"(^|[^[:alnum:]])(" + "|".join(re.escape(t) for t in terms) + r")([^[:alnum:]]|$)"
    rows = (
        (
            await s.execute(
                text(
                    "SELECT o.id, o.title, p.prospect_id, p.category FROM outreach_profile p JOIN opportunity o "
                    "ON o.id = p.opportunity_id WHERE p.org_id = :org AND (o.title ~* :re OR p.category ~* :re) "
                    "AND NOT EXISTS (SELECT 1 FROM eligibility_gate_link l WHERE l.gate_id = CAST(:g AS uuid) "
                    "AND l.opportunity_id = o.id) ORDER BY p.prospect_id"
                ),
                {"org": _org(), "re": pattern, "g": gate_id},
            )
        )
        .mappings()
        .all()
    )
    return {"gate_id": gate_id, "terms": terms, "suggestions": [dict(r) for r in rows]}


# ----------------------------------------------------------------------------------------- writes (audited)
async def create_gate(s: AsyncSession, actor: Principal, data: dict[str, Any]) -> dict[str, Any]:
    code = str(data.get("gate_code") or "").strip().upper()
    if not _GATE_CODE.match(code):
        raise Problem(422, "Invalid gate code", "gate codes look like G1, G2, …", "validation")
    status = data.get("status") or "open"
    if status not in STATUSES:
        raise Problem(422, "Invalid status", f"status must be one of {list(STATUSES)}", "validation")
    src = {"kind": "manual_entry", "entered_by": actor.username or actor.sub}
    gid = (
        await s.execute(
            text(
                "INSERT INTO eligibility_gate (org_id, gate_code, scope, decision, known_issue, proposed_owner_text, "
                "owner_id, resolution_action, affected_text, status, source_ref) VALUES (:org, :code, :scope, :decision, "
                ":known_issue, :proposed_owner_text, :owner_id, :resolution_action, :affected_text, :status, "
                "CAST(:src AS jsonb)) ON CONFLICT (org_id, gate_code) DO NOTHING RETURNING id"
            ),
            {
                "org": _org(),
                "code": code,
                "status": status,
                "owner_id": data.get("owner_id"),
                "src": json.dumps(src),
                **{f: data.get(f) for f in TEXT_FIELDS},
            },
        )
    ).scalar()
    if gid is None:
        raise Problem(409, "Gate exists", f"{code} is already in the register", "conflict")
    await audit_service.record(s, actor, "eligibility_gate.create", f"eligibility_gate:{gid}", {"gate_code": code})
    return await get_gate(s, str(gid))


async def update_gate(s: AsyncSession, actor: Principal, gate_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    allowed = {*TEXT_FIELDS, "status", "owner_id"}
    patch = {k: v for k, v in patch.items() if k in allowed}
    if not patch:
        raise Problem(422, "Nothing to update", f"editable fields: {sorted(allowed)}", "validation")
    if "status" in patch and patch["status"] not in STATUSES:
        raise Problem(422, "Invalid status", f"status must be one of {list(STATUSES)}", "validation")
    before = await get_gate(s, gate_id)
    await s.execute(
        text(f"UPDATE eligibility_gate SET {', '.join(f'{k} = :{k}' for k in patch)} WHERE id = CAST(:id AS uuid)"),
        {**patch, "id": gate_id},
    )
    await audit_service.record(
        s,
        actor,
        "eligibility_gate.update",
        f"eligibility_gate:{gate_id}",
        {"changes": {k: {"from": before.get(k), "to": v} for k, v in patch.items()}},
    )
    return await get_gate(s, gate_id)


async def link(s: AsyncSession, actor: Principal, gate_id: str, opportunity_id: str) -> dict[str, Any]:
    await get_gate(s, gate_id)
    ok = (
        await s.execute(
            text("SELECT 1 FROM opportunity WHERE id = CAST(:id AS uuid) AND org_id = :org"),
            {"id": opportunity_id, "org": _org()},
        )
    ).scalar()
    if not ok:
        raise NotFound("opportunity not found")
    new = (
        await s.execute(
            text(
                "INSERT INTO eligibility_gate_link (org_id, gate_id, opportunity_id, linked_by) VALUES (:org, "
                "CAST(:g AS uuid), CAST(:o AS uuid), :by) ON CONFLICT (gate_id, opportunity_id) DO NOTHING RETURNING id"
            ),
            {"org": _org(), "g": gate_id, "o": opportunity_id, "by": actor.username or actor.sub},
        )
    ).scalar()
    if new:
        await audit_service.record(
            s, actor, "eligibility_gate.link", f"eligibility_gate:{gate_id}", {"opportunity_id": opportunity_id}
        )
    return {"gate_id": gate_id, "opportunity_id": opportunity_id, "linked": True, "new": bool(new)}


async def unlink(s: AsyncSession, actor: Principal, gate_id: str, opportunity_id: str) -> dict[str, Any]:
    gone = (
        await s.execute(
            text(
                "DELETE FROM eligibility_gate_link WHERE gate_id = CAST(:g AS uuid) AND opportunity_id = CAST(:o AS uuid) "
                "AND org_id = :org RETURNING id"
            ),
            {"g": gate_id, "o": opportunity_id, "org": _org()},
        )
    ).scalar()
    if gone is None:
        raise NotFound("link not found")
    await audit_service.record(
        s, actor, "eligibility_gate.unlink", f"eligibility_gate:{gate_id}", {"opportunity_id": opportunity_id}
    )
    return {"gate_id": gate_id, "opportunity_id": opportunity_id, "linked": False}
