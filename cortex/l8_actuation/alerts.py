"""alerts (FR-08): a deterministic rule engine over the knowledge graph, milestones and the forecast.

Rules live in ``alert_rule`` (seeded from ``config/alerts.yaml``). Each evaluation creates alerts
idempotently through a ``dedup_key`` (one alert per opportunity per deadline bucket, per milestone, per
runway projection), resolves alerts whose cause has gone, and wakes snoozed alerts. Every alert carries the
rule and subject it came from (source_ref, I1). Deliveries: in-app always; internal e-mail only to
configured internal addresses; webhook only to the configured internal endpoint. External recipients are
never alerted directly.
"""

from __future__ import annotations

import asyncio
import json
import logging
import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core import secrets
from platform_core.config import get_settings

log = logging.getLogger(__name__)
KINDS = ("new_opp", "deadline", "follow_up", "runway_risk", "expiring_commitment", "custom")
CUSTOM_FIELDS = {
    "score": "o.score",
    "completeness": "o.completeness",
    "days_to_deadline": "EXTRACT(EPOCH FROM (o.deadline - now())) / 86400",
}
CUSTOM_OPS = {">=": ">=", "<=": "<=", ">": ">", "<": "<", "=": "="}


@lru_cache
def alerts_config() -> dict[str, Any]:
    return yaml.safe_load((get_settings().config_dir / "alerts.yaml").read_text(encoding="utf-8")) or {}


def validate_rule(kind: str, expr: dict[str, Any]) -> None:
    from platform_core.errors import Problem

    if kind not in KINDS:
        raise Problem(422, "Invalid kind", f"kind must be one of {KINDS}", "validation")
    if kind == "custom":
        if expr.get("field") not in CUSTOM_FIELDS or expr.get("op") not in CUSTOM_OPS:
            raise Problem(
                422, "Invalid condition", f"field in {sorted(CUSTOM_FIELDS)}, op in {sorted(CUSTOM_OPS)}", "validation"
            )
        try:
            float(expr["value"])
        except (KeyError, TypeError, ValueError) as e:
            raise Problem(422, "Invalid threshold", "value must be a number", "validation") from e


async def seed_default_rules(s: AsyncSession) -> int:
    n = 0
    for r in alerts_config().get("defaults", []):
        res = await s.execute(
            text(
                "INSERT INTO alert_rule (org_id, name, kind, rule_expr, severity, channels, enabled, is_default, description, created_by) "
                "VALUES (:org, :n, :k, CAST(:e AS jsonb), :sev, :ch, true, true, :d, 'system:default') "
                "ON CONFLICT (org_id, name) DO NOTHING"
            ),
            {"org": get_settings().org_id, "n": r["name"], "k": r["kind"], "e": json.dumps(r["rule_expr"]),
             "sev": r["severity"], "ch": r["channels"], "d": r.get("description")},
        )  # fmt: skip
        n += getattr(res, "rowcount", 0) or 0
    return n


# ----------------------------------------------------------------------------- candidates per rule kind
async def _new_opp(s: AsyncSession, e: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    rows = (
        (
            await s.execute(
                text(
                    "SELECT id, title, score, is_demo FROM opportunity WHERE org_id = :org AND status = 'active' AND score_band = 'high' "
                    "AND score >= :min AND created_at >= :since"
                ),
                {
                    "org": get_settings().org_id,
                    "min": float(e.get("min_score", 0.7)),
                    "since": now - timedelta(hours=float(e.get("within_hours", 24))),
                },
            )
        )
        .mappings()
        .all()
    )
    return [
        {"key": f"new_opp:{r['id']}", "subject": ("opportunity", r["id"]), "demo": r["is_demo"], "drill": f"/opportunities/{r['id']}",
         "message": f"New high-score opportunity ({float(r['score']) * 100:.1f}/100): {r['title'][:140]}"}
        for r in rows
    ]  # fmt: skip


async def _deadline(s: AsyncSession, e: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    offsets = sorted(int(x) for x in e.get("offsets_days", [30, 14, 7, 2]))
    rows = (
        (
            await s.execute(
                text(
                    "SELECT id, title, deadline, is_demo FROM opportunity WHERE org_id = :org AND status IN ('active','watchlist') "
                    "AND deadline > :now AND deadline <= :until AND ((cardinality(CAST(:bands AS text[])) = 0 AND "
                    "cardinality(CAST(:stages AS text[])) = 0) OR score_band = ANY(:bands) OR pipeline_stage::text = ANY(:stages))"
                ),
                {
                    "org": get_settings().org_id,
                    "now": now,
                    "until": now + timedelta(days=max(offsets)),
                    "bands": e.get("bands") or [],
                    "stages": e.get("stages") or [],
                },
            )
        )
        .mappings()
        .all()
    )
    out = []
    for r in rows:
        days = (r["deadline"] - now).total_seconds() / 86400
        bucket = next(o for o in offsets if days <= o)
        crit = days <= float(e.get("critical_at_days", 7))
        out.append({
            "key": f"deadline:{r['id']}:T-{bucket}", "subject": ("opportunity", r["id"]), "demo": r["is_demo"],
            "severity": "critical" if crit else None, "due_at": r["deadline"], "drill": f"/opportunities/{r['id']}",
            "message": f"T-{bucket}: deadline {r['deadline'].date().isoformat()} ({int(days)} days) for {r['title'][:140]}",
        })  # fmt: skip
    return out


async def _milestones(
    s: AsyncSession, kind: str, now: datetime, until: datetime | None, overdue: bool
) -> list[dict[str, Any]]:
    cond = "m.due_at < :now" if overdue else "m.due_at BETWEEN :now AND :until"
    return [
        dict(r)
        for r in (
            await s.execute(
                text(
                    "SELECT m.id, m.title, m.due_at, m.opportunity_id, m.contact_id, m.is_demo FROM milestone m WHERE m.org_id = :org "
                    f"AND m.kind = :k AND m.status = 'open' AND {cond}"
                ),
                {"org": get_settings().org_id, "k": kind, "now": now, "until": until},
            )
        )
        .mappings()
        .all()
    ]


async def _follow_up(s: AsyncSession, e: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    rows = await _milestones(s, "follow_up", now - timedelta(days=float(e.get("grace_days", 0))), None, True)
    return [
        {"key": f"follow_up:{r['id']}", "subject": ("milestone", r["id"]), "demo": r["is_demo"], "due_at": r["due_at"],
         "drill": f"/opportunities/{r['opportunity_id']}" if r["opportunity_id"] else "/relationships",
         "message": f"Overdue since {r['due_at'].date().isoformat()}: {r['title'][:160]}"}
        for r in rows
    ]  # fmt: skip


async def _expiring(s: AsyncSession, e: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    rows = await _milestones(s, "commitment_expiry", now, now + timedelta(days=float(e.get("within_days", 14))), False)
    return [
        {"key": f"commitment:{r['id']}", "subject": ("milestone", r["id"]), "demo": r["is_demo"], "due_at": r["due_at"],
         "drill": "/relationships", "message": f"Expires {r['due_at'].date().isoformat()}: {r['title'][:160]}"}
        for r in rows
    ]  # fmt: skip


async def _runway(s: AsyncSession, e: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    from cortex.l5_strategy.forecasting import preset, run_scenarios

    out = []
    for demo in (False, True):
        res = (await run_scenarios(s, [preset("base")], include_demo=demo, grouped=True))["results"][0]
        has_demo_only = (
            demo and (await s.execute(text("SELECT EXISTS (SELECT 1 FROM financial_snapshot WHERE is_demo)"))).scalar()
        )
        if demo and not has_demo_only:
            continue
        months = res.get("runway_months_from_today", res["runway_months"])  # from today, not from the last snapshot
        if res["status"] == "ok" and not res["beyond_horizon"] and months < float(e.get("months", 9)):
            out.append({
                "key": f"runway:{'demo' if demo else 'real'}:{res['zero_cash_date']}", "subject": ("forecast", None), "demo": demo,
                "drill": "/forecast",
                "message": f"Base-case runway {months:.2f} months (< {e.get('months', 9)}); zero cash {res['zero_cash_date']}",
            })  # fmt: skip
    return out


async def _custom(s: AsyncSession, e: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    validate_rule("custom", e)
    expr, op = CUSTOM_FIELDS[e["field"]], CUSTOM_OPS[e["op"]]
    where = [f"{expr} {op} :v", "o.org_id = :org", "o.status = 'active'"]
    p: dict[str, Any] = {"v": float(e["value"]), "org": get_settings().org_id}
    if e.get("class"):
        where.append("o.class::text = :cls")
        p["cls"] = e["class"]
    rows = (
        (
            await s.execute(
                text(f"SELECT o.id, o.title, o.is_demo FROM opportunity o WHERE {' AND '.join(where)} LIMIT 200"),
                p,
            )
        )
        .mappings()
        .all()
    )
    return [
        {"key": f"custom:{e['field']}{e['op']}{e['value']}:{r['id']}", "subject": ("opportunity", r["id"]), "demo": r["is_demo"],
         "drill": f"/opportunities/{r['id']}", "message": f"{e['field']} {e['op']} {e['value']}: {r['title'][:160]}"}
        for r in rows
    ]  # fmt: skip


EVALUATORS = {
    "new_opp": _new_opp, "deadline": _deadline, "follow_up": _follow_up, "runway_risk": _runway,
    "expiring_commitment": _expiring, "custom": _custom,
}  # fmt: skip


# ----------------------------------------------------------------------------- delivery
def _email(to: list[str], subject: str, body: str) -> None:
    s = get_settings()
    u = urlparse(s.smtp_url or "")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s.smtp_from, ", ".join(to), subject
    msg.set_content(body)
    cls = smtplib.SMTP_SSL if u.scheme == "smtps" else smtplib.SMTP
    with cls(u.hostname or "localhost", u.port or 25, timeout=15) as c:
        pw = secrets.resolve(s.smtp_password_ref)
        if u.username and pw:
            c.login(u.username, pw)
        c.send_message(msg)


async def _deliver(s: AsyncSession, alert_id: str, channels: list[str], message: str, severity: str) -> None:
    st = get_settings()

    async def log_delivery(ch: str, target: str | None, status: str, detail: str | None = None) -> None:
        await s.execute(
            text(
                "INSERT INTO alert_delivery (org_id, alert_id, channel, target, status, detail) VALUES (:org, :a, :c, :t, :s, :d)"
            ),
            {"org": st.org_id, "a": alert_id, "c": ch, "t": target, "s": status, "d": detail},
        )

    await log_delivery("in_app", None, "sent")
    if "internal_email" in channels:
        domains = {d.lower() for d in st.internal_email_domains}
        to = [a for a in alerts_config().get("internal_recipients") or [] if a.rsplit("@", 1)[-1].lower() in domains]
        if not st.smtp_url or not to:
            await log_delivery(
                "internal_email", None, "skipped", "no SMTP_URL or no internal recipients in an internal domain"
            )
        else:
            try:
                await asyncio.to_thread(_email, to, f"[Capital Cortex · {severity}] {message[:120]}", message)
                await log_delivery("internal_email", ", ".join(to), "sent")
            except (OSError, smtplib.SMTPException) as e:
                await log_delivery("internal_email", ", ".join(to), "failed", str(e)[:500])
    if "webhook" in channels:
        if not st.alert_webhook_url:
            await log_delivery("webhook", None, "skipped", "ALERT_WEBHOOK_URL not configured")
        else:
            try:
                async with httpx.AsyncClient(timeout=10) as c:
                    r = await c.post(
                        st.alert_webhook_url, json={"alert_id": alert_id, "severity": severity, "message": message}
                    )
                    r.raise_for_status()
                await log_delivery("webhook", st.alert_webhook_url, "sent")
            except httpx.HTTPError as e:
                await log_delivery("webhook", st.alert_webhook_url, "failed", str(e)[:500])


# ----------------------------------------------------------------------------- evaluation
async def evaluate(s: AsyncSession, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    org = get_settings().org_id
    await s.execute(
        text(
            "UPDATE alert SET status = 'open', snoozed_until = NULL WHERE org_id = :org AND status = 'snoozed' AND snoozed_until <= :now"
        ),
        {"org": org, "now": now},
    )
    rules = (
        (await s.execute(text("SELECT * FROM alert_rule WHERE org_id = :org AND enabled ORDER BY name"), {"org": org}))
        .mappings()
        .all()
    )
    created: list[str] = []
    for rule in rules:
        try:
            cands = await EVALUATORS[rule["kind"]](s, dict(rule["rule_expr"] or {}), now)
        except Exception as e:  # one bad rule never stops the others
            log.warning("alert rule %s failed: %s", rule["name"], e)
            continue
        for c in cands:
            sev = c.get("severity") or rule["severity"]
            subj_type, subj_id = c["subject"]
            aid = (
                await s.execute(
                    text(
                        "INSERT INTO alert (org_id, rule_id, kind, severity, subject_type, subject_id, message, status, dedup_key, drill, "
                        "due_at, source_ref, is_demo) VALUES (:org, :r, :k, :sev, :st, :sid, :m, 'open', :key, :drill, :due, "
                        "CAST(:src AS jsonb), :demo) ON CONFLICT (org_id, dedup_key) WHERE dedup_key IS NOT NULL DO NOTHING RETURNING id"
                    ),
                    {
                        "org": org, "r": rule["id"], "k": rule["kind"], "sev": sev, "st": subj_type, "sid": subj_id, "m": c["message"],
                        "key": c["key"], "drill": c.get("drill"), "due": c.get("due_at"), "demo": bool(c.get("demo")),
                        "src": json.dumps({"kind": "alert_rule", "rule_id": str(rule["id"]), "rule": rule["name"],
                                           "subject": f"{subj_type}:{subj_id}" if subj_id else subj_type, "evaluated_at": now.isoformat()}),
                    },
                )
            ).scalar()  # fmt: skip
            if aid:
                created.append(str(aid))
                await _deliver(s, str(aid), list(rule["channels"]), c["message"], sev)
        await s.execute(
            text("UPDATE alert_rule SET last_evaluated_at = :now WHERE id = :id"), {"now": now, "id": rule["id"]}
        )
    # resolve alerts whose cause is gone: milestones done/cancelled, deadlines passed, opportunities closed
    resolved_res = await s.execute(
        text(
            "UPDATE alert a SET status = 'resolved' WHERE a.org_id = :org AND a.status IN ('open','snoozed','acked') AND ("
            "(a.subject_type = 'milestone' AND EXISTS (SELECT 1 FROM milestone m WHERE m.id = a.subject_id AND m.status IN ('done','cancelled'))) "
            "OR (a.kind = 'deadline' AND a.due_at < :now) "
            "OR (a.subject_type = 'opportunity' AND EXISTS (SELECT 1 FROM opportunity o WHERE o.id = a.subject_id "
            "AND o.status IN ('archived','won','lost','withdrawn'))))"
        ),
        {"org": org, "now": now},
    )
    resolved = getattr(resolved_res, "rowcount", 0)
    if created:
        from cortex.l2_representation.pipeline import publish_event

        await publish_event({"type": "alert.created", "count": len(created), "ids": created[:50]})
    return {"rules": len(rules), "created": len(created), "resolved": int(resolved or 0)}
