"""Evidence refs → records, scoped to the caller (citation_checker's resolver).

Ref grammar: ``<kind>:<id>[#field]``.
* table kinds (``opportunity:<uuid>``, ``contact:<uuid>`` …) read the row, org-scoped;
* ``tool:<agent_run_id>:<key>`` reads a deterministic tool result recorded in that run's evidence pack;
* ``config:<relative path>`` reads a declared assumption (e.g. ``config:scoring/reference.yaml``).

Each kind needs a permission. A ref the caller can't read is "outside the caller's authorisation scope" and
fails the citation check even though the record exists (§6 L7).
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l7_governance.citation_checker import REF_RE, Resolved
from platform_core.auth.principal import Principal
from platform_core.auth.rbac import get_rbac
from platform_core.config import get_settings

# kind → (table, permission). Only these tables are resolvable (whitelist; the table name is never user input).
TABLE_KINDS: dict[str, tuple[str, str]] = {
    "opportunity": ("opportunity", "opportunity:read"),
    "organization": ("organization", "opportunity:read"),
    "investor": ("investor", "opportunity:read"),
    "fund": ("fund", "opportunity:read"),
    "grant_program": ("grant_program", "opportunity:read"),
    "financial_instrument": ("financial_instrument", "opportunity:read"),
    "signal": ("signal", "opportunity:read"),
    "outcome": ("outcome", "opportunity:read"),
    "contact": ("contact", "relationship:read"),
    "meeting": ("meeting", "relationship:read"),
    "relationship": ("relationship", "relationship:read"),
    "interaction": ("interaction", "relationship:read"),
    "milestone": ("milestone", "relationship:read"),
    "memory": ("memory", "relationship:read"),
    "financial_snapshot": ("financial_snapshot", "forecast:read"),
    "forecast": ("forecast", "forecast:read"),
    "recommendation": ("recommendation", "agent:read"),
    "scoring_profile": ("scoring_profile", "scoring:read"),
    "document": ("document", "dataroom:read"),
    "ml_model": ("ml_model", "scoring:read"),
    "alert": ("alert", "alert:read"),
    "proposal": ("proposal", "proposal:read"),
    "board_report": ("board_report", "board_report:read"),
    "dataroom_package": ("dataroom_package", "dataroom:read"),
}
# columns never exposed as evidence (binary, generated, secrets)
DROP_COLUMNS = ("artifact", "search", "raw", "approval_token")
CONFIG_ALLOWED = re.compile(
    r"^(scoring/[\w\-]+\.yaml|forecast\.yaml|relationships\.yaml|taxonomy\.yaml|alerts\.yaml|tools\.yaml|dd_checklist\.yaml|ml\.yaml)$"
)
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


@lru_cache(maxsize=32)
def _config_doc(path: str) -> dict[str, Any]:
    p = (get_settings().config_dir / Path(path)).resolve()
    if get_settings().config_dir.resolve() not in p.parents:
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def _field(record: dict[str, Any], path: str | None) -> Any:
    if not path:
        return record
    cur: Any = record
    for part in re.split(r"[./]", path):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


class DBRefResolver:
    """Resolves refs inside the caller's transaction. ``tool_pack`` holds this run's tool results."""

    def __init__(self, session: AsyncSession, principal: Principal, tool_pack: dict[str, dict[str, Any]] | None = None):
        self.s = session
        self.p = principal
        self.tool_pack = tool_pack or {}
        self._cache: dict[str, Resolved | None] = {}

    async def resolve(self, ref: str) -> Resolved | None:
        if ref in self._cache:
            return self._cache[ref]
        m = REF_RE.match(ref)
        out: Resolved | None = None
        if m:
            kind, rid, fld = m["kind"], m["id"], m["field"]
            if kind == "tool":
                out = await self._tool(ref, rid, fld)
            elif kind == "config":
                if CONFIG_ALLOWED.match(rid):
                    doc = _config_doc(rid)
                    val = _field(doc, fld)
                    if val is not None:
                        out = Resolved(ref, val if isinstance(val, dict) else {"value": val, "field": fld}, "config")
            elif kind in TABLE_KINDS and _UUID.match(rid):
                table, _ = TABLE_KINDS[kind]
                row = (
                    await self.s.execute(
                        text(
                            f"SELECT to_jsonb(t) - CAST(:drop AS text[]) FROM {table} t "
                            "WHERE t.id = CAST(:id AS uuid) AND t.org_id = :org"
                        ),
                        {"id": rid, "org": get_settings().org_id, "drop": list(DROP_COLUMNS)},
                    )
                ).scalar()
                if row is not None:
                    if fld:
                        val = _field(row, fld)
                        if val is None and fld not in row:
                            out = None
                        else:
                            ctx = {k: row.get(k) for k in ("id", "name", "title") if row.get(k) is not None}
                            out = Resolved(ref, {"field": fld, "value": val, **ctx}, kind)
                    else:
                        out = Resolved(ref, row, kind)
        self._cache[ref] = out
        return out

    async def _tool(self, ref: str, rid: str, fld: str | None) -> Resolved | None:
        # rid is "<agent_run_id>:<key>"
        run_id, _, key = rid.partition(":")
        rec = self.tool_pack.get(f"{run_id}:{key}")
        if rec is None and _UUID.match(run_id):
            rec = (
                await self.s.execute(
                    text(
                        "SELECT output -> 'evidence_pack' -> :k FROM agent_run WHERE id = CAST(:id AS uuid) AND org_id = :org"
                    ),
                    {"k": key, "id": run_id, "org": get_settings().org_id},
                )
            ).scalar()
        if rec is None:
            return None
        val = _field(rec, fld) if fld else rec
        if val is None:
            return None
        return Resolved(ref, val if isinstance(val, dict) else {"value": val, "field": fld}, "tool")

    def in_scope(self, resolved: Resolved) -> bool:
        rbac = get_rbac()
        if resolved.kind == "config":
            return True
        if resolved.kind == "tool":
            return rbac.allows(self.p, "agent:read")
        perm = TABLE_KINDS[resolved.kind][1]
        if not rbac.allows(self.p, perm):
            return False
        cls = resolved.record.get("classification")
        if isinstance(cls, str):
            return rbac.classification_rank(cls) <= rbac.classification_rank(rbac.clearance(self.p.roles))
        return True
