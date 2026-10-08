"""Runway & Forecast Studio API (FR-07): financial snapshot import (with column mapping), scenarios, forecasts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l1_perception.adapters.tabular import read_rows
from cortex.l1_perception.mapping import to_date, to_number
from cortex.l5_strategy.forecast_engine import Scenario
from cortex.l5_strategy.forecasting import preset, run_scenarios
from cortex.l7_governance import audit_service
from cortex.l8_actuation.api.common import row
from platform_core.auth.deps import authorize
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.db import get_session
from platform_core.errors import Problem

router = APIRouter(prefix="/v1/forecasts", tags=["forecasts"])
FIELDS = ["period", "cash", "revenue", "opex", "net_burn", "currency"]
GUESS = {
    "period": ["period", "month", "date", "as_of", "month_end"],
    "cash": ["cash", "cash_balance", "closing_cash", "bank_balance", "cash_end"],
    "revenue": ["revenue", "income", "sales", "turnover"],
    "opex": ["opex", "expenses", "operating_expenses", "costs", "spend", "total_expenses"],
    "net_burn": ["net_burn", "burn", "net_cash_burn", "burn_rate"],
    "currency": ["currency", "ccy"],
}


def _norm(h: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in h.strip().lower()).strip("_")


def suggest(headers: list[str]) -> dict[str, str | None]:
    normed = {_norm(h): h for h in headers}
    return {f: next((normed[g] for g in GUESS[f] if g in normed), None) for f in FIELDS}


@router.get("/snapshots", summary="Imported financial snapshots")
async def snapshots(
    _: Principal = Depends(authorize("forecast:read", "financial_snapshot")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id, period, cash, revenue, opex, net_burn, currency, source_ref, is_demo FROM financial_snapshot "
                    "WHERE org_id = :org ORDER BY period DESC"
                ),
                {"org": get_settings().org_id},
            )
        )
        .mappings()
        .all()
    )
    return {"items": [row(r) for r in rows]}


@router.post("/snapshots/preview", summary="Read a CSV/XLSX and suggest a column mapping (no persistence)")
async def preview(
    file: UploadFile = File(...), _: Principal = Depends(authorize("forecast:write", "financial_snapshot"))
) -> dict[str, Any]:
    data = await file.read(10 * 1024 * 1024)
    rows = read_rows(data, file.filename or "upload.csv")
    headers = list(rows[0].keys()) if rows else []
    return {
        "headers": headers,
        "sample": rows[:8],
        "rows": len(rows),
        "suggested_mapping": suggest(headers),
        "fields": FIELDS,
    }


@router.post("/snapshots/import", summary="Import financial snapshots with a column mapping")
async def import_snapshots(
    file: UploadFile = File(...),
    mapping: str = Form(...),
    default_currency: str = Form("USD"),
    p: Principal = Depends(authorize("forecast:write", "financial_snapshot")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    try:
        m: dict[str, str | None] = json.loads(mapping)
    except ValueError as e:
        raise Problem(422, "Invalid mapping", "mapping must be JSON {field: column}", "validation") from e
    if not m.get("period") or not (m.get("cash") or m.get("net_burn") or m.get("opex")):
        raise Problem(422, "Incomplete mapping", "map period plus at least one of cash / net_burn / opex", "validation")
    data = await file.read(10 * 1024 * 1024)
    digest = hashlib.sha256(data).hexdigest()
    rows = read_rows(data, file.filename or "upload.csv")
    imported, skipped = 0, []
    for i, r in enumerate(rows, start=2):
        period_col = m.get("period")
        period = to_date(r.get(period_col)) if period_col else None
        if period is None:
            skipped.append(f"row {i}: unreadable period")
            continue
        cols = {f: c for f, c in m.items() if c}
        vals = {f: (to_number(r.get(cols[f])) if f in cols else None) for f in ("cash", "revenue", "opex", "net_burn")}
        if all(v is None for v in vals.values()):
            skipped.append(f"row {i}: no numeric values")
            continue
        ccy_col = cols.get("currency")
        ccy = str(r.get(ccy_col)).strip().upper()[:3] if ccy_col and r.get(ccy_col) else default_currency.upper()[:3]
        src = {
            "kind": "file",
            "filename": file.filename,
            "sha256": digest,
            "row": i,
            "uploaded_by": p.username,
            "at": datetime.now(UTC).isoformat(),
            "mapping": m,
        }
        await session.execute(
            text(
                "INSERT INTO financial_snapshot (org_id, period, cash, revenue, opex, net_burn, currency, source_ref) "
                "VALUES (:org, :period, :cash, :rev, :opex, :burn, :ccy, CAST(:src AS jsonb)) ON CONFLICT (org_id, period) "
                "DO UPDATE SET cash = EXCLUDED.cash, revenue = EXCLUDED.revenue, opex = EXCLUDED.opex, "
                "net_burn = EXCLUDED.net_burn, currency = EXCLUDED.currency, source_ref = EXCLUDED.source_ref, is_demo = false"
            ),
            {
                "org": get_settings().org_id,
                "period": period.date().replace(day=1),
                "cash": vals["cash"],
                "rev": vals["revenue"],
                "opex": vals["opex"],
                "burn": vals["net_burn"],
                "ccy": ccy,
                "src": json.dumps(src),
            },
        )
        imported += 1
    await audit_service.record(
        session,
        p,
        "financials.import",
        "financial_snapshot:*",
        {"filename": file.filename, "sha256": digest, "imported": imported, "skipped": len(skipped)},
    )
    return {"imported": imported, "skipped": skipped[:50], "sha256": digest}


class HireIn(BaseModel):
    start_month_offset: int = Field(0, ge=0, le=120)
    monthly_cost: float = Field(ge=0)
    label: str | None = None


class ScenarioIn(BaseModel):
    name: str = Field("custom", max_length=60)
    burn_delta_pct: float = Field(0, ge=-90, le=500)
    inflow_probability_multiplier: float = Field(1.0, ge=0, le=5)
    inflow_delay_months: int = Field(0, ge=0, le=36)
    hires: list[HireIn] = Field(default_factory=list, max_length=50)
    raise_amount: float | None = Field(None, ge=0)
    raise_month_offset: int | None = Field(None, ge=0, le=120)
    raise_probability: float = Field(1.0, ge=0, le=1)
    probability_overrides: dict[str, float] = Field(default_factory=dict)


class ScenarioRunIn(BaseModel):
    scenarios: list[ScenarioIn] = Field(default_factory=list, max_length=6)
    include_presets: bool = True
    include_demo: bool = True


@router.post("/scenarios/run", summary="Run scenarios (base/downside/upside + custom), no persistence")
async def run(
    body: ScenarioRunIn,
    _: Principal = Depends(authorize("forecast:read", "forecast")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    scs = [preset(n) for n in ("base", "downside", "upside")] if body.include_presets else []
    scs += [Scenario(**{**sc.model_dump(), "hires": [h.model_dump() for h in sc.hires]}) for sc in body.scenarios]
    if not scs:
        raise Problem(422, "No scenarios", None, "validation")
    return await run_scenarios(session, scs, body.include_demo)


@router.get("", summary="Persisted forecasts")
async def list_forecasts(
    _: Principal = Depends(authorize("forecast:read", "forecast")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                text(
                    "SELECT id, scenario, horizon_months, status, runway_months, zero_cash_date, assumptions, created_at, is_demo "
                    "FROM forecast WHERE org_id = :org ORDER BY created_at DESC LIMIT 60"
                ),
                {"org": get_settings().org_id},
            )
        )
        .mappings()
        .all()
    )
    return {"items": [row(r) for r in rows]}


class CreateForecastIn(BaseModel):
    include_demo: bool = Field(
        False, description="mix synthetic demo snapshots and pipeline in (the saved rows are then demo)"
    )


@router.post("", status_code=201, summary="Compute and persist base/downside/upside forecasts")
async def create(
    body: CreateForecastIn | None = None,
    p: Principal = Depends(authorize("forecast:write", "forecast")),
    session: AsyncSession = Depends(get_session, scope="function"),
) -> dict[str, Any]:
    # Real data only by default: a saved forecast built on demo snapshots/pipeline must never pass for a real one.
    include_demo = bool(body and body.include_demo)
    out = await run_scenarios(session, [preset(n) for n in ("base", "downside", "upside")], include_demo)
    ids = []
    for r in out["results"]:
        inputs_ref = {
            "snapshots": (r.get("inputs") or {}).get("snapshot_refs", []),
            "assumptions": "config/forecast.yaml",
            "computed_by": "forecast_engine",
        }
        src = {"kind": "computed", "engine": "forecast_engine", "inputs": inputs_ref}
        fid = (
            await session.execute(
                text(
                    "INSERT INTO forecast (org_id, scenario, horizon_months, status, series, runway_months, zero_cash_date, "
                    "assumptions, inputs_ref, source_ref, is_demo) VALUES (:org, :sc, :h, :st, CAST(:series AS jsonb), :rw, :zc, "
                    "CAST(:as AS jsonb), CAST(:ir AS jsonb), CAST(:src AS jsonb), :demo) RETURNING id"
                ),
                {
                    "org": get_settings().org_id,
                    "sc": r["scenario"],
                    "h": r["horizon_months"],
                    "st": r["status"],
                    "series": json.dumps(r["series"], default=str),
                    "rw": r["runway_months"] if r["status"] == "ok" else None,
                    "zc": r["zero_cash_date"] if r["status"] == "ok" else None,
                    "as": json.dumps(r.get("inputs", {}), default=str),
                    "ir": json.dumps(inputs_ref, default=str),
                    "src": json.dumps(src, default=str),
                    "demo": include_demo,
                },
            )
        ).scalar_one()
        ids.append(str(fid))
    await audit_service.record(session, p, "forecast.create", "forecast:*", {"ids": ids, "include_demo": include_demo})
    return {"ids": ids, **out}
