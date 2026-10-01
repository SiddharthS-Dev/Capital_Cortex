"""Regressions for the Phase 3 ZAP active scan and the 1M-node load test (docs/SECURITY_SCAN.md, docs/LOAD_TEST.md)."""

from __future__ import annotations

from datetime import date

import psycopg
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, field_validator
from sqlalchemy.exc import DataError

from cortex.l5_strategy.forecast_engine import DETAIL_LIMIT, Inflow, Scenario, Snapshot, forecast
from platform_core.errors import install_problem_handlers
from tests.unit.test_api import auth, client  # noqa: F401 - fixture


class _Body(BaseModel):
    n: int

    @field_validator("n")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v < 0:
            raise ValueError("must be positive")
        return v


def _app() -> TestClient:
    app = FastAPI()
    install_problem_handlers(app)

    @app.post("/v")
    async def v(body: _Body) -> dict:
        return {}

    @app.get("/nul")
    async def nul() -> dict:
        raise DataError("SELECT", {}, psycopg.DataError("PostgreSQL text fields cannot contain NUL (0x00) bytes"))

    return TestClient(app, raise_server_exceptions=False)


def test_validation_error_with_exception_context_is_a_422_problem():
    r = _app().post("/v", json={"n": -1})
    assert r.status_code == 422 and r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["errors"][0]["ctx"]["error"] == "must be positive"


def test_client_side_data_error_is_a_422():
    r = _app().get("/nul")
    assert r.status_code == 422 and r.json()["title"] == "Invalid parameter"


def test_api_sends_cross_origin_resource_policy(client):  # noqa: F811
    assert client.get("/healthz").headers["Cross-Origin-Resource-Policy"] == "same-origin"


def test_dlq_replay_rejects_malformed_ids(client, make_token):  # noqa: F811
    r = client.post("/v1/ingestion/dlq/not-an-id/replay", headers=auth(make_token(["admin"])))
    assert r.status_code == 422


def test_copilot_validates_before_streaming(client, make_token):  # noqa: F811
    h = auth(make_token(["analyst"], mfa=False))
    assert (
        client.post("/v1/copilot/ask", headers=h, json={"question": "hi there", "opportunity_id": "x"}).status_code
        == 422
    )
    assert client.post("/v1/copilot/ask", headers=h, json={"question": "a\x00b"}).status_code == 422


def test_forecast_buckets_inflows_and_caps_detail():
    snaps = [Snapshot(date(2026, 8, 1), 10_000_000, None, None, 100_000)]
    inflows = [
        Inflow(date(2026, 10, 1), 1_000 + i, 0.5, f"o{i}", f"O{i}", "grant" if i % 2 else None) for i in range(250)
    ]
    r = forecast(snaps, inflows, Scenario(), horizon=6, min_cash_buffer=0)
    oct_ = next(m for m in r.series if m["month"] == "2026-10")
    expected = sum(round((1_000 + i) * 0.5, 2) for i in range(250))
    assert oct_["inflows"] == round(expected, 2)  # the total covers every inflow
    assert len(oct_["inflow_detail"]) == DETAIL_LIMIT and oct_["inflow_detail_omitted"] == 250 - DETAIL_LIMIT
    assert oct_["inflow_detail"][0]["opportunity_id"] == "o249"  # largest first
    assert sum(oct_["inflow_by_class"].values()) == round(expected, 2)
    assert set(oct_["inflow_by_class"]) == {"grant", "unclassified"}
