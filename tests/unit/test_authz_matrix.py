"""§14 security: authorisation matrix, every role × every endpoint.

Each route declares its permission through its ``authorize(...)`` dependency. For every role the API must answer
403 exactly when RBAC denies that permission (the Rego mirrors RBAC and adds narrower denies that are covered by
``opa test``). Allowed requests may still fail later (no database here, or a validation error), but never 403.
"""

import re

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from cortex.l8_actuation.api.app import create_app
from platform_core.auth import oidc
from platform_core.auth.rbac import get_rbac
from platform_core.policy import opa
from platform_core.policy.opa import PolicyDecision

ROLES = ["admin", "analyst", "approver", "auditor", "executive"]
UUID = "11111111-1111-1111-1111-111111111111"
PUBLIC = {"/v1/share/{token}"}  # capability URL for external recipients (never a user, R10)


class RbacOPA:
    async def evaluate(self, package, input_):
        perms = get_rbac().permissions_for(set(input_["subject"]["roles"])) | set(input_["subject"].get("grants") or [])
        ok = (
            "*" in perms
            or input_["action"] in perms
            or any(p.endswith(":*") and input_["action"].startswith(p[:-1]) for p in perms)
        )
        return PolicyDecision(ok, [] if ok else ["rbac"])


def _permission(route: APIRoute) -> str | None:
    for dep in route.dependant.dependencies:
        perm = getattr(dep.call, "permission", None)
        if perm:
            return str(perm)
    return None


def _walk(routes: list) -> list[APIRoute]:
    """Newer FastAPI wraps included routers (``_IncludedRouter.original_router``): walk them recursively."""
    out: list[APIRoute] = []
    for r in routes:
        if isinstance(r, APIRoute):
            out.append(r)
        elif getattr(r, "original_router", None) is not None:
            out += _walk(r.original_router.routes)
    return out


def _routes() -> list[tuple[str, str, str | None]]:
    out = []
    for r in _walk(create_app().routes):
        if r.path.startswith("/v1") and r.path != "/v1/openapi.json":
            for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
                out.append((m, r.path, _permission(r)))
    return sorted(set(out))


ROUTES = _routes()


def test_matrix_covers_the_whole_api():
    assert len(ROUTES) >= 120, len(ROUTES)


def test_every_endpoint_is_authorised_or_explicitly_public():
    unprotected = [
        (m, p) for m, p, perm in ROUTES if perm is None and p not in PUBLIC and p not in ("/v1/me", "/v1/meta")
    ]
    assert not unprotected, unprotected


@pytest.fixture(scope="module")
def client(verifier):
    oidc.set_verifier(verifier)
    opa.set_opa(RbacOPA())  # type: ignore[arg-type]
    c = TestClient(create_app(), raise_server_exceptions=False)
    yield c
    oidc.set_verifier(None)
    opa.set_opa(None)


@pytest.mark.parametrize("role", ROLES)
def test_role_by_endpoint_matrix(client, make_token, role):
    tok = make_token([role], auth_age=5)
    perms = get_rbac().permissions_for({role})
    wrong = []
    for method, path, perm in ROUTES:
        if perm is None or path.endswith("/stream") or path == "/v1/copilot/ask" or path == "/v1/events/stream":
            continue  # SSE routes are authorised the same way; streaming them here would block
        url = re.sub(r"{[^}]+}", UUID, path).replace(UUID + "/export", UUID + "/export")
        r = client.request(
            method, url, headers={"Authorization": f"Bearer {tok}"}, json={}, params={"fmt": "pdf", "artefact": "x"}
        )
        allowed = "*" in perms or perm in perms or any(p.endswith(":*") and perm.startswith(p[:-1]) for p in perms)
        if (r.status_code == 403) == allowed and not (allowed and r.json().get("step_up")):
            wrong.append((method, path, perm, r.status_code))
    assert not wrong, wrong


def test_unauthenticated_requests_are_rejected(client):
    for method, path, perm in ROUTES:
        if perm is None or path.endswith("/stream"):
            continue
        r = client.request(method, re.sub(r"{[^}]+}", UUID, path))
        assert r.status_code == 401, (method, path, r.status_code)


def test_sessions_commit_before_the_response():
    """Every DB-backed route uses get_session with scope="function" (commit before the 2xx is sent)."""
    from platform_core.db import get_session

    bad = []
    for r in _walk(create_app().routes):
        for d in r.dependant.dependencies:
            if d.call is get_session and getattr(d, "scope", None) != "function":
                bad.append(r.path)
    assert not bad, bad
