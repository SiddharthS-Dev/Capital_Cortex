"""signals.raw consumer: signal → classify → type → resolve counterparty → graph → score → live event.

Runs in the worker under the envelope's (service) token; see cortex/worker.py for the authz check.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text

from cortex.l1_perception.models import Signal
from cortex.l2_representation.classifier import classify
from cortex.l2_representation.entity_resolver import resolve_organization
from cortex.l2_representation.graph_writer import write_opportunity
from cortex.l2_representation.outreach_writer import is_outreach, write_outreach_profile
from cortex.l2_representation.typer import type_signal
from cortex.l4_reasoning.score_service import score_opportunity
from platform_core import embeddings
from platform_core.bus import get_bus
from platform_core.db import session_scope
from platform_core.db.vector import to_pgvector

log = logging.getLogger(__name__)
EVENTS = "cortex.events"


async def publish_event(event: dict[str, Any]) -> None:
    await get_bus().r.publish(EVENTS, json.dumps({**event, "at": datetime.now(UTC).isoformat()}, default=str))


async def process_signal(signal_id: str) -> dict[str, Any]:
    async with session_scope() as s:
        row = (
            (
                await s.execute(
                    text(
                        "SELECT sg.id, sg.normalized, sg.source_ref, sg.is_demo, sg.raw, s.kind AS source_kind, "
                        "s.adapter_key, s.config FROM signal sg JOIN source s ON s.id = sg.source_id WHERE sg.id = :id"
                    ),
                    {"id": signal_id},
                )
            )
            .mappings()
            .one()
        )
        if row["source_kind"] == "dataroom":
            from cortex.l8_actuation.dataroom import ingest_object

            out = await ingest_object(s, signal_id, row["raw"] or {}, (row["config"] or {}).get("request") or {})
            return {"type": "document.ingested", **out}
        if row["source_kind"] in ("mailbox", "calendar"):
            # relationship signals feed L3 memory, not the opportunity pipeline (FR-04)
            from cortex.l3_memory.interaction_ingest import ingest

            cfg_req = ((row["config"] or {}).get("request") or {}) if isinstance(row["config"], dict) else {}
            out = await ingest(
                s, signal_id, row["raw"] or {}, row["adapter_key"], list(cfg_req.get("self_addresses") or [])
            )
            await publish_event(
                {"type": "relationship.updated", "source_id": row["adapter_key"], "count": out.get("interactions", 0)}
            )
            return {"type": "interaction.ingested", **out}
        sig = Signal(**row["normalized"])
        cls = await classify(sig)
        tags = type_signal(sig)
        counterparty_id = None
        if sig.counterparty_name:
            kind = (
                sig.counterparty_kind
                if sig.counterparty_kind in ("counterparty", "university", "agency", "association")
                else "counterparty"
            )
            res = await resolve_organization(
                s,
                name=sig.counterparty_name,
                kind=kind,
                country=sig.counterparty_country,
                domain=sig.counterparty_domain,
                source_ref={"kind": "signal", "signal_id": signal_id, "field": "counterparty_name"},
                is_demo=row["is_demo"],
            )
            counterparty_id = res.organization_id
        opp_id, created = await write_opportunity(
            s,
            signal_id=signal_id,
            signal_ref=row["source_ref"],
            sig=sig,
            cls=cls,
            tags=tags,
            counterparty_id=counterparty_id,
            counterparty_name=sig.counterparty_name,
            is_demo=row["is_demo"],
        )
        if is_outreach(sig):  # outreach research (FR-04-OUT), same transaction as the opportunity
            await write_outreach_profile(
                s,
                opportunity_id=opp_id,
                sig=sig,
                signal_id=signal_id,
                signal_ref=row["source_ref"],
                raw=row["raw"],
                is_demo=row["is_demo"],
            )
        # retrievable text only (§5.3): title + description
        body = f"{sig.title}\n{sig.description or ''}"
        await s.execute(
            text(
                "INSERT INTO embedding (org_id, entity_id, entity_type, model, dim, text_hash, vector, is_demo) "
                "VALUES ((SELECT org_id FROM signal WHERE id = :sid), :eid, 'opportunity', :model, 1024, md5(:body), "
                "CAST(:vec AS vector), :demo) ON CONFLICT (org_id, entity_id, model, chunk_index) "
                "DO UPDATE SET vector = EXCLUDED.vector, text_hash = EXCLUDED.text_hash"
            ),
            {
                "sid": signal_id,
                "eid": opp_id,
                "model": embeddings.MODEL,
                "body": body,
                "vec": to_pgvector(embeddings.embed(body)),
                "demo": row["is_demo"],
            },
        )
        scored = await score_opportunity(s, opp_id)
    event = {
        "type": "opportunity.created" if created else "opportunity.updated",
        "opportunity_id": opp_id,
        "title": sig.title,
        "class": cls.capital_class,
        "score": scored.score,
        "band": scored.band,
        "is_demo": row["is_demo"],
    }
    await publish_event(event)
    return event
