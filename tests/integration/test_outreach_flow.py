"""Capital outreach workbook (FR-04-OUT) through the real API on the real database."""

from __future__ import annotations

import json
from pathlib import Path

import fakeredis.aioredis
import httpx
import pytest
from sqlalchemy import text

from cortex.l2_representation.pipeline import process_signal
from cortex.l8_actuation.api.app import create_app
from platform_core.auth import oidc
from platform_core.bus import streams
from platform_core.db import session_scope
from platform_core.policy import opa
from platform_core.policy.opa import PolicyDecision

pytestmark = pytest.mark.integration

WORKBOOK = Path(__file__).resolve().parents[2] / "docs" / "Meris_Capital_Cortex_Outreach_Workbook_2026-10-06_9405.xlsx"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class AllowOPA:
    async def evaluate(self, package, input_):
        return PolicyDecision(True, [])


@pytest.fixture
async def client(engine, verifier):
    oidc.set_verifier(verifier)
    opa.set_opa(AllowOPA())  # type: ignore[arg-type]
    streams.set_bus(streams.Bus(fakeredis.aioredis.FakeRedis()))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app()), base_url="http://t") as c:
        yield c
    oidc.set_verifier(None)
    opa.set_opa(None)
    streams.set_bus(None)


async def drain_signals() -> int:
    bus = streams.get_bus()
    msgs = await bus.r.xrange("signals.raw")
    for _, fields in msgs:
        await process_signal(json.loads(fields[b"payload"])["signal_id"])
    await bus.r.delete("signals.raw")
    return len(msgs)


def _file() -> dict:
    return {"file": (WORKBOOK.name, WORKBOOK.read_bytes(), XLSX)}


async def _source_id(client, h, key: str) -> str:
    items = (await client.get("/v1/sources", headers=h)).json()["items"]
    return next(s["id"] for s in items if s["adapter_key"] == key)


async def test_workbook_inspect_upload_and_reupload(client, make_token):
    h = {"Authorization": f"Bearer {make_token(['admin', 'approver'], auth_age=5)}"}
    src = await _source_id(client, h, "capital_outreach")

    # a sheet that isn't there: 422 naming the ones that are, nothing written
    r = await client.post(f"/v1/sources/{src}/upload/inspect?sheet=Nope", headers=h, files=_file())
    assert r.status_code == 422 and "sheet 'Nope' not found; available: ['00_Read_Me'" in r.json()["detail"]
    r = await client.post(f"/v1/sources/{src}/upload?sheet=Nope", headers=h, files=_file())
    assert r.status_code == 422

    # dry run: the configured sheet, 27 headers matched, 52 would import, nothing stored
    r = await client.post(f"/v1/sources/{src}/upload/inspect", headers=h, files=_file())
    assert r.status_code == 200, r.text
    rep = r.json()
    assert rep["sheet"] == "12_Meris_Import" and len(rep["headers"]) == 27 and rep["would_import"] == 52
    assert rep["unmapped_headers"] == [] and rep["required_missing"] == []
    async with session_scope() as s:
        n = await s.execute(text("SELECT count(*) FROM signal WHERE source_id = CAST(:s AS uuid)"), {"s": src})
        assert n.scalar() == 0  # the dry run stored nothing
        assert (
            await s.execute(text("SELECT count(*) FROM audit_log WHERE action = 'source.upload.inspect'"))
        ).scalar() == 1

    # upload: 52 new → 52 opportunities keyed by prospect id; no amount, currency or deadline anywhere
    r = await client.post(f"/v1/sources/{src}/upload", headers=h, files=_file())
    assert r.status_code == 200, r.text
    assert (r.json()["new"], r.json()["failed"], r.json()["status"]) == (52, 0, "succeeded")
    assert await drain_signals() == 52
    async with session_scope() as s:
        rows = (
            await s.execute(
                text(
                    "SELECT external_key, amount_min, amount_max, currency, deadline FROM opportunity "
                    "WHERE external_key LIKE 'capital_outreach:%'"
                )
            )
        ).all()
        assert len(rows) == 52 and {r[0] for r in rows} >= {"capital_outreach:CC-001", "capital_outreach:CC-052"}
        assert all(r[1] is None and r[2] is None and r[3] is None and r[4] is None for r in rows)
        prov = (
            await s.execute(
                text("SELECT source_ref FROM signal WHERE external_id = 'CC-002'"),
            )
        ).scalar_one()
        assert prov["url"].endswith("#sheet=12_Meris_Import&row=3")

    # the same workbook again: 52 duplicates, no new opportunities
    r = await client.post(f"/v1/sources/{src}/upload", headers=h, files=_file())
    assert (r.json()["new"], r.json()["duplicate"]) == (0, 52)
    async with session_scope() as s:
        n = (
            await s.execute(text("SELECT count(*) FROM opportunity WHERE external_key LIKE 'capital_outreach:%'"))
        ).scalar()
        assert n == 52


async def test_generic_upload_source_keeps_reading_the_first_sheet(client, make_token):
    h = {"Authorization": f"Bearer {make_token(['admin'], auth_age=5)}"}
    src = await _source_id(client, h, "csv_upload")
    r = await client.post(f"/v1/sources/{src}/upload", headers=h, files=_file())
    assert r.status_code == 200 and (r.json()["fetched"], r.json()["new"], r.json()["failed"]) == (16, 0, 16)
    r = await client.post(f"/v1/sources/{src}/upload?sheet=12_Meris_Import", headers=h, files=_file())
    assert (r.json()["fetched"], r.json()["failed"]) == (52, 52)  # no title header for the generic mapping


def _workbook_with(changes: dict[str, dict[str, object]]) -> bytes:
    """The real workbook with some 12_Meris_Import cells changed, built in memory (the file in docs/ is never re-saved)."""
    import io

    from openpyxl import load_workbook

    wb = load_workbook(WORKBOOK)
    ws = wb["12_Meris_Import"]
    header = [c.value for c in ws[1]]
    for row in ws.iter_rows(min_row=2):
        pid = row[0].value
        for col, value in changes.get(pid, {}).items():
            row[header.index(col)].value = value
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


async def _profile(pid: str) -> dict:
    async with session_scope() as s:
        r = (
            (await s.execute(text("SELECT * FROM outreach_profile WHERE prospect_id = :p"), {"p": pid}))
            .mappings()
            .one()
        )
        return dict(r)


async def test_outreach_profiles_and_human_wins_on_reimport(client, make_token):
    import time

    h = {"Authorization": f"Bearer {make_token(['admin'], auth_age=5)}"}
    src = await _source_id(client, h, "capital_outreach")
    await client.post(f"/v1/sources/{src}/upload", headers=h, files=_file())  # new or already there
    await drain_signals()
    async with session_scope() as s:
        n = (await s.execute(text("SELECT count(*) FROM outreach_profile"))).scalar()
        assert n == 52
        events = (await s.execute(text("SELECT count(*) FROM outreach_status_event"))).scalar()
        assert events == 52  # one initial event per profile
    p = await _profile("CC-002")
    assert (p["route"], p["engagement_outlook"], p["analyst_priority"], p["outreach_status"]) == (
        "Contact now", "High", 90, "Not contacted",
    )  # fmt: skip
    assert p["phones"] == ["+1 423-281-0811"] and p["verified_on"].isoformat() == "2026-10-06"
    assert (p["source_ref"]["sheet"], p["source_ref"]["row"]) == ("12_Meris_Import", 3)
    assert p["source_ref"]["official_source_url"] == p["official_source_url"]
    assert p["source_ref"]["field_sources"]["attributes.route"] == "raw:route"

    # a person works the tracker
    async with session_scope() as s:
        await s.execute(
            text(
                "UPDATE outreach_profile SET outreach_status = 'Sent', first_sent_on = DATE '2026-10-08', "
                "notes = 'called them', status_set_by = 'ana' WHERE prospect_id = 'CC-002'"
            )
        )
    # a newer workbook: CC-002's research changed, and its sheet status says something else
    marker = f"Revised ask {time.time_ns()}"
    data = _workbook_with({"CC-002": {"next_action": marker, "status": "Declined", "route": "Watch next intake"}})
    r = await client.post(f"/v1/sources/{src}/upload", headers=h, files={"file": (WORKBOOK.name, data, XLSX)})
    assert (r.json()["new"], r.json()["duplicate"]) == (1, 51)
    assert await drain_signals() == 1
    p = await _profile("CC-002")
    assert p["next_action"] == marker and p["route"] == "Watch next intake" and p["import_status"] == "Declined"
    assert (p["outreach_status"], p["notes"], p["status_set_by"]) == ("Sent", "called them", "ana")  # human wins
    assert p["first_sent_on"].isoformat() == "2026-10-08"
    async with session_scope() as s:
        n = (
            await s.execute(text("SELECT count(*) FROM opportunity WHERE external_key LIKE 'capital_outreach:%'"))
        ).scalar()
        assert n == 52  # updated in place, no duplicate opportunity


async def test_outreach_status_events_are_append_only(engine):
    from sqlalchemy.exc import DBAPIError

    for stmt in ("UPDATE outreach_status_event SET reason = 'x'", "DELETE FROM outreach_status_event",
                 "TRUNCATE outreach_status_event"):  # fmt: skip
        with pytest.raises(DBAPIError, match="append-only"):
            async with session_scope() as s:
                await s.execute(text(stmt))


def test_migration_0007_downgrades_and_upgrades(pg_url):
    import os
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "DATABASE_URL": pg_url}
    for target in ("0006_fx_rates", "head"):
        subprocess.run([sys.executable, "-m", "alembic", "downgrade" if target != "head" else "upgrade", target],
                       cwd=root, env=env, check=True)  # fmt: skip
