"""Graph writer (FR-02): opportunity + counterparty + signal -> relational rows, mirrors, and graph vertices/edges.

Everything happens in the caller's transaction. Every derived node gets a DERIVED_FROM edge back to the
signal it came from (I5), and every node and edge carries ``source_ref``. A human-set class, stage, owner or
status is never overwritten by re-ingestion.
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l1_perception.models import Signal
from cortex.l2_representation.classifier import Classification
from cortex.l2_representation.typer import Tags
from platform_core.config import get_settings

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
    org = get_settings().org_id
    existing = (
        await s.execute(
            text("SELECT id FROM entity WHERE org_id = :org AND ref_table = :tbl AND ref_id = :ref"),
            {"org": org, "tbl": table, "ref": ref_id},
        )
    ).scalar_one_or_none()
    if existing:
        await s.execute(
            text(
                "UPDATE entity SET label = :label, attrs = :attrs, source_ref = :src, is_demo = :demo, updated_at = NOW(6) "
                "WHERE id = :id"
            ),
            {
                "id": str(existing),
                "label": label[:300],
                "attrs": json.dumps(attrs or {}, default=str),
                "src": json.dumps(src),
                "demo": is_demo,
            },
        )
        return str(existing)

    new_id = str(uuid.uuid4())
    await s.execute(
        text(
            "INSERT INTO entity (id, org_id, entity_type, ref_table, ref_id, label, attrs, source_ref, is_demo) "
            "VALUES (:id, :org, :t, :tbl, :ref, :label, :attrs, :src, :demo)"
        ),
        {
            "id": new_id,
            "org": org,
            "t": etype,
            "tbl": table,
            "ref": ref_id,
            "label": label[:300],
            "attrs": json.dumps(attrs or {}, default=str),
            "src": json.dumps(src),
            "demo": is_demo,
        },
    )
    return new_id


async def _edge(s: AsyncSession, frm: str, to: str, etype: str, src: dict[str, Any], is_demo: bool = False) -> None:
    edge_id = str(uuid.uuid4())
    sref_data = src if (src and len(src) > 0) else {"source": "graph_writer"}
    await s.execute(
        text(
            "INSERT INTO relationship_edge (id, org_id, from_entity, to_entity, type, source_ref, is_demo) "
            "VALUES (:id, :org, :f, :t, :type, :src, :demo) "
            "ON DUPLICATE KEY UPDATE source_ref = VALUES(source_ref), updated_at = NOW(6)"
        ),
        {
            "id": edge_id,
            "org": get_settings().org_id,
            "f": frm,
            "t": to,
            "type": etype,
            "src": json.dumps(sref_data, default=str),
            "demo": is_demo,
        },
    )


_PROP = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,40}$")


def _set_clause(var: str, props: dict[str, Any], prefix: str) -> tuple[str, dict[str, Any]]:
    parts, params = [], {}
    for k, v in props.items():
        if not _PROP.match(k):
            raise ValueError(f"invalid property name {k!r}")
        parts.append(f"{var}.{k} = ${prefix}_{k}")
        params[f"{prefix}_{k}"] = v
    return (" SET " + ", ".join(parts)) if parts else "", params


async def upsert_vertex(s: AsyncSession, label: str, node_id: str, props: dict[str, Any]) -> None:
    org = get_settings().org_id
    tbl = label.lower()
    name = props.get("name") or props.get("title") or node_id
    attrs = json.dumps(props, default=str)
    existing = (
        await s.execute(
            text("SELECT id FROM entity WHERE org_id = :org AND ref_table = :tbl AND ref_id = :ref"),
            {"org": org, "tbl": tbl, "ref": node_id},
        )
    ).scalar_one_or_none()
    if existing:
        await s.execute(
            text("UPDATE entity SET label = :name, attrs = :attrs, updated_at = NOW(6) WHERE id = :id"),
            {"id": str(existing), "name": str(name)[:300], "attrs": attrs},
        )
    else:
        new_id = str(uuid.uuid4())
        await s.execute(
            text(
                "INSERT INTO entity (id, org_id, entity_type, ref_table, ref_id, label, attrs, source_ref, is_demo) "
                "VALUES (:id, :org, :etype, :tbl, :ref, :name, :attrs, :src, :demo)"
            ),
            {
                "id": new_id,
                "org": org,
                "etype": label,
                "tbl": tbl,
                "ref": node_id,
                "name": str(name)[:300],
                "attrs": attrs,
                "src": json.dumps({"source": "graph_writer"}),
                "demo": bool(props.get("is_demo", False)),
            },
        )


async def upsert_edge(
    s: AsyncSession, a_label: str, a_id: str, rel: str, b_label: str, b_id: str, props: dict[str, Any]
) -> None:
    org = get_settings().org_id
    ea = (
        await s.execute(
            text("SELECT id FROM entity WHERE org_id = :org AND ref_id = :ref LIMIT 1"),
            {"org": org, "ref": a_id},
        )
    ).scalar_one_or_none()
    eb = (
        await s.execute(
            text("SELECT id FROM entity WHERE org_id = :org AND ref_id = :ref LIMIT 1"),
            {"org": org, "ref": b_id},
        )
    ).scalar_one_or_none()
    if not ea or not eb:
        return
    edge_id = str(uuid.uuid4())
    sref_data = {"source": "graph_writer", **(props or {})}
    sref = json.dumps(sref_data, default=str)
    await s.execute(
        text(
            "INSERT INTO relationship_edge (id, org_id, from_entity, to_entity, type, source_ref, is_demo) "
            "VALUES (:id, :org, :ea, :eb, :type, :src, :demo) "
            "ON DUPLICATE KEY UPDATE source_ref = VALUES(source_ref), updated_at = NOW(6)"
        ),
        {
            "id": edge_id,
            "org": org,
            "ea": str(ea),
            "eb": str(eb),
            "type": rel,
            "src": sref,
            "demo": bool(props.get("is_demo", False)),
        },
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
        grant_program_id = str(existing_gp)
        await s.execute(
            text(
                "UPDATE grant_program SET agency_org_id = :agency, title = :title, description = :desc, "
                "eligibility = :elig, amount_min = :amin, amount_max = :amax, currency = :ccy, "
                "open_date = :open, deadline = :deadline, url = :url, source_ref = :src WHERE id = :id"
            ),
            {**gp_params, "id": str(existing_gp)},
        )
    elif cls.capital_class in ("grant", "government_program", "university_program", "foundation_esg"):
        grant_program_id = str(uuid.uuid4())
        await s.execute(
            text(
                "INSERT INTO grant_program (id, org_id, agency_org_id, title, description, eligibility, amount_min, amount_max, "
                "currency, open_date, deadline, url, source_ref, is_demo) VALUES (:id, :org, :agency, :title, :desc, "
                ":elig, :amin, :amax, :ccy, :open, :deadline, :url, :src, :demo)"
            ),
            {**gp_params, "id": grant_program_id},
        )

    existing_opp = None
    if sig.external_key:
        existing_opp = (
            await s.execute(
                text("SELECT id FROM opportunity WHERE org_id = :org AND external_key = :key"),
                {"org": org, "key": sig.external_key},
            )
        ).scalar_one_or_none()
    created = existing_opp is None
    opp_id = str(existing_opp) if existing_opp else str(uuid.uuid4())

    params = {
        "id": opp_id,
        "org": org,
        "cls": cls.capital_class,
        "csrc": cls.method if cls.capital_class else None,
        "conf": cls.confidence if cls.capital_class else None,
        "cev": json.dumps(cls.as_json()),
        "title": sig.title[:500],
        "desc": sig.description,
        "cp": counterparty_id,
        "gp": grant_program_id,
        "geo": json.dumps(sig.countries or []),
        "stages": json.dumps(tags.stages or []),
        "amin": sig.amount_min,
        "amax": sig.amount_max,
        "ccy": sig.currency,
        "deadline": sig.deadline,
        "src": json.dumps(src),
        "sig": signal_id,
        "key": sig.external_key,
        "url": sig.url,
        "sectors": json.dumps(tags.sectors or []),
        "esg": json.dumps(sorted({*tags.esg, *tags.sdg}) or []),
        "demo": is_demo,
    }
    await s.execute(
        text(
            "INSERT INTO opportunity (id, org_id, class, class_source, classification_confidence, class_evidence, title, "
            "description, counterparty_id, grant_program_id, geography, stage_fit, amount_min, amount_max, currency, "
            "deadline, source_ref, signal_id, external_key, url, sectors, esg_tags, is_demo) VALUES (:id, :org, "
            ":cls, :csrc, :conf, :cev, :title, :desc, :cp, :gp, :geo, :stages, :amin, "
            ":amax, :ccy, :deadline, :src, :sig, :key, :url, :sectors, :esg, :demo) "
            "ON DUPLICATE KEY UPDATE "
            "class = CASE WHEN opportunity.class_source = 'human' THEN opportunity.class ELSE VALUES(class) END, "
            "class_source = CASE WHEN opportunity.class_source = 'human' THEN 'human' ELSE VALUES(class_source) END, "
            "classification_confidence = CASE WHEN opportunity.class_source = 'human' THEN opportunity.classification_confidence "
            "ELSE VALUES(classification_confidence) END, class_evidence = VALUES(class_evidence), "
            "title = VALUES(title), description = VALUES(description), counterparty_id = VALUES(counterparty_id), "
            "grant_program_id = VALUES(grant_program_id), geography = VALUES(geography), stage_fit = VALUES(stage_fit), "
            "amount_min = VALUES(amount_min), amount_max = VALUES(amount_max), currency = VALUES(currency), "
            "deadline = VALUES(deadline), source_ref = VALUES(source_ref), signal_id = VALUES(signal_id), "
            "url = VALUES(url), sectors = VALUES(sectors), esg_tags = VALUES(esg_tags)"
        ),
        params,
    )

    if prev_counterparty and prev_counterparty != counterparty_id:
        # the listing now names a different counterparty: drop the stale OFFERS edge
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
        {"class": cls.capital_class, "deadline": sig.deadline.isoformat() if sig.deadline else None},
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

    # ---- Knowledge Graph vertices & edges ----
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
            text("SELECT id FROM entity WHERE org_id = :org AND ref_table = :t AND ref_id = :id"),
            {"org": get_settings().org_id, "t": table, "id": node_id},
        )
    ).scalar()
    if ent is None:
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
    touching existing ones."""
    ea = await ensure_node(s, a[0], a[1], a[2], a[3], src, is_demo)
    eb = await ensure_node(s, b[0], b[1], b[2], b[3], src, is_demo)
    await _edge(s, ea, eb, rel, src, is_demo)
    await upsert_edge(s, a[0], a[2], rel, b[0], b[2], {"source_ref": json.dumps(src, default=str), **(props or {})})
