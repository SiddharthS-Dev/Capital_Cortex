"""Security controls (SECURITY report §13): authentication edge cases, authorization denials and their events, tenant
context, request limits, rate limiting, headers, redaction, download headers, webhook destinations, package clearance.

Everything runs without a database: routes used here are DB-free, and the rate limiter uses fakeredis.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import fakeredis.aioredis
import jwt
import pytest
from fastapi.testclient import TestClient

from cortex.l7_governance import settings_service
from cortex.l7_governance.outbox import webhook_destination_allowed
from cortex.l8_actuation import dataroom as dataroom_svc
from cortex.l8_actuation.api import app as app_module
from platform_core import security
from platform_core.auth import oidc
from platform_core.auth.principal import Principal
from platform_core.config import Settings, get_settings
from platform_core.errors import Forbidden, Problem, Unauthorized
from platform_core.policy import opa
from tests.unit.test_authz_matrix import RbacOPA

ROOT = Path(__file__).resolve().parents[2]
ISSUER = get_settings().oidc_issuer


@pytest.fixture
def client(verifier):
    oidc.set_verifier(verifier)
    opa.set_opa(RbacOPA())  # type: ignore[arg-type]
    fake = fakeredis.aioredis.FakeRedis()
    security.set_rate_limiter(security.RateLimiter(lambda: fake))
    with TestClient(app_module.create_app(), raise_server_exceptions=False) as c:
        yield c
    oidc.set_verifier(None)
    opa.set_opa(None)
    security.set_rate_limiter(security.RateLimiter())


def _bearer(tok: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {tok}"}


def _events(caplog) -> list[dict]:
    return [json.loads(r.getMessage().split(" ", 1)[1]) for r in caplog.records if r.name == "cortex.security"]


# ---------------------------------------------------------------- authentication


def test_missing_token_is_401_and_logged(client, caplog):
    caplog.set_level(logging.INFO, logger="cortex.security")
    r = client.get("/v1/me")
    assert r.status_code == 401 and r.headers["content-type"].startswith("application/problem+json")
    assert [e["action"] for e in _events(caplog)] == ["authn.token_missing"]


@pytest.mark.parametrize("token", ["not-a-jwt", "a.b.c", "eyJhbGciOiJub25lIn0.eyJzdWIiOiJ4In0."])
def test_malformed_and_unsigned_tokens_are_401(client, token):
    assert client.get("/v1/me", headers=_bearer(token)).status_code == 401


def test_alg_none_token_rejected_by_verifier(verifier):
    now = int(time.time())
    claims = {"iss": ISSUER, "aud": "cortex-api", "sub": "x", "iat": now, "exp": now + 60}
    unsigned = jwt.encode(claims, key=None, algorithm="none")
    with pytest.raises(Unauthorized):
        verifier.verify_sync(unsigned)


def test_not_yet_valid_and_missing_exp_tokens_rejected(make_token, rsa_key, verifier):
    with pytest.raises(Unauthorized):
        verifier.verify_sync(make_token(["analyst"], nbf=int(time.time()) + 3600))
    now = int(time.time())
    no_exp = jwt.encode({"iss": ISSUER, "aud": "cortex-api", "sub": "x", "iat": now}, rsa_key, algorithm="RS256")
    with pytest.raises(Unauthorized):
        verifier.verify_sync(no_exp)


def test_rejection_reason_is_not_returned_to_the_client(client, make_token, caplog):
    caplog.set_level(logging.INFO, logger="cortex.security")
    r = client.get("/v1/me", headers=_bearer(make_token(["analyst"], ttl=-120)))  # expired beyond leeway
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid or expired token"  # no "Signature has expired" / audience hints
    assert [e["action"] for e in _events(caplog)] == ["authn.token_rejected"]


def test_unknown_roles_and_request_payload_grant_nothing(client, make_token):
    tok = make_token(["superadmin", "root"], mfa=True)
    me = client.get("/v1/me", headers=_bearer(tok)).json()
    assert me["roles"] == [] and me["permissions"] == []
    # identity comes from the verified token only: a spoofed header/query changes nothing
    spoof = client.get("/v1/me?roles=admin&org_id=other", headers={**_bearer(tok), "X-Roles": "admin", "X-Org-Id": "x"})
    assert spoof.json()["roles"] == []


# ---------------------------------------------------------------- authorization


def test_missing_permission_is_403_and_logged(client, make_token, caplog):
    caplog.set_level(logging.INFO, logger="cortex.security")
    r = client.get("/v1/system/ping/abc", headers=_bearer(make_token(["analyst"], mfa=False)))
    assert r.status_code == 403
    events = _events(caplog)
    assert [e["action"] for e in events] == ["authz.permission_denied"]
    assert events[0]["reason"] == "system:ping" and events[0]["actor"] and events[0]["request_id"]


def test_privileged_role_without_mfa_is_refused(client, make_token, caplog):
    caplog.set_level(logging.INFO, logger="cortex.security")
    r = client.get("/v1/me", headers=_bearer(make_token(["admin"], mfa=False)))
    assert r.status_code == 403 and r.json().get("mfa_required") is True
    assert [e["action"] for e in _events(caplog)] == ["authn.mfa_required"]


def test_service_client_scope_limits_a_stolen_service_token():
    from platform_core.auth.rbac import get_rbac

    svc = Principal(sub="s", username="service-account-x", roles=frozenset({"service"}), client_id="unknown-client",
                    is_service=True)  # fmt: skip
    assert not get_rbac().allows(svc, "opportunity:read")  # unknown service clients get nothing


# ---------------------------------------------------------------- tenant context (single-tenant by design, R9)


def test_no_endpoint_accepts_a_tenant_identifier(client):
    """The org comes from server configuration only; no API parameter or body field can name a tenant."""
    spec = client.get("/v1/openapi.json").json()
    tenantish = re.compile(r"^(org|org_id|tenant|tenant_id|orgid)$", re.I)
    found = []
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            for prm in op.get("parameters", []):
                if tenantish.match(prm["name"]):
                    found.append(f"{method.upper()} {path} param {prm['name']}")
    for name, schema in spec.get("components", {}).get("schemas", {}).items():
        for prop in schema.get("properties") or {}:
            if tenantish.match(prop) and not name.endswith(("Out", "Response", "Detail", "Row", "Item")):
                found.append(f"schema {name}.{prop}")
    assert found == []


def test_router_queries_take_org_from_settings_only():
    routers = (ROOT / "cortex" / "l8_actuation" / "api" / "routers").glob("*.py")
    bad = []
    for path in routers:
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r'["\']org["\']\s*:\s*([^,}\n]+)', text):
            # `params["org"]` re-uses a dict built from get_settings().org_id in the same handler
            if "get_settings().org_id" not in m.group(1) and m.group(1).strip() not in ("org", 'params["org"]'):
                bad.append(f"{path.name}: {m.group(1).strip()[:60]}")
    assert bad == []


# ---------------------------------------------------------------- request limits, ids and headers


def test_oversized_body_is_413_before_any_handler(client):
    big = b"x" * (get_settings().max_request_bytes + 1)
    r = client.post("/v1/system/ping", content=big, headers={"Content-Type": "application/json"})
    assert r.status_code == 413 and r.json()["status"] == 413


async def test_oversized_chunked_body_is_413_when_read():
    """No Content-Length (chunked): the limit applies to the bytes a handler actually reads."""

    async def reader(scope, receive, send):
        while (await receive()).get("more_body"):
            pass
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    mw = security.BodySizeLimitMiddleware(reader, max_bytes=10, max_multipart_bytes=10)
    chunks = [{"type": "http.request", "body": b"x" * 6, "more_body": True}] * 3
    sent: list[dict] = []

    async def receive():
        return chunks.pop(0) if chunks else {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    await mw({"type": "http", "path": "/v1/x", "headers": []}, receive, send)
    assert sent[0]["status"] == 413


def test_invalid_content_length_is_400(client):
    r = client.post(
        "/v1/system/ping", content=b"{}", headers={"Content-Type": "application/json", "Content-Length": "x"}
    )
    assert r.status_code in (400, 413)


def test_request_id_is_generated_echoed_and_in_problem_bodies(client):
    r = client.get("/v1/me")
    rid = r.headers["x-request-id"]
    assert re.fullmatch(r"[0-9a-f]{32}", rid) and r.json()["request_id"] == rid
    given = client.get("/v1/me", headers={"X-Request-ID": "trace-abc-12345"})
    assert given.headers["x-request-id"] == "trace-abc-12345"
    hostile = client.get("/v1/me", headers={"X-Request-ID": "bad\r\nvalue<script>"})
    assert hostile.headers["x-request-id"] != "bad\r\nvalue<script>"


def test_security_headers_on_api_responses(client):
    h = client.get("/healthz").headers
    assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
    assert h["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert h["cache-control"] == "no-store" and "strict-transport-security" not in h  # plain-HTTP dev/test


def test_production_sends_hsts_and_hides_docs(monkeypatch):
    prod = Settings(env="prod", database_url="mysql+asyncmy://u@db/cortex")
    monkeypatch.setattr(app_module, "get_settings", lambda: prod)
    monkeypatch.setattr(app_module, "setup_otel", lambda s: None)
    with TestClient(app_module.create_app(), raise_server_exceptions=False) as c:
        h = c.get("/healthz").headers
        assert h["strict-transport-security"].startswith("max-age=31536000")
        assert c.get("/v1/docs").status_code == 404 and c.get("/v1/openapi.json").status_code == 404


def test_cors_rejects_unknown_origins(client):
    r = client.options("/v1/me", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert "access-control-allow-origin" not in r.headers


# ---------------------------------------------------------------- rate limiting


async def test_rate_limiter_counts_per_bucket_and_window():
    fake = fakeredis.aioredis.FakeRedis()
    limiter = security.RateLimiter(lambda: fake)
    results = [(await limiter.hit("t:alice", 3, 60))[0] for _ in range(5)]
    assert results == [True, True, True, False, False]
    assert (await limiter.hit("t:bob", 3, 60))[0] is True  # another principal has its own budget


async def test_rate_limiter_falls_back_locally_when_redis_fails():
    def broken():
        raise ConnectionError("redis down")

    limiter = security.RateLimiter(broken)
    results = [(await limiter.hit("t:x", 2, 60))[0] for _ in range(3)]
    assert results == [True, True, False]  # still limits, never raises


async def test_enforce_rate_limit_raises_429_and_logs(caplog, monkeypatch):
    caplog.set_level(logging.INFO, logger="cortex.security")
    fake = fakeredis.aioredis.FakeRedis()
    security.set_rate_limiter(security.RateLimiter(lambda: fake))
    try:
        await security.enforce_rate_limit("share_link", "tokhash", 1, 60)
        with pytest.raises(Problem) as e:
            await security.enforce_rate_limit("share_link", "tokhash", 1, 60)
        assert e.value.status == 429 and e.value.extra["retry_after"] > 0
        assert [ev["action"] for ev in _events(caplog)] == ["rate_limit.exceeded"]
    finally:
        security.set_rate_limiter(security.RateLimiter())


def test_costly_routes_carry_a_rate_limit():
    from cortex.l8_actuation.api.routers import board_reports, copilot, dataroom, graph, proposals, sources

    limited = set()
    for mod in (board_reports, copilot, dataroom, graph, proposals, sources):
        for r in mod.router.routes:
            if any(getattr(d.call, "__name__", "").startswith("rate_limit_") for d in r.dependant.dependencies):
                limited.add((sorted(r.methods)[0], r.path))
    for expected in [
        ("POST", "/v1/copilot/ask"), ("GET", "/v1/board-reports/{id}/export"), ("POST", "/v1/board-reports"),
        ("GET", "/v1/proposals/{id}/export"), ("POST", "/v1/proposals"), ("POST", "/v1/proposals/{id}/generate"),
        ("POST", "/v1/dataroom/documents"), ("GET", "/v1/graph/paths"), ("POST", "/v1/sources/{id}/upload"),
    ]:  # fmt: skip
        assert expected in limited, (expected, sorted(limited))


# ---------------------------------------------------------------- secrets and logs


def test_log_redaction_masks_tokens_and_passwords(caplog):
    security.install_log_redaction()
    caplog.set_level(logging.INFO)
    lg = logging.getLogger("cortex.test.redaction")
    lg.info("auth header Bearer abc.def.ghi and password=hunter2 client_secret: s3cr3t")
    lg.info("dsn mysql+asyncmy://cortex:pw-test-only@db:3306/cortex token=%s", "eyJhbGciOi.eyJzdWIiOi.c2lnbmF0dXJl")
    text = "\n".join(r.getMessage() for r in caplog.records if r.name == "cortex.test.redaction")
    for leaked in ("abc.def.ghi", "hunter2", "s3cr3t", "pw-test-only", "eyJhbGciOi.eyJzdWIiOi.c2lnbmF0dXJl"):
        assert leaked not in text, leaked
    assert "[REDACTED]" in text


def test_security_event_drops_secret_attributes(caplog):
    caplog.set_level(logging.INFO, logger="cortex.security")
    event = security.security_event("x", "denied", client_secret="leak", access_token="leak", note="kept")
    assert "client_secret" not in event and "access_token" not in event and event["note"] == "kept"
    assert "leak" not in caplog.text


def test_internal_errors_do_not_leak_exception_text(client, monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("password=secret-test-only at db-host-internal")

    monkeypatch.setattr(oidc.TokenVerifier, "verify", boom)
    r = client.get("/v1/me", headers=_bearer("x"))
    assert r.status_code == 500 and "secret-test-only" not in r.text and "db-host-internal" not in r.text


# ---------------------------------------------------------------- downloads


@pytest.mark.parametrize(
    "name",
    ['a"; filename*=evil.html', "x\r\nSet-Cookie: s=1", "../../etc/passwd", "rapport-é.pdf", "", "a\\b;c:d"],
)
def test_content_disposition_cannot_inject_parameters(name):
    header = security.content_disposition(name, "document")
    quoted = header.split('filename="', 1)[1].split('"', 1)[0]
    assert not set(quoted) & set('"\\/;:\r\n') and "\r" not in header and "\n" not in header
    assert header.count('filename="') == 1 and header.startswith("attachment; ")


@pytest.mark.parametrize(
    ("given", "served"),
    [("application/pdf", "application/pdf"), ("text/html", "application/octet-stream"),
     ("image/svg+xml", "application/octet-stream"), ("TEXT/PLAIN; charset=utf-8", "text/plain"), (None, "application/octet-stream")],
)  # fmt: skip
def test_uploads_are_served_with_allow_listed_types(given, served):
    assert security.safe_media_type(given) == served


# ---------------------------------------------------------------- webhook destinations (SSRF / exfiltration)


@pytest.mark.parametrize(
    ("url", "ok"),
    [
        ("https://hooks.corp.com/x", True),
        ("https://hooks.corp.com.evil.net/x", False),
        ("https://hooks.corp.com@evil.net/", False),
        ("https://user:pw@hooks.corp.com/x", False),
        ("http://hooks.corp.com/x", False),
        ("https://hooks.corp.com:8443/x", False),
        ("https://api.partner.io/inbound/a", True),
        ("https://api.partner.io/inboundX", False),
        ("https://api.partner.io/other", False),
        ("https://hooks.corp.com:99999/x", False),
    ],
)
def test_webhook_destinations_match_host_and_path_exactly(url, ok):
    assert webhook_destination_allowed(url, ["https://hooks.corp.com", "https://api.partner.io/inbound/"]) is ok


@pytest.mark.parametrize("entry", ["http://x.io/", "https://u:p@x.io/", "https://x.io/?a=1", "https:///nohost", "x.io"])
def test_admin_cannot_store_an_unsafe_webhook_allowlist(entry):
    with pytest.raises(Problem):
        settings_service.validate("governance", {"webhook_allowlist": [entry]})


# ---------------------------------------------------------------- data room clearance


def _principal(*roles: str) -> Principal:
    return Principal(sub="u1", username="u1", roles=frozenset(roles))


def test_package_inherits_its_most_restricted_document():
    pkg = {"manifest": {"files": [{"classification": "internal"}, {"classification": "restricted"}]}}
    with pytest.raises(Forbidden):
        dataroom_svc.assert_package_clearance(_principal("analyst"), pkg)
    dataroom_svc.assert_package_clearance(_principal("admin"), pkg)  # cleared: no exception
    with pytest.raises(Forbidden):  # an unrecorded classification counts as restricted
        dataroom_svc.assert_package_clearance(_principal("analyst"), {"manifest": {"files": [{}]}})


# ---------------------------------------------------------------- database privileges (prepared, not applied)


def test_runtime_account_script_grants_no_ddl_and_keeps_audit_append_only():
    sql = (ROOT / "infra" / "mysql" / "runtime_account.sql").read_text(encoding="utf-8")
    code = "\n".join(ln for ln in sql.splitlines() if not ln.strip().startswith("--"))
    assert not re.search(
        r"\b(DROP|ALTER|INDEX|TRIGGER|REFERENCES|SUPER|ALL PRIVILEGES)\b", code.replace("DROP USER", "")
    )
    assert "IF(table_name = 'audit_log', '', ', UPDATE, DELETE')" in code  # audit_log: SELECT, INSERT only
    assert "IDENTIFIED BY '<from the secret store>'" in sql and "NOT APPLIED" in sql
