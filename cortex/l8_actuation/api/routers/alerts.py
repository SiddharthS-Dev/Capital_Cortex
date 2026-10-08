"""Alerts Center API (FR-08): feed with ack / snooze / assign / resolve, and the rule builder."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l2_representation.pipeline import publish_event
from cortex.l7_governance import audit_service
from cortex.l8_actuation import alerts as engine
from cortex.l8_actuation.api.common import row
from platform_core.auth.deps import authorize
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.db import get_session, session_scope
from platform_core.errors import NotFound, Problem

router = APIRouter(prefix="/v1", tags=["alerts"])
Severity = Literal["info", "warning", "critical"]
Channel = Literal["in_app", "internal_email", "webhook"]


@router.get("/alerts", summary="Alert feed (open first, most severe first)")
async def list_alerts(
    status: list[str] | None = Query(None),
    severity: list[str] | None = Query(None),
    kind: list[str] | None = Query(None),
    include_demo: bool = True,
    limit: int = Query(100, ge=1, le=500),
    _: Principal = Depends(authorize("alert:read", "alert")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    org = get_settings().org_id
    rows = (
        (
            await session.execute(
                text(
                    "SELECT a.id, a.kind, a.severity, a.subject_type, a.subject_id, a.message, a.status, a.assigned_to, a.snoozed_until, "
                    "a.acked_by, a.acked_at, a.drill, a.due_at, a.created_at, a.is_demo, a.source_ref, r.name AS rule_name, "
                    "(SELECT array_agg(DISTINCT d.channel || ':' || d.status) FROM alert_delivery d WHERE d.alert_id = a.id) AS deliveries "
                    "FROM alert a LEFT JOIN alert_rule r ON r.id = a.rule_id WHERE a.org_id = :org AND a.status = ANY(:st) "
                    "AND (CAST(:sev AS text[]) IS NULL OR a.severity = ANY(:sev)) AND (CAST(:k AS text[]) IS NULL OR a.kind = ANY(:k)) "
                    "AND (:demo OR NOT a.is_demo) ORDER BY CASE a.severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END, "
                    "a.created_at DESC LIMIT :n"
                ),
                {
                    "org": org,
                    "st": status or ["open", "acked", "snoozed"],
                    "sev": severity,
                    "k": kind,
                    "demo": include_demo,
                    "n": limit,
                },
            )
        )
        .mappings()
        .all()
    )
    counts = {
        r[0]: r[1]
        for r in (
            await session.execute(
                text(
                    "SELECT severity, count(*) FROM alert WHERE org_id = :org AND status = 'open' AND (:demo OR NOT is_demo) GROUP BY 1"
                ),
                {"org": org, "demo": include_demo},
            )
        ).all()
    }
    return {"items": [row(r) for r in rows], "open_by_severity": counts, "open": sum(counts.values())}


class ManualAlert(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    severity: Severity = "info"
    subject_type: str | None = None
    subject_id: str | None = None


@router.post("/alerts", status_code=201, summary="Create a manual (internal) alert")
async def create_alert(
    body: ManualAlert,
    p: Principal = Depends(authorize("alert:write", "alert")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    aid = (
        await session.execute(
            text(
                "INSERT INTO alert (org_id, kind, severity, subject_type, subject_id, message, source_ref) VALUES "
                "(:org, 'custom', :sev, :st, :sid, :m, CAST(:src AS jsonb)) RETURNING id"
            ),
            {"org": get_settings().org_id, "sev": body.severity, "st": body.subject_type, "sid": body.subject_id, "m": body.message,
             "src": json.dumps({"kind": "manual_entry", "entered_by": p.username or p.sub})},
        )
    ).scalar_one()  # fmt: skip
    await audit_service.record(session, p, "alert.created", f"alert:{aid}", body.model_dump())
    await publish_event({"type": "alert.created", "count": 1, "ids": [str(aid)]})
    return {"id": str(aid)}


class AlertAction(BaseModel):
    until: datetime | None = None
    assignee: str | None = Field(None, max_length=200)


async def _update(
    session: AsyncSession, p: Principal, id: str, sets: str, prm: dict[str, Any], action: str
) -> dict[str, Any]:
    n = (
        await session.execute(
            text(f"UPDATE alert SET {sets} WHERE id = CAST(:id AS uuid) AND org_id = :org RETURNING status"),
            {**prm, "id": id, "org": get_settings().org_id},
        )
    ).scalar()
    if n is None:
        raise NotFound("alert not found")
    await audit_service.record(
        session, p, f"alert.{action}", f"alert:{id}", {k: v for k, v in prm.items() if k != "by"}
    )
    await publish_event({"type": "alert.updated", "ids": [id]})
    return {"id": id, "status": n}


@router.post("/alerts/{id}/ack", summary="Acknowledge an alert")
async def ack(
    id: str,
    p: Principal = Depends(authorize("alert:write", "alert")),
    session: AsyncSession = Depends(get_session, scope="function"),
):
    return await _update(session, p, id, "status = 'acked', acked_by = :by, acked_at = now()", {"by": p.sub}, "acked")


@router.post("/alerts/{id}/snooze", summary="Snooze an alert until a time")
async def snooze(
    id: str,
    body: AlertAction,
    p: Principal = Depends(authorize("alert:write", "alert")),
    session: AsyncSession = Depends(get_session, scope="function"),
):
    if body.until is None:
        raise Problem(422, "until required", "snooze needs an until time", "validation")
    return await _update(session, p, id, "status = 'snoozed', snoozed_until = :u", {"u": body.until}, "snoozed")


@router.post("/alerts/{id}/assign", summary="Assign an alert to a user")
async def assign(
    id: str,
    body: AlertAction,
    p: Principal = Depends(authorize("alert:write", "alert")),
    session: AsyncSession = Depends(get_session, scope="function"),
):
    return await _update(session, p, id, "assigned_to = :a", {"a": body.assignee or p.sub}, "assigned")


@router.post("/alerts/{id}/resolve", summary="Resolve an alert")
async def resolve(
    id: str,
    p: Principal = Depends(authorize("alert:write", "alert")),
    session: AsyncSession = Depends(get_session, scope="function"),
):
    return await _update(session, p, id, "status = 'resolved'", {}, "resolved")


@router.post("/alerts/evaluate", summary="Evaluate every enabled rule now")
async def evaluate_now(p: Principal = Depends(authorize("alert:write", "alert_rule"))) -> dict[str, Any]:
    pending: list[dict[str, Any]] = []
    async with session_scope() as session:
        await engine.seed_default_rules(session)
        out = await engine.evaluate(session, pending=pending)
        out = {k: out[k] for k in ("rules", "created", "resolved")} | {"ids": out["ids"][:50]}
        await audit_service.record(
            session, p, "alerts.evaluated", "alert_rule:*", {k: out[k] for k in ("rules", "created", "resolved")}
        )
    # after the commit: external deliveries happen once, for alerts that really exist
    out["delivered"] = await engine.deliver_pending(pending, out["ids"])
    return out


# ----------------------------------------------------------------------------- rules
@router.get("/alert-rules", summary="Alert rules")
async def list_rules(
    _: Principal = Depends(authorize("alert:read", "alert_rule")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    await engine.seed_default_rules(session)
    rows = (
        (
            await session.execute(
                text(
                    "SELECT r.*, (SELECT count(*) FROM alert a WHERE a.rule_id = r.id AND a.status = 'open') AS open_alerts "
                    "FROM alert_rule r WHERE r.org_id = :org ORDER BY r.is_default DESC, r.name"
                ),
                {"org": get_settings().org_id},
            )
        )
        .mappings()
        .all()
    )
    return {"items": [row(r) for r in rows], "kinds": list(engine.KINDS), "custom_fields": sorted(engine.CUSTOM_FIELDS)}


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: Literal["new_opp", "deadline", "follow_up", "runway_risk", "expiring_commitment", "custom"]
    rule_expr: dict[str, Any]
    severity: Severity = "warning"
    channels: list[Channel] = Field(default_factory=lambda: list[Channel](["in_app"]), min_length=1)
    enabled: bool = True
    description: str | None = Field(None, max_length=500)


@router.post("/alert-rules", status_code=201, summary="Create an alert rule (condition + threshold + channel)")
async def create_rule(
    body: RuleIn,
    p: Principal = Depends(authorize("alert:write", "alert_rule")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    engine.validate_rule(body.kind, body.rule_expr)
    rid = (
        await session.execute(
            text(
                "INSERT INTO alert_rule (org_id, name, kind, rule_expr, severity, channels, enabled, description, created_by) VALUES "
                "(:org, :n, :k, CAST(:e AS jsonb), :sev, :ch, :en, :d, :by) ON CONFLICT (org_id, name) DO NOTHING RETURNING id"
            ),
            {"org": get_settings().org_id, "n": body.name, "k": body.kind, "e": json.dumps(body.rule_expr), "sev": body.severity,
             "ch": list(body.channels), "en": body.enabled, "d": body.description, "by": p.sub},
        )
    ).scalar()  # fmt: skip
    if rid is None:
        raise Problem(409, "Rule exists", "a rule with this name already exists", "conflict")
    await audit_service.record(session, p, "alert_rule.created", f"alert_rule:{rid}", body.model_dump())
    return {"id": str(rid)}


class RulePatch(BaseModel):
    rule_expr: dict[str, Any] | None = None
    severity: Severity | None = None
    channels: list[Channel] | None = None
    enabled: bool | None = None


@router.patch("/alert-rules/{id}", summary="Update a rule (threshold, channels, severity, enabled)")
async def patch_rule(
    id: str, body: RulePatch, p: Principal = Depends(authorize("alert:write", "alert_rule")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:  # fmt: skip
    cur = (
        (await session.execute(text("SELECT kind FROM alert_rule WHERE id = CAST(:id AS uuid) AND org_id = :org"),
                               {"id": id, "org": get_settings().org_id}))
        .mappings()
        .first()
    )  # fmt: skip
    if cur is None:
        raise NotFound("rule not found")
    if body.rule_expr is not None:
        engine.validate_rule(cur["kind"], body.rule_expr)
    await session.execute(
        text(
            "UPDATE alert_rule SET rule_expr = COALESCE(CAST(:e AS jsonb), rule_expr), severity = COALESCE(:sev, severity), "
            "channels = COALESCE(CAST(:ch AS text[]), channels), enabled = COALESCE(:en, enabled) WHERE id = CAST(:id AS uuid)"
        ),
        {"e": json.dumps(body.rule_expr) if body.rule_expr is not None else None, "sev": body.severity,
         "ch": list(body.channels) if body.channels else None, "en": body.enabled, "id": id},
    )  # fmt: skip
    await audit_service.record(session, p, "alert_rule.updated", f"alert_rule:{id}", body.model_dump(exclude_none=True))
    return {"id": id, "updated": list(body.model_dump(exclude_none=True))}
