"""Remove every synthetic demo row (``is_demo = true``) and demo graph vertices (§13, ``make purge-demo``).

Real data is never touched. The audit log is immutable, so the purge itself is recorded there.
"""

from __future__ import annotations

import asyncio
import json

from sqlalchemy import text

from cortex.l7_governance import audit_service
from platform_core.config import get_settings
from platform_core.db import age, session_scope

# child → parent order so foreign keys never block
TABLES = [
    "factor_history",
    "proposal_export",
    "proposal_version",
    "share_link",
    "document_access",
    "dataroom_package",
    "board_report",
    "alert_delivery",
    "alert",
    "approval_decision",
    "approval",
    "outbox",
    "interaction",
    "memory",
    "ml_model",
    "outcome",
    "proposal",
    "recommendation",
    "agent_run",
    "milestone",
    "document",
    "meeting",
    "relationship",
    "contact",
    "embedding",
    "relationship_edge",
    "entity",
    "entity_merge_candidate",
    "opportunity",
    "grant_program",
    "fund",
    "investor",
    "financial_snapshot",
    "forecast",
    "signal",
    "source_run",
    "organization",
    "source",
    "inference",
]


async def purge() -> dict[str, int]:
    org = get_settings().org_id
    counts: dict[str, int] = {}
    async with session_scope() as s:
        await age.cypher(s, "ckg", "MATCH (n) WHERE n.is_demo = true DETACH DELETE n RETURN count(*)")
        # source_run rows of the demo source (source_run of real sources are never is_demo)
        await s.execute(
            text("UPDATE source_run SET is_demo = true WHERE source_id IN (SELECT id FROM source WHERE is_demo)")
        )
        # rows derived from demo rows by Phase 2 services inherit the flag, so they go too
        for stmt in (
            "UPDATE agent_run SET is_demo = true WHERE opportunity_id IN (SELECT id FROM opportunity WHERE is_demo)",
            "UPDATE outbox SET is_demo = true WHERE opportunity_id IN (SELECT id FROM opportunity WHERE is_demo) "
            "OR recommendation_id IN (SELECT id FROM recommendation WHERE is_demo)",
            "UPDATE approval SET is_demo = true WHERE subject_id IN (SELECT id FROM outbox WHERE is_demo) "
            "OR subject_id IN (SELECT id FROM recommendation WHERE is_demo)",
            "UPDATE approval_decision SET is_demo = true WHERE approval_id IN (SELECT id FROM approval WHERE is_demo)",
            "UPDATE alert_delivery SET is_demo = true WHERE alert_id IN (SELECT id FROM alert WHERE is_demo)",
            "UPDATE milestone SET is_demo = true WHERE opportunity_id IN (SELECT id FROM opportunity WHERE is_demo)",
            "UPDATE proposal SET is_demo = true WHERE opportunity_id IN (SELECT id FROM opportunity WHERE is_demo)",
            "UPDATE proposal_version SET is_demo = true WHERE proposal_id IN (SELECT id FROM proposal WHERE is_demo)",
            "UPDATE proposal_export SET is_demo = true WHERE proposal_id IN (SELECT id FROM proposal WHERE is_demo)",
            "UPDATE agent_run SET is_demo = true WHERE id IN (SELECT agent_run_id FROM proposal WHERE is_demo)",
            "UPDATE document SET is_demo = true WHERE opportunity_id IN (SELECT id FROM opportunity WHERE is_demo)",
            "UPDATE document_access SET is_demo = true WHERE document_id IN (SELECT id FROM document WHERE is_demo)",
            "UPDATE share_link SET is_demo = true WHERE package_id IN (SELECT id FROM dataroom_package WHERE is_demo)",
        ):
            await s.execute(text(stmt))
        await s.execute(text("DELETE FROM agent_run WHERE is_demo AND parent_run_id IS NOT NULL"))
        for t in TABLES:
            counts[t] = (
                await s.execute(text(f"DELETE FROM {t} WHERE org_id = :org AND is_demo"), {"org": org})
            ).rowcount
        await audit_service.record(s, "system:purge-demo", "demo.purge", "database:*", {"deleted": counts})
    return counts


if __name__ == "__main__":
    print(json.dumps({"purged": asyncio.run(purge())}))
