"""Phase 8 Test Suite: Keycloak 26 Database Migration & Verification on MySQL 8.4.

Validates that Keycloak 26 runs against MySQL 8.4 Community Edition in our
isolated test environment (port 53306 for MySQL, port 58380 for Keycloak),
verifying:
1. Liquibase schema generation in MySQL (90+ tables).
2. Declarative realm import from `realm-cortex.json`.
3. Relational persistence of users, clients, and credentials in MySQL tables.
4. OIDC discovery, JWKS keys, and OIDC token issuance.
5. Cortex TokenVerifier validation of JWT signatures, roles, and MFA claims.
6. Keycloak Admin API operations against MySQL.
"""

from __future__ import annotations

import os

import aiomysql
import httpx
import pytest

import scripts.devtoken as devtoken
import scripts.smoke as smoke
from platform_core.auth.oidc import TokenVerifier
from platform_core.config import Settings
from platform_core.db.session import get_mysql_test_url
from scripts.devtoken import token as get_user_token

KEYCLOAK_URL = os.environ.get("KEYCLOAK_TEST_URL", "http://localhost:58480")
MYSQL_URL = os.environ.get("MYSQL_KEYCLOAK_URL", get_mysql_test_url(driver="aiomysql").rsplit("/", 1)[0] + "/keycloak")


def _cred(name: str) -> str:
    """Dev-realm credentials come from the environment or .env (no committed values, SEC-1). Missing -> a clear
    failure naming the variable (not a skip): these live-Keycloak tests need them."""
    value = smoke.setting(name, required=False)
    if not value:
        pytest.fail(f"set {name} in the environment or .env to run the live Keycloak login tests")
    return value


@pytest.fixture
async def mysql_conn():
    """Direct aiomysql connection to MySQL keycloak database."""
    conn = await aiomysql.connect(
        host="127.0.0.1",
        port=53306,
        user="cortex",
        password=os.environ["MYSQL_TEST_PASSWORD"],
        db="keycloak",
        charset="utf8mb4",
    )
    try:
        yield conn
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_keycloak_schema_and_liquibase_in_mysql(mysql_conn):
    """Verify that Keycloak 26 executed Liquibase migrations and created all core tables in MySQL."""
    async with mysql_conn.cursor() as cur:
        await cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'keycloak'")
        (count,) = await cur.fetchone()
        assert count >= 80, f"Expected at least 80 Keycloak tables in MySQL, found {count}"

        # Check critical Keycloak tables
        await cur.execute("SHOW TABLES")
        rows = await cur.fetchall()
        table_names = {r[0].upper() for r in rows}
        required_tables = {
            "REALM",
            "USER_ENTITY",
            "CLIENT",
            "CREDENTIAL",
            "KEYCLOAK_ROLE",
            "DATABASECHANGELOG",
            "DATABASECHANGELOGLOCK",
        }
        for t in required_tables:
            assert t in table_names, f"Required Keycloak table {t} missing from MySQL"

        # Check Liquibase change log count
        await cur.execute("SELECT count(*) FROM DATABASECHANGELOG")
        (changesets,) = await cur.fetchone()
        assert changesets >= 100, f"Expected >= 100 Liquibase changesets, got {changesets}"


@pytest.mark.asyncio
async def test_keycloak_realm_persistence_in_mysql(mysql_conn):
    """Verify that realm 'cortex' was imported and persisted in MySQL."""
    async with mysql_conn.cursor() as cur:
        await cur.execute("SELECT id, name, enabled FROM REALM WHERE name = 'cortex'")
        realm = await cur.fetchone()
        assert realm is not None, "Realm 'cortex' not found in MySQL REALM table"
        _realm_id, realm_name, enabled = realm
        assert realm_name == "cortex"
        assert enabled == 1


@pytest.mark.asyncio
async def test_keycloak_users_persisted_in_mysql(mysql_conn):
    """Verify that pre-provisioned dev/staging users exist in MySQL USER_ENTITY table."""
    async with mysql_conn.cursor() as cur:
        await cur.execute("SELECT username, email, enabled FROM USER_ENTITY")
        users = await cur.fetchall()
        user_map = {u[0]: {"email": u[1], "enabled": u[2]} for u in users}

        expected_users = [
            "dev-analyst",
            "dev-admin",
            "dev-finance",
            "dev-approver",
            "dev-legal",
            "dev-executive",
            "smoke-auditor",
            "service-account-cortex-worker",
            "service-account-cortex-ingestion",
        ]
        for username in expected_users:
            assert username in user_map, f"User {username} not found in MySQL USER_ENTITY"
            assert user_map[username]["enabled"] == 1


@pytest.mark.asyncio
async def test_keycloak_clients_persisted_in_mysql(mysql_conn):
    """Verify that clients are properly stored in MySQL CLIENT table."""
    async with mysql_conn.cursor() as cur:
        await cur.execute("SELECT client_id, enabled FROM CLIENT WHERE client_id LIKE 'cortex%'")
        clients = await cur.fetchall()
        client_map = {c[0]: c[1] for c in clients}

        expected_clients = ["cortex-web", "cortex-api", "cortex-worker", "cortex-ingestion"]
        for cid in expected_clients:
            assert cid in client_map, f"Client {cid} not found in MySQL CLIENT table"
            assert client_map[cid] == 1


@pytest.mark.asyncio
async def test_keycloak_openid_configuration_discovery():
    """Verify OIDC well-known discovery document from Keycloak running on MySQL."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{KEYCLOAK_URL}/realms/cortex/.well-known/openid-configuration")
        assert r.status_code == 200
        data = r.json()
        assert "issuer" in data
        assert data["token_endpoint"].endswith("/protocol/openid-connect/token")
        assert data["jwks_uri"].endswith("/protocol/openid-connect/certs")


@pytest.mark.asyncio
async def test_keycloak_jwks_certs():
    """Verify JWKS certs endpoint returns valid signing keys."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(f"{KEYCLOAK_URL}/realms/cortex/protocol/openid-connect/certs")
        assert r.status_code == 200
        keys = r.json().get("keys", [])
        assert len(keys) > 0
        sig_keys = [k for k in keys if k.get("use") == "sig"]
        assert len(sig_keys) > 0
        assert any(k.get("alg") == "RS256" for k in sig_keys)


@pytest.mark.asyncio
async def test_keycloak_service_token_issuance_and_cortex_verification():
    """Verify client_credentials token issuance and Cortex TokenVerifier validation."""
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.post(
            f"{KEYCLOAK_URL}/realms/cortex/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": "cortex-worker",
                "client_secret": _cred("WORKER_CLIENT_SECRET"),
            },
        )
        assert r.status_code == 200
        tok_data = r.json()
        assert "access_token" in tok_data
        token = tok_data["access_token"]

        # Validate token using Cortex's own TokenVerifier
        settings = Settings(
            oidc_issuer=f"{KEYCLOAK_URL}/realms/cortex",
            jwks_url=f"{KEYCLOAK_URL}/realms/cortex/protocol/openid-connect/certs",
            oidc_audience="cortex-api",
        )
        verifier = TokenVerifier(settings=settings)
        principal = await verifier.verify(token)

        assert principal.username == "service-account-cortex-worker"
        assert principal.is_service is True
        assert "service" in principal.roles


@pytest.mark.asyncio
async def test_keycloak_human_user_auth_code_pkce_token():
    """Verify authorization code + PKCE login for dev-analyst user and token verification."""
    os.environ["KEYCLOAK"] = KEYCLOAK_URL
    smoke.KC = KEYCLOAK_URL
    smoke.REALM = f"{KEYCLOAK_URL}/realms/cortex"
    devtoken.REALM = f"{KEYCLOAK_URL}/realms/cortex"
    token = get_user_token("dev-analyst", _cred("SMOKE_USER_PASSWORD"))
    assert token and len(token) > 100

    settings = Settings(
        oidc_issuer=f"{KEYCLOAK_URL}/realms/cortex",
        jwks_url=f"{KEYCLOAK_URL}/realms/cortex/protocol/openid-connect/certs",
        oidc_audience="cortex-api",
    )
    verifier = TokenVerifier(settings=settings)
    principal = await verifier.verify(token)

    assert principal.username == "dev-analyst"
    assert principal.is_service is False
    assert "analyst" in principal.roles
    assert principal.email == "dev-analyst@cortex.local"


@pytest.mark.asyncio
async def test_keycloak_mfa_user_totp_token():
    """Verify MFA (TOTP) login for smoke-auditor user and token verification."""
    os.environ["KEYCLOAK"] = KEYCLOAK_URL
    smoke.KC = KEYCLOAK_URL
    smoke.REALM = f"{KEYCLOAK_URL}/realms/cortex"
    devtoken.REALM = f"{KEYCLOAK_URL}/realms/cortex"
    token = get_user_token("smoke-auditor", _cred("SMOKE_USER_PASSWORD"), _cred("SMOKE_TOTP_SECRET"))
    assert token and len(token) > 100

    settings = Settings(
        oidc_issuer=f"{KEYCLOAK_URL}/realms/cortex",
        jwks_url=f"{KEYCLOAK_URL}/realms/cortex/protocol/openid-connect/certs",
        oidc_audience="cortex-api",
    )
    verifier = TokenVerifier(settings=settings)
    principal = await verifier.verify(token)

    assert principal.username == "smoke-auditor"
    assert "auditor" in principal.roles
    assert principal.email == "smoke-auditor@cortex.local"
    assert "otp" in principal.amr
    assert "pwd" in principal.amr


@pytest.mark.asyncio
async def test_keycloak_admin_api_operations():
    """Verify Keycloak Admin REST API operations against master realm on MySQL."""
    async with httpx.AsyncClient(timeout=10) as client:
        # Get admin token
        tok_res = await client.post(
            f"{KEYCLOAK_URL}/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": os.environ.get("KEYCLOAK_ADMIN", "kcadmin"),
                "password": os.environ["KEYCLOAK_ADMIN_PASSWORD"],
            },
        )
        assert tok_res.status_code == 200
        admin_token = tok_res.json()["access_token"]

        # Query users in cortex realm
        users_res = await client.get(
            f"{KEYCLOAK_URL}/admin/realms/cortex/users",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert users_res.status_code == 200
        users = users_res.json()
        assert len(users) >= 7
        usernames = [u["username"] for u in users]
        assert "dev-analyst" in usernames
        assert "dev-admin" in usernames
