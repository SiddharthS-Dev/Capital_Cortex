"""Retention (R13) driven by ``config/retention.yaml`` (plus Admin overrides), with legal hold.

Legal hold always wins: a held row is never moved or deleted, and the run log counts what was skipped. A hold
targets one row (``target_table`` + ``target_id``), every row of a table (no id), or everything linked to an
opportunity (``scope.opportunity_id``). The audit log is never touched (immutable by trigger). Every run is
logged in ``retention_run`` and the audit chain; ``dry_run`` reports counts without changing anything.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l7_governance import audit_service
from platform_core import objectstore
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.errors import NotFound, Problem

COLD_BUCKET = "cortex-cold"
HOLDABLE = {"document", "proposal", "signal", "meeting", "interaction", "outbox", "agent_run", "opportunity"}
_DUR = re.compile(r"^(\d+)([hdwy])$")


def duration(spec: str) -> timedelta:
    m = _DUR.match(str(spec).strip())
    if not m:
        raise ValueError(f"bad duration {spec!r}")
    n = int(m[1])
    return {"h": timedelta(hours=n), "d": timedelta(days=n), "w": timedelta(weeks=n), "y": timedelta(days=365 * n)}[
        m[2]
    ]


def policies(overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    import yaml

    base = yaml.safe_load((get_settings().config_dir / "retention.yaml").read_text(encoding="utf-8"))["policies"]
    for k, v in (overrides or {}).items():
        if k in base and k != "audit_log":  # the audit log's 7-year immutability can't be overridden
            base[k] = {**base[k], **v}
    return base


def _held_sql(table: str, alias: str = "t") -> str:
    """SQL predicate: this row is under legal hold (row, table-wide, or via its opportunity)."""
    opp_col = {"proposal": "opportunity_id", "document": "opportunity_id", "meeting": "opportunity_id",
               "interaction": "opportunity_id", "outbox": "opportunity_id", "agent_run": "opportunity_id"}.get(table)  # fmt: skip
    parts = [
        f"EXISTS (SELECT 1 FROM legal_hold h WHERE h.released_at IS NULL AND h.target_table = '{table}' "
        f"AND (h.target_id IS NULL OR h.target_id = {alias}.id))"
    ]
    if opp_col:
        parts.append(
            f"EXISTS (SELECT 1 FROM legal_hold h WHERE h.released_at IS NULL AND h.scope ->> 'opportunity_id' = {alias}.{opp_col}::text)"
        )
    if table in ("document", "proposal", "signal", "meeting"):
        parts.append(f"{alias}.legal_hold")
    return "(" + " OR ".join(parts) + ")"


async def _log(
    s: AsyncSession,
    actor: str,
    policy: str,
    table: str,
    action: str,
    dry: bool,
    n: int,
    held: int,
    detail: dict[str, Any],
) -> None:
    await s.execute(
        text(
            "INSERT INTO retention_run (org_id, policy, target_table, action, dry_run, rows_affected, rows_held, detail, run_by) "
            "VALUES (:org, :p, :t, :a, :d, :n, :h, CAST(:det AS jsonb), :by)"
        ),
        {
            "org": get_settings().org_id,
            "p": policy,
            "t": table,
            "a": action,
            "d": dry,
            "n": n,
            "h": held,
            "det": json.dumps(detail),
            "by": actor,
        },
    )


async def run(s: AsyncSession, actor: Principal | str, *, dry_run: bool = True, overrides: dict[str, Any] | None = None,
              now: datetime | None = None, batch: int = 500) -> dict[str, Any]:  # fmt: skip
    now = now or datetime.now(UTC)
    who = actor if isinstance(actor, str) else f"user:{actor.sub}"
    pol = policies(overrides)
    org = get_settings().org_id
    results: list[dict[str, Any]] = []

    async def count(sql: str, p: dict[str, Any]) -> int:
        return int((await s.execute(text(f"SELECT count(*) FROM {sql}"), p)).scalar() or 0)

    # signals: warm for N, then raw payload moves to the cold tier (row + provenance stay)
    cutoff = now - duration(pol["signal"]["warm"])
    base = "signal t WHERE t.org_id = :org AND t.ingested_at < :c AND t.raw IS NOT NULL"
    held = await count(f"{base} AND {_held_sql('signal')}", {"org": org, "c": cutoff})
    ids = (await s.execute(text(f"SELECT t.id, t.raw FROM {base} AND NOT {_held_sql('signal')} LIMIT :n"),
                           {"org": org, "c": cutoff, "n": batch})).all()  # fmt: skip
    if not dry_run:
        for r in ids:
            key = f"signals/{r.id}.json"
            await objectstore.put_bytes(COLD_BUCKET, key, json.dumps(r.raw, default=str).encode(), "application/json")
            await s.execute(
                text("UPDATE signal SET raw = NULL, raw_key = :k WHERE id = :id"),
                {"k": f"s3://{COLD_BUCKET}/{key}", "id": r.id},
            )
    results.append({"policy": "signal", "table": "signal", "action": "to_cold", "rows": len(ids), "held": held})

    # warm memory → cold (ttl_job does the move; retention reports it)
    from cortex.l3_memory.memory_manager import ttl_job

    moved = 0 if dry_run else await ttl_job(s, batch)
    due = await count(
        "memory t WHERE t.org_id = :org AND t.tier = 'warm' AND t.expires_at < :c", {"org": org, "c": now}
    )
    results.append(
        {
            "policy": "memory_warm",
            "table": "memory",
            "action": "to_cold",
            "rows": moved if not dry_run else due,
            "held": 0,
        }
    )

    # draft proposals older than N: delete (with versions/exports), unless held or ever approved
    cutoff = now - duration(pol["proposal_draft"]["retain"])
    base = ("proposal t WHERE t.org_id = :org AND t.status = 'draft' AND t.updated_at < :c AND NOT EXISTS (SELECT 1 FROM approval a "
            "WHERE a.subject_type = 'proposal' AND a.subject_id = t.id AND a.decision = 'approved')")  # fmt: skip
    held = await count(f"{base} AND {_held_sql('proposal')}", {"org": org, "c": cutoff})
    ids = (
        (
            await s.execute(
                text(f"SELECT t.id FROM {base} AND NOT {_held_sql('proposal')} LIMIT :n"),
                {"org": org, "c": cutoff, "n": batch},
            )
        )
        .scalars()
        .all()
    )
    if not dry_run and ids:
        for tbl in ("proposal_export", "proposal_version"):
            await s.execute(text(f"DELETE FROM {tbl} WHERE proposal_id = ANY(:ids)"), {"ids": list(ids)})
        await s.execute(text("DELETE FROM proposal WHERE id = ANY(:ids)"), {"ids": list(ids)})
    results.append(
        {"policy": "proposal_draft", "table": "proposal", "action": "delete", "rows": len(ids), "held": held}
    )

    # agent runs older than N: delete, unless held or referenced by a recommendation / proposal
    cutoff = now - duration(pol["agent_run"]["retain"])
    base = ("agent_run t WHERE t.org_id = :org AND t.created_at < :c AND NOT EXISTS (SELECT 1 FROM recommendation r WHERE r.agent_run_id = t.id "
            "OR r.agent_run_id = t.parent_run_id) AND NOT EXISTS (SELECT 1 FROM proposal p WHERE p.agent_run_id = t.id) "
            "AND NOT EXISTS (SELECT 1 FROM agent_run c WHERE c.parent_run_id = t.id)")  # fmt: skip
    held = await count(f"{base} AND {_held_sql('agent_run')}", {"org": org, "c": cutoff})
    ids = (
        (
            await s.execute(
                text(f"SELECT t.id FROM {base} AND NOT {_held_sql('agent_run')} LIMIT :n"),
                {"org": org, "c": cutoff, "n": batch},
            )
        )
        .scalars()
        .all()
    )
    if not dry_run and ids:
        await s.execute(text("DELETE FROM agent_run WHERE id = ANY(:ids)"), {"ids": list(ids)})
    results.append({"policy": "agent_run", "table": "agent_run", "action": "delete", "rows": len(ids), "held": held})

    # TTL-managed tiers and the immutable audit log: reported, never touched here
    results.append(
        {
            "policy": "memory_hot",
            "table": "redis",
            "action": "ttl",
            "rows": 0,
            "held": 0,
            "note": pol["memory_hot"]["retain"],
        }
    )
    results.append(
        {
            "policy": "llm_cache",
            "table": "redis",
            "action": "ttl",
            "rows": 0,
            "held": 0,
            "note": pol["llm_cache"]["retain"],
        }
    )
    results.append(
        {
            "policy": "audit_log",
            "table": "audit_log",
            "action": "none",
            "rows": 0,
            "held": 0,
            "note": "immutable, 7 years",
        }
    )
    for res in results:
        await _log(
            s,
            who,
            res["policy"],
            res["table"],
            res["action"],
            dry_run,
            res["rows"],
            res["held"],
            {k: v for k, v in res.items() if k == "note"},
        )
    await audit_service.record(s, actor, "retention.run", "retention:*", {"dry_run": dry_run, "results": results})
    return {"dry_run": dry_run, "at": now.isoformat(), "results": results}


async def place_hold(
    s: AsyncSession, actor: Principal, target_table: str, target_id: str | None, scope: dict[str, Any], reason: str
) -> dict[str, Any]:
    if target_table not in HOLDABLE:
        raise Problem(422, "Not holdable", f"legal hold applies to {sorted(HOLDABLE)}", "validation")
    if target_table == "opportunity":
        if not target_id:
            raise Problem(422, "Opportunity required", "an opportunity hold needs its id", "validation")
        scope = {**scope, "opportunity_id": target_id}
    hid = str(
        (
            await s.execute(
                text("INSERT INTO legal_hold (org_id, target_table, target_id, scope, reason, created_by) VALUES "
                     "(:org, :t, :id, CAST(:sc AS jsonb), :r, :by) RETURNING id"),
                {"org": get_settings().org_id, "t": target_table, "id": target_id if target_table != "opportunity" else None,
                 "sc": json.dumps(scope), "r": reason, "by": actor.sub},
            )
        ).scalar_one()
    )  # fmt: skip
    if target_table in ("document", "proposal", "signal", "meeting") and target_id:
        await s.execute(
            text(f"UPDATE {target_table} SET legal_hold = true WHERE id = CAST(:id AS uuid)"), {"id": target_id}
        )
    await audit_service.record(
        s,
        actor,
        "legal_hold.placed",
        f"legal_hold:{hid}",
        {"table": target_table, "id": target_id, "scope": scope, "reason": reason},
    )
    return {"id": hid}


async def release_hold(s: AsyncSession, actor: Principal, hid: str, reason: str) -> dict[str, Any]:
    h = (
        (
            await s.execute(
                text("SELECT * FROM legal_hold WHERE id = CAST(:id AS uuid) AND released_at IS NULL FOR UPDATE"),
                {"id": hid},
            )
        )
        .mappings()
        .first()
    )
    if h is None:
        raise NotFound("active legal hold not found")
    await s.execute(
        text("UPDATE legal_hold SET released_at = now(), released_by = :by WHERE id = :id"),
        {"by": actor.sub, "id": h["id"]},
    )
    if h["target_table"] in ("document", "proposal", "signal", "meeting") and h["target_id"]:
        other = (
            await s.execute(
                text("SELECT 1 FROM legal_hold WHERE target_table = :t AND target_id = :id AND released_at IS NULL"),
                {"t": h["target_table"], "id": h["target_id"]},
            )
        ).scalar()
        if not other:
            await s.execute(
                text(f"UPDATE {h['target_table']} SET legal_hold = false WHERE id = :id"), {"id": h["target_id"]}
            )
    await audit_service.record(s, actor, "legal_hold.released", f"legal_hold:{hid}", {"reason": reason})
    return {"id": hid, "released": True}
