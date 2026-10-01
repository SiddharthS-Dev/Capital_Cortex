"""Grant Calendar (screen 11): deadlines and milestones as calendar events, plus an iCal export."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l7_governance import audit_service
from platform_core.auth.deps import authorize
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.db import get_session

router = APIRouter(prefix="/v1/calendar", tags=["calendar"])


async def _events(
    s: AsyncSession, start: datetime, end: datetime, include_demo: bool, classes: list[str] | None
) -> list[dict[str, Any]]:
    org = get_settings().org_id
    out: list[dict[str, Any]] = []
    for r in (
        await s.execute(
            text(
                "SELECT o.id, o.title, o.class::text AS class, o.deadline, o.score_band, o.pipeline_stage::text AS stage, o.url, o.is_demo, "
                "cp.name AS counterparty FROM opportunity o LEFT JOIN organization cp ON cp.id = o.counterparty_id WHERE o.org_id = :org "
                "AND o.status IN ('active','watchlist') AND o.deadline BETWEEN :a AND :b AND (:demo OR NOT o.is_demo) "
                "AND (CAST(:cls AS text[]) IS NULL OR o.class::text = ANY(:cls)) ORDER BY o.deadline LIMIT 2000"
            ),
            {"org": org, "a": start, "b": end, "demo": include_demo, "cls": classes},
        )
    ).mappings():
        out.append({
            "id": f"deadline:{r['id']}", "type": "deadline", "title": r["title"], "start": r["deadline"].isoformat(),
            "class": r["class"], "band": r["score_band"], "stage": r["stage"], "opportunity_id": str(r["id"]),
            "counterparty": r["counterparty"], "url": r["url"], "is_demo": r["is_demo"], "ref": f"opportunity:{r['id']}#deadline",
        })  # fmt: skip
    for r in (
        await s.execute(
            text(
                "SELECT m.id, m.kind, m.title, m.due_at, m.status, m.opportunity_id, m.is_demo, o.class::text AS class, c.name AS contact "
                "FROM milestone m LEFT JOIN opportunity o ON o.id = m.opportunity_id LEFT JOIN contact c ON c.id = m.contact_id "
                "WHERE m.org_id = :org AND m.status IN ('open','done') AND m.due_at BETWEEN :a AND :b AND (:demo OR NOT m.is_demo) "
                "AND (CAST(:cls AS text[]) IS NULL OR o.class::text = ANY(:cls) OR m.opportunity_id IS NULL) ORDER BY m.due_at LIMIT 2000"
            ),
            {"org": org, "a": start, "b": end, "demo": include_demo, "cls": classes},
        )
    ).mappings():
        out.append({
            "id": f"milestone:{r['id']}", "type": r["kind"], "title": r["title"], "start": r["due_at"].isoformat(),
            "class": r["class"], "status": r["status"], "opportunity_id": str(r["opportunity_id"]) if r["opportunity_id"] else None,
            "contact": r["contact"], "is_demo": r["is_demo"], "ref": f"milestone:{r['id']}",
            "overdue": r["status"] == "open" and r["due_at"] < datetime.now(UTC),
        })  # fmt: skip
    return out


@router.get("/events", summary="Deadlines, submissions, follow-ups and commitment expiries in a window")
async def events(
    start: datetime | None = None,
    end: datetime | None = None,
    include_demo: bool = True,
    cls: list[str] | None = Query(None, alias="class"),
    _: Principal = Depends(authorize("opportunity:read", "calendar")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    start = start or datetime.now(UTC) - timedelta(days=7)
    end = end or start + timedelta(days=120)
    return {
        "events": await _events(session, start, end, include_demo, cls),
        "start": start.isoformat(),
        "end": end.isoformat(),
    }


def _ics_escape(v: str) -> str:
    return v.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


@router.get(
    "/export.ics",
    summary="iCal export for internal users (authenticated; audited)",
    response_class=Response,
    responses={200: {"content": {"text/calendar": {}}, "description": "iCalendar file"}},
)
async def export_ics(
    include_demo: bool = False,
    days: int = Query(365, ge=1, le=1095),
    p: Principal = Depends(authorize("opportunity:read", "calendar")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> Response:
    now = datetime.now(UTC)
    evs = await _events(session, now - timedelta(days=30), now + timedelta(days=days), include_demo, None)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Inspironics//Capital Cortex//EN", "CALSCALE:GREGORIAN",
             "X-WR-CALNAME:Capital Cortex deadlines"]  # fmt: skip
    for e in evs:
        when = datetime.fromisoformat(e["start"]).astimezone(UTC)
        prefix = {
            "deadline": "Deadline",
            "submission": "Submission",
            "follow_up": "Follow-up",
            "commitment_expiry": "Commitment",
        }.get(e["type"], e["type"])
        lines += [
            "BEGIN:VEVENT", f"UID:{e['id']}@capital-cortex", f"DTSTAMP:{stamp}", f"DTSTART:{when.strftime('%Y%m%dT%H%M%SZ')}",
            f"DTEND:{(when + timedelta(minutes=30)).strftime('%Y%m%dT%H%M%SZ')}", f"SUMMARY:{_ics_escape(prefix + ': ' + e['title'][:200])}",
            f"CATEGORIES:{_ics_escape(e.get('class') or 'unclassified')}",
        ]  # fmt: skip
        if e.get("url"):
            lines.append(f"URL:{e['url']}")
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    await audit_service.record(
        session, p, "calendar.exported", "calendar:ics", {"events": len(evs), "include_demo": include_demo}
    )
    body = "\r\n".join(lines) + "\r\n"
    return Response(
        body, media_type="text/calendar", headers={"Content-Disposition": 'attachment; filename="capital-cortex.ics"'}
    )
