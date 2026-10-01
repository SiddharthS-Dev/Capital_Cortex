"""Graph writer (FR-02): opportunity + counterparty + signal → relational rows, mirrors, and CKG vertices/edges.

Everything happens in the caller's transaction. Every derived node gets a DERIVED_FROM edge back to the
signal it came from (I5), and every node and edge carries ``source_ref``. A human-set class, stage, owner or
status is never overwritten by re-ingestion.
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l1_perception.models import Signal
from cortex.l2_representation.classifier import Classification
from cortex.l2_representation.typer import Tags
from platform_core.config import get_settings
from platform_core.db import age

GRAPH = "ckg"


async def _entity(
    s: AsyncSession,
    etype: str,
    table: str,
    ref_id: str,
    label: str,
    src: dict[str, Any],
    attrs: dict[str, Any] | None = None,
    is_demo: bool = False,
) -> str:
    return str(
        (
            await s.execute(
                text(
                    "INSERT INTO entity (org_id, entity_type, ref_table, ref_id, label, attrs, source_ref, is_demo) "
                    "VALUES (:org, :t, :tbl, :ref, :label, CAST(:attrs AS jsonb), CAST(:src AS jsonb), :demo) "
                    "ON CONFLICT (org_id, ref_table, ref_id) DO UPDATE SET label = EXCLUDED.label, attrs = EXCLUDED.attrs "
                    "RETURNING id"
                ),
                {
                    "org": get_settings().org_id,
                    "t": etype,
                    "tbl": table,
                    "ref": ref_id,
                    "label": label[:300],
                    "attrs": json.dumps(attrs or {}, default=str),
                    "src": json.dumps(src),
                    "demo": is_demo,
                },
            )
        ).scalar_one()
    )


async def _edge(s: AsyncSession, frm: str, to: str, etype: str, src: dict[str, Any], is_demo: bool = False) -> None:
    await s.execute(
        text(
            "INSERT INTO relationship_edge (org_id, from_entity, to_entity, type, source_ref, is_demo) "
            "VALUES (:org, :f, :t, :type, CAST(:src AS jsonb), :demo) ON CONFLICT (from_entity, to_entity, type) DO NOTHING"
        ),
        {"org": get_settings().org_id, "f": frm, "t": to, "type": etype, "src": json.dumps(src), "demo": is_demo},
    )


_PROP = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,40}$")


def _set_clause(var: str, props: dict[str, Any], prefix: str) -> tuple[str, dict[str, Any]]:
    """AGE can't ``SET n += $map`` from a parameter, so each property becomes ``var.key = $prefix_key``."""
    parts, params = [], {}
    for k, v in props.items():
        if not _PROP.match(k):
            raise ValueError(f"invalid property name {k!r}")
        parts.append(f"{var}.{k} = ${prefix}_{k}")
        params[f"{prefix}_{k}"] = v
    return (" SET " + ", ".join(parts)) if parts else "", params


async def upsert_vertex(s: AsyncSession, label: str, node_id: str, props: dict[str, Any]) -> None:
    clause, params = _set_clause("n", props, "p")
    await age.cypher(s, GRAPH, f"MERGE (n:{label} {{id: $id}}){clause} RETURN n.id", {"id": node_id, **params})


async def upsert_edge(
    s: AsyncSession, a_label: str, a_id: str, rel: str, b_label: str, b_id: str, props: dict[str, Any]
) -> None:
    clause, params = _set_clause("r", props, "p")
    await age.cypher(
        s,
        GRAPH,
        f"MATCH (a:{a_label} {{id: $a}}), (b:{b_label} {{id: $b}}) MERGE (a)-[r:{rel}]->(b){clause} RETURN id(r)",
        {"a": a_id, "b": b_id, **params},
    )


async def write_opportunity(
    s: AsyncSession,
    *,
    signal_id: str,
    signal_ref: dict[str, Any],
    sig: Signal,
    cls: Classification,
    tags: Tags,
    counterparty_id: str | None,
    counterparty_name: str | None,
    is_demo: bool = False,
) -> tuple[str, bool]:
    """Returns (opportunity_id, created)."""
    org = get_settings().org_id
    src = {
        "kind": "signal",
        "signal_id": signal_id,
        "source_key": sig.source_key,
        "url": sig.url,
        "fields": sig.field_sources,
    }
    grant_program_id = None
    existing_gp = None
    prev_counterparty = None
    if sig.external_key:
        prev_counterparty = (
            await s.execute(
                text("SELECT counterparty_id FROM opportunity WHERE org_id = :org AND external_key = :key"),
                {"org": org, "key": sig.external_key},
            )
        ).scalar()
        existing_gp = (
            await s.execute(
                text("SELECT grant_program_id FROM opportunity WHERE org_id = :org AND external_key = :key"),
                {"org": org, "key": sig.external_key},
            )
        ).scalar()
    gp_params = {
        "org": org,
        "agency": counterparty_id,
        "title": sig.title[:500],
        "desc": sig.description,
        "elig": json.dumps(sig.eligibility, default=str),
        "amin": sig.amount_min,
        "amax": sig.amount_max,
        "ccy": sig.currency,
        "open": sig.open_date.date() if sig.open_date else None,
        "deadline": sig.deadline,
        "url": sig.url,
        "src": json.dumps(src),
        "demo": is_demo,
    }
    if existing_gp and cls.capital_class in ("grant", "government_program", "university_program", "foundation_esg"):
        grant_program_id = existing_gp
        await s.execute(
            text(
                "UPDATE grant_program SET agency_org_id = :agency, title = :title, description = :desc, "
                "eligibility = CAST(:elig AS jsonb), amount_min = :amin, amount_max = :amax, currency = :ccy, "
                "open_date = :open, deadline = :deadline, url = :url, source_ref = CAST(:src AS jsonb) WHERE id = :id"
            ),
            {**gp_params, "id": existing_gp},
        )
    elif cls.capital_class in ("grant", "government_program", "university_program", "foundation_esg"):
        grant_program_id = (
            await s.execute(
                text(
                    "INSERT INTO grant_program (org_id, agency_org_id, title, description, eligibility, amount_min, amount_max, "
                    "currency, open_date, deadline, url, source_ref, is_demo) VALUES (:org, :agency, :title, :desc, "
                    "CAST(:elig AS jsonb), :amin, :amax, :ccy, :open, :deadline, :url, CAST(:src AS jsonb), :demo) RETURNING id"
                ),
                gp_params,
            )
        ).scalar_one()

    params = {
        "org": org,
        "cls": cls.capital_class,
        "csrc": cls.method if cls.capital_class else None,
        "conf": cls.confidence if cls.capital_class else None,
        "cev": json.dumps(cls.as_json()),
        "title": sig.title[:500],
        "desc": sig.description,
        "cp": counterparty_id,
        "gp": grant_program_id,
        "geo": sig.countries,
        "stages": tags.stages,
        "amin": sig.amount_min,
        "amax": sig.amount_max,
        "ccy": sig.currency,
        "deadline": sig.deadline,
        "src": json.dumps(src),
        "sig": signal_id,
        "key": sig.external_key,
        "url": sig.url,
        "sectors": tags.sectors,
        "esg": sorted({*tags.esg, *tags.sdg}),
        "demo": is_demo,
    }
    row = (
        await s.execute(
            text(
                "INSERT INTO opportunity (org_id, class, class_source, classification_confidence, class_evidence, title, "
                "description, counterparty_id, grant_program_id, geography, stage_fit, amount_min, amount_max, currency, "
                "deadline, source_ref, signal_id, external_key, url, sectors, esg_tags, is_demo) VALUES (:org, "
                "CAST(:cls AS capital_class), :csrc, :conf, CAST(:cev AS jsonb), :title, :desc, :cp, :gp, :geo, :stages, :amin, "
                ":amax, :ccy, :deadline, CAST(:src AS jsonb), :sig, :key, :url, :sectors, :esg, :demo) "
                "ON CONFLICT (org_id, external_key) WHERE external_key IS NOT NULL DO UPDATE SET "
                # a human-set class wins over re-classification
                "class = CASE WHEN opportunity.class_source = 'human' THEN opportunity.class ELSE EXCLUDED.class END, "
                "class_source = CASE WHEN opportunity.class_source = 'human' THEN 'human' ELSE EXCLUDED.class_source END, "
                "classification_confidence = CASE WHEN opportunity.class_source = 'human' THEN opportunity.classification_confidence "
                "ELSE EXCLUDED.classification_confidence END, class_evidence = EXCLUDED.class_evidence, "
                "title = EXCLUDED.title, description = EXCLUDED.description, counterparty_id = EXCLUDED.counterparty_id, "
                "grant_program_id = EXCLUDED.grant_program_id, geography = EXCLUDED.geography, stage_fit = EXCLUDED.stage_fit, "
                "amount_min = EXCLUDED.amount_min, amount_max = EXCLUDED.amount_max, currency = EXCLUDED.currency, "
                "deadline = EXCLUDED.deadline, source_ref = EXCLUDED.source_ref, signal_id = EXCLUDED.signal_id, "
                "url = EXCLUDED.url, sectors = EXCLUDED.sectors, esg_tags = EXCLUDED.esg_tags "
                "RETURNING id, (xmax = 0) AS created"
            ),
            params,
        )
    ).one()
    opp_id, created = str(row.id), bool(row.created)
    if prev_counterparty and prev_counterparty != counterparty_id:
        # the listing now names a different counterparty: drop the stale OFFERS edge (graph + mirror)
        await age.cypher(
            s,
            GRAPH,
            "MATCH (a:Organization {id: $old})-[r:OFFERS]->(o:Opportunity {id: $opp}) DELETE r RETURN 1",
            {"old": str(prev_counterparty), "opp": opp_id},
        )
        await s.execute(
            text(
                "DELETE FROM relationship_edge WHERE type = 'OFFERS' AND to_entity IN (SELECT id FROM entity WHERE "
                "ref_table = 'opportunity' AND ref_id = :opp) AND from_entity IN (SELECT id FROM entity WHERE "
                "ref_table = 'organization' AND ref_id = :old)"
            ),
            {"opp": opp_id, "old": str(prev_counterparty)},
        )

    # ---- relational mirrors (fast access, LLD §3.1) ----
    sig_e = await _entity(s, "Signal", "signal", signal_id, sig.title, signal_ref, {"source": sig.source_key}, is_demo)
    opp_e = await _entity(
        s,
        "Opportunity",
        "opportunity",
        opp_id,
        sig.title,
        src,
        {"class": cls.capital_class, "deadline": sig.deadline},
        is_demo,
    )
    await _edge(s, opp_e, sig_e, "DERIVED_FROM", src, is_demo)
    org_e = None
    if counterparty_id:
        org_e = await _entity(
            s, "Organization", "organization", counterparty_id, counterparty_name or "", src, {}, is_demo
        )
        await _edge(s, org_e, opp_e, "OFFERS", src, is_demo)
        await _edge(s, org_e, sig_e, "DERIVED_FROM", src, is_demo)

    # ---- Capital Knowledge Graph (AGE) ----
    ref = json.dumps(src, default=str)
    await upsert_vertex(
        s,
        "Signal",
        signal_id,
        {
            "title": sig.title[:300],
            "source": sig.source_key,
            "is_demo": is_demo,
            "source_ref": json.dumps(signal_ref, default=str),
        },
    )
    await upsert_vertex(
        s,
        "Opportunity",
        opp_id,
        {
            "title": sig.title[:300],
            "class": cls.capital_class or "",
            "deadline": sig.deadline.isoformat() if sig.deadline else "",
            "is_demo": is_demo,
            "source_ref": ref,
        },
    )
    await upsert_edge(s, "Opportunity", opp_id, "DERIVED_FROM", "Signal", signal_id, {"source_ref": ref})
    if counterparty_id:
        await upsert_vertex(
            s,
            "Organization",
            counterparty_id,
            {"name": (counterparty_name or "")[:300], "is_demo": is_demo, "source_ref": ref},
        )
        await upsert_edge(s, "Organization", counterparty_id, "OFFERS", "Opportunity", opp_id, {"source_ref": ref})
        await upsert_edge(s, "Organization", counterparty_id, "DERIVED_FROM", "Signal", signal_id, {"source_ref": ref})
    return opp_id, created


async def node(
    s: AsyncSession,
    label: str,
    table: str,
    node_id: str,
    name: str,
    src: dict[str, Any],
    props: dict[str, Any] | None = None,
    is_demo: bool = False,
) -> str:
    """Upsert a vertex this caller owns (e.g. a Contact) and its relational mirror. Returns the entity id."""
    ent = await _entity(s, label, table, node_id, name, src, props or {}, is_demo)
    await upsert_vertex(
        s,
        label,
        node_id,
        {"name": name[:300], "is_demo": is_demo, "source_ref": json.dumps(src, default=str), **(props or {})},
    )
    return ent


async def ensure_node(
    s: AsyncSession, label: str, table: str, node_id: str, name: str, src: dict[str, Any], is_demo: bool = False
) -> str:
    """Make sure a vertex exists without overwriting one another writer owns (its props and provenance)."""
    ent = (
        await s.execute(
            text("SELECT id FROM entity WHERE org_id = :org AND ref_table = :t AND ref_id = CAST(:id AS uuid)"),
            {"org": get_settings().org_id, "t": table, "id": node_id},
        )
    ).scalar()
    exists = await age.cypher(s, GRAPH, f"MATCH (n:{label} {{id: $id}}) RETURN n.id", {"id": node_id})
    if ent is None or not exists:
        return await node(s, label, table, node_id, name, src, None, is_demo)
    return str(ent)


async def link(
    s: AsyncSession,
    a: tuple[str, str, str, str],
    rel: str,
    b: tuple[str, str, str, str],
    src: dict[str, Any],
    props: dict[str, Any] | None = None,
    is_demo: bool = False,
) -> None:
    """Upsert an edge between nodes given as (label, table, id, name), creating missing endpoints without
    touching existing ones. The AGE edge and its relational mirror change in the same transaction (§5.2)."""
    ea = await ensure_node(s, a[0], a[1], a[2], a[3], src, is_demo)
    eb = await ensure_node(s, b[0], b[1], b[2], b[3], src, is_demo)
    await _edge(s, ea, eb, rel, src, is_demo)
    await upsert_edge(s, a[0], a[2], rel, b[0], b[2], {"source_ref": json.dumps(src, default=str), **(props or {})})
