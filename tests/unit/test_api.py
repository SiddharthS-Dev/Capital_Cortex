"""API tests with a fake OPA (mirrors the Rego) and no database (DB endpoints are integration-tested)."""

import pytest
from fastapi.testclient import TestClient

from cortex.l8_actuation.api.app import create_app
from cortex.l8_actuation.api.routers.phased import PLANNED
from platform_core.auth import oidc
from platform_core.auth.rbac import get_rbac
from platform_core.policy import opa
from platform_core.policy.opa import PolicyDecision


class FakeOPA:
    """Allows iff RBAC allows. The Rego-specific denies are covered by `opa test`."""

    def __init__(self):
        self.inputs = []

    async def evaluate(self, package, input_):
        self.inputs.append(input_)
        roles = input_["subject"]["roles"]
        perms = get_rbac().permissions_for(set(roles))
        ok = "*" in perms or input_["action"] in perms
        return PolicyDecision(ok, [] if ok else ["rbac"])


@pytest.fixture
def client(verifier):
    oidc.set_verifier(verifier)
    fake = FakeOPA()
    opa.set_opa(fake)  # type: ignore[arg-type]
    c = TestClient(create_app(), raise_server_exceptions=False)
    c.fake_opa = fake  # type: ignore[attr-defined]
    yield c
    oidc.set_verifier(None)
    opa.set_opa(None)


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_openapi_published(client):
    r = client.get("/v1/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    assert "/v1/audit/verify" in paths and "/v1/opportunities/{id}" in paths


def test_healthz_unauthenticated(client):
    assert client.get("/healthz").json() == {"status": "ok"}


def test_no_token_is_401_problem(client):
    r = client.get("/v1/me")
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")
    assert r.json()["title"] == "Unauthorized"


def test_me(client, make_token):
    r = client.get("/v1/me", headers=auth(make_token(["analyst"], username="ana", mfa=False)))
    assert r.status_code == 200
    body = r.json()
    assert body["roles"] == ["analyst"] and "opportunity:read" in body["permissions"]
    assert body["mfa_required"] is False and body["clearance"] == "confidential"


def test_admin_without_mfa_blocked(client, make_token):
    r = client.get("/v1/me", headers=auth(make_token(["admin"], mfa=False)))
    assert r.status_code == 403 and r.json().get("mfa_required") is True


def test_forbidden_permission(client, make_token):
    r = client.get("/v1/audit/verify", headers=auth(make_token(["analyst"])))
    assert r.status_code == 403
    assert r.json()["permission"] == "audit:verify"


def test_opa_receives_subject_and_resource(client, make_token):
    client.get("/v1/opportunities/abc", headers=auth(make_token(["analyst"])))
    inp = client.fake_opa.inputs[-1]
    assert inp["action"] == "opportunity:read"
    assert inp["resource"] == {
        "type": "opportunity",
        "id": "abc",
        "owner_id": None,
        "classification": None,
        "capital_class": None,
    }
    assert inp["context"]["method"] == "GET"


def test_every_endpoint_has_shipped():
    assert PLANNED == [], "Phase 3: every §8 endpoint is implemented"
    from cortex.phases import CURRENT_PHASE, FEATURE_PHASES

    assert CURRENT_PHASE == 3 and max(FEATURE_PHASES.values()) <= 3


def test_planned_endpoint_still_authorises(client, make_token):
    # authz runs before the 501: an executive can't reach the agent runner
    r = client.post("/v1/agents/run", headers=auth(make_token(["executive"])))
    assert r.status_code == 403


def test_step_up_on_approval_decision(client, make_token):
    stale = make_token(["approver"], auth_age=3600)
    r = client.post("/v1/approvals/x/decision", headers=auth(stale), json={"decision": "approved"})
    assert r.status_code == 403 and r.json()["step_up"] is True
    fresh = make_token(["approver"], auth_age=5)
    # past step-up and authz, the body is validated (the DB-backed decision is integration-tested)
    r = client.post("/v1/approvals/x/decision", headers=auth(fresh), json={"decision": "maybe"})
    assert r.status_code == 422


def test_step_up_on_outbox_send(client, make_token):
    r = client.post("/v1/outbox/x/send", headers=auth(make_token(["approver"], auth_age=3600)))
    assert r.status_code == 403 and r.json()["step_up"] is True


@pytest.mark.parametrize(
    ("role", "method", "path", "allowed"),
    [
        ("analyst", "POST", "/v1/agents/run", True),
        ("executive", "POST", "/v1/agents/run", False),
        ("auditor", "POST", "/v1/agents/run", False),
        ("analyst", "POST", "/v1/approvals/x/decision", False),
        ("approver", "POST", "/v1/outbox", False),
        ("analyst", "POST", "/v1/outbox/x/send", False),
        ("executive", "POST", "/v1/outcomes", False),
        ("analyst", "POST", "/v1/ml/models/train", False),
        ("approver", "POST", "/v1/meetings", False),
        ("auditor", "GET", "/v1/contacts", False),
    ],
)
def test_phase2_authz(client, make_token, role, method, path, allowed):
    r = client.request(method, path, headers=auth(make_token([role], auth_age=5)), json={})
    assert (r.status_code != 403) == allowed, (role, path, r.status_code, r.text)


@pytest.mark.parametrize("role", ["admin", "analyst", "approver", "auditor", "executive"])
def test_authz_matrix_planned_endpoints(client, make_token, role):
    """Every role x every planned endpoint: 501 iff RBAC grants the permission, else 403."""
    tok = make_token([role], auth_age=5)
    perms = get_rbac().permissions_for({role})
    for pl in PLANNED:
        path = "/v1" + pl.path.replace("{id}", "x").replace("{contact_id}", "x").replace("{name}", "executive")
        r = client.request(pl.method, path, headers=auth(tok))
        allowed = "*" in perms or pl.permission in perms
        assert r.status_code == (501 if allowed else 403), (role, pl.method, path, r.status_code, r.text)
