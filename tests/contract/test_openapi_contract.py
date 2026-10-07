"""Contract tests (schemathesis) against the in-process ASGI app.

Every documented operation is fuzzed with a valid analyst token and a permissive fake OPA. Responses must
match the declared status codes, content types and schemas. DB-backed endpoints are excluded here; they
run against the live stack in CI (`make contract-live`).
"""

from __future__ import annotations

import pytest
import schemathesis
from hypothesis import HealthCheck, settings
from schemathesis.specs.openapi.checks import (
    content_type_conformance,
    response_schema_conformance,
    status_code_conformance,
)

from cortex.l8_actuation.api.app import create_app
from platform_core.auth import oidc
from platform_core.policy import opa
from platform_core.policy.opa import PolicyDecision

pytestmark = pytest.mark.contract

DB_BACKED = (
    "/v1/meta",
    "/v1/audit",
    "/v1/approvals",
    "/v1/system/ping",
    "/v1/admin",
    "/v1/ingestion/dlq",
    "/v1/opportunities",
    "/v1/scoring",
    "/v1/graph",
    "/v1/entities",
    "/v1/sources",
    "/v1/signals",
    "/v1/dashboards",
    "/v1/forecasts",
    "/v1/organization",
    "/v1/events",
    # Phase 2 (exercised in tests/integration/test_phase2_flow.py)
    "/v1/contacts",
    "/v1/meetings",
    "/v1/interactions",
    "/v1/relationships",
    "/v1/milestones",
    "/v1/recall",
    "/v1/organizations",
    "/v1/agents",
    "/v1/recommendations",
    "/v1/outbox",
    "/v1/alerts",
    "/v1/alert-rules",
    "/v1/outcomes",
    "/v1/ml",
    "/v1/calendar",
    # Phase 3 (exercised in tests/integration/test_phase3_flow.py)
    "/v1/proposals",
    "/v1/dataroom",
    "/v1/share",
    "/v1/board-reports",
    "/v1/copilot",
    "/v1/legal-holds",
    # Capital outreach register (exercised in tests/integration/test_outreach_flow.py)
    "/v1/outreach",
    "/v1/eligibility-gates",
)  # exercised against a real database in tests/integration/test_api_flow.py


class AllowOPA:
    async def evaluate(self, package, input_):
        return PolicyDecision(True, [])


app = create_app()
schema = schemathesis.openapi.from_asgi("/v1/openapi.json", app)


@pytest.fixture(autouse=True)
def _auth(verifier):
    oidc.set_verifier(verifier)
    opa.set_opa(AllowOPA())  # type: ignore[arg-type]
    yield
    oidc.set_verifier(None)
    opa.set_opa(None)


@schema.exclude(path_regex="|".join(f"^{p}" for p in DB_BACKED)).parametrize()
@settings(max_examples=5, suppress_health_check=list(HealthCheck), deadline=None)
def test_api_contract(case, make_token):
    token = make_token(["admin", "approver"], auth_age=5)
    case.call_and_validate(
        headers={"Authorization": f"Bearer {token}"},
        checks=[status_code_conformance, content_type_conformance, response_schema_conformance],
    )
