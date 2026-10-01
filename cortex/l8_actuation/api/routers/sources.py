"""Sources & Ingestion (FR-01): adapter registry, health, run now, enable/disable, uploads, manual entry, signals."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l1_perception.ingestion import run_source
from cortex.l1_perception.registry import get_source, sync_sources
from cortex.l7_governance import audit_service
from cortex.l8_actuation.api.common import row
from platform_core.auth.deps import authorize
from platform_core.auth.principal import Principal
from platform_core.bus import Envelope, get_bus
from platform_core.config import get_settings
from platform_core.db import get_session
from platform_core.errors import Problem

router = APIRouter(prefix="/v1", tags=["ingestion"])
MAX_UPLOAD = 20 * 1024 * 1024


@router.get("/sources", summary="Adapter registry with health, last run and items/run")
async def list_sources(
    _: Principal = Depends(authorize("ingestion:read", "source")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    await sync_sources(session)
    rows = (
        (
            await session.execute(
                text(
                    "SELECT s.id, s.name, s.kind, s.adapter, s.adapter_key, s.schedule, s.enabled, s.health, s.last_run_at, "
                    "s.last_error, s.terms_note, (SELECT count(*) FROM signal sg WHERE sg.source_id = s.id) AS signals_total, "
                    "(SELECT row_to_json(r) FROM (SELECT id, status, trigger, started_at, finished_at, items_fetched, items_new, "
                    "items_duplicate, items_failed, error FROM source_run WHERE source_id = s.id ORDER BY started_at DESC LIMIT 1) r) "
                    "AS last_run, (SELECT count(*) FROM source_run WHERE source_id = s.id AND status = 'failed' "
                    "AND started_at > now() - interval '7 days') AS errors_7d FROM source s WHERE s.org_id = :org ORDER BY s.name"
                ),
                {"org": get_settings().org_id},
            )
        )
        .mappings()
        .all()
    )
    return {"items": [row(r) for r in rows]}


@router.get("/sources/{id}/runs", summary="Run history for a source")
async def source_runs(
    id: str,
    _: Principal = Depends(authorize("ingestion:read", "source")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id, trigger, requested_by, status, started_at, finished_at, items_fetched, items_new, items_duplicate, "
                    "items_failed, error FROM source_run WHERE source_id = CAST(:id AS uuid) ORDER BY started_at DESC LIMIT 50"
                ),
                {"id": id},
            )
        )
        .mappings()
        .all()
    )
    return {"items": [row(r) for r in rows]}


class SourcePatch(BaseModel):
    enabled: bool


@router.patch("/sources/{id}", summary="Enable or disable a source")
async def patch_source(
    id: str,
    body: SourcePatch,
    p: Principal = Depends(authorize("source:run", "source")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    await get_source(session, id)
    await session.execute(
        text(
            "UPDATE source SET enabled = :e, health = CASE WHEN :e THEN 'unknown' ELSE 'disabled' END WHERE id = CAST(:id AS uuid)"
        ),
        {"e": body.enabled, "id": id},
    )
    await audit_service.record(session, p, "source.enable" if body.enabled else "source.disable", f"source:{id}")
    return {"id": id, "enabled": body.enabled}


@router.post("/sources/{id}/run", status_code=202, summary="Run a source now (queued to the worker)")
async def run_now(
    id: str,
    p: Principal = Depends(authorize("source:run", "source")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    _, cfg = await get_source(session, id)
    if cfg.adapter in ("tabular", "manual"):
        raise Problem(
            422, "Not a pull source", f"{cfg.name} ingests uploads/entries; use /upload or /entries", "validation"
        )
    msg = await get_bus().publish(
        "system.jobs", Envelope(type="ingest.run", payload={"source_id": id, "trigger": "manual"}, actor_token=p.token)
    )
    await audit_service.record(session, p, "source.run.requested", f"source:{id}", {"stream_id": msg})
    return {"queued": True, "stream_id": msg}


@router.post(
    "/sources/{id}/upload",
    summary="Upload a CSV/XLSX (file source) or an .ics calendar (calendar source); runs immediately",
)
async def upload(
    id: str,
    file: UploadFile = File(...),
    p: Principal = Depends(authorize("source:run", "source")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    _, cfg = await get_source(session, id)
    allowed = {"tabular": (".csv", ".xlsx", ".xlsm", ".tsv", ".txt"), "ics": (".ics",)}
    if cfg.adapter not in allowed:
        raise Problem(
            422, "Not a file source", "choose the CSV / XLSX upload source or the calendar source", "validation"
        )
    name = file.filename or ("upload.ics" if cfg.adapter == "ics" else "upload.csv")
    if not name.lower().endswith(allowed[cfg.adapter]):
        raise Problem(415, "Unsupported file", f"upload {' or '.join(allowed[cfg.adapter])}", "unsupported-media-type")
    data = await file.read(MAX_UPLOAD + 1)
    if len(data) > MAX_UPLOAD:
        raise Problem(413, "File too large", "limit is 20 MB", "payload-too-large")
    return await run_source(id, p, "upload", upload=data, upload_name=name)


class ManualEntry(BaseModel):
    title: str = Field(min_length=3, max_length=500)
    description: str | None = Field(None, max_length=20000)
    url: str | None = Field(None, max_length=2000)
    counterparty_name: str | None = Field(None, max_length=300)
    counterparty_kind: str | None = None
    counterparty_country: str | None = None
    countries: list[str] = Field(default_factory=list)
    deadline: str | None = None
    amount_min: float | None = Field(None, ge=0)
    amount_max: float | None = Field(None, ge=0)
    currency: str | None = Field(None, min_length=3, max_length=3)
    class_hint: str | None = None
    stage_fit: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    investor_type: str | None = None
    external_id: str | None = None


@router.post("/sources/{id}/entries", summary="Manual entry of one or more opportunities (runs immediately)")
async def entries(
    id: str,
    body: list[ManualEntry],
    p: Principal = Depends(authorize("source:run", "source")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    _, cfg = await get_source(session, id)
    if cfg.adapter != "manual":
        raise Problem(422, "Not a manual source", "choose the Manual entry source", "validation")
    if not body or len(body) > 100:
        raise Problem(422, "1–100 entries", None, "validation")
    return await run_source(id, p, "manual", entries=[e.model_dump(exclude_none=True) for e in body])


class SignalIn(BaseModel):
    source_key: str
    items: list[dict[str, Any]] = Field(min_length=1, max_length=500)


@router.post("/signals", summary="Submit raw items for a configured source (service role)")
async def post_signals(
    body: SignalIn,
    p: Principal = Depends(authorize("signal:write", "signal")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    sid = (
        await session.execute(
            text("SELECT id FROM source WHERE org_id = :org AND adapter_key = :k"),
            {"org": get_settings().org_id, "k": body.source_key},
        )
    ).scalar()
    if sid is None:
        raise Problem(404, "Unknown source", f"no source {body.source_key}", "not-found")
    return await run_source(str(sid), p, "manual", entries=body.items)
