from __future__ import annotations

import os
import time
import uuid
from typing import Any

os.environ.setdefault("ENV", "test")
os.environ.setdefault("OIDC_ISSUER", "https://idp.test/realms/cortex")
os.environ.setdefault("OIDC_AUDIENCE", "cortex-api")


def _load_test_db_env() -> None:
    """MYSQL_TEST_* and KEYCLOAK_ADMIN* come from the (git-ignored) .env when the shell doesn't set them: no credential
    is committed in code any more (get_mysql_test_url requires MYSQL_TEST_PASSWORD; the Keycloak admin test requires
    KEYCLOAK_ADMIN_PASSWORD). Values are never printed."""
    from pathlib import Path

    env_file = Path(__file__).resolve().parents[1] / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        key = key.strip()
        if sep and key.startswith(("MYSQL_TEST_", "KEYCLOAK_ADMIN")) and value.strip():
            os.environ.setdefault(key, value.strip().strip('"'))


_load_test_db_env()

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from platform_core.auth.oidc import TokenVerifier
from platform_core.config import get_settings

ISSUER = os.environ["OIDC_ISSUER"]


class _Key:
    def __init__(self, key: Any) -> None:
        self.key = key


class StaticJWKClient:
    """Stand-in for PyJWKClient that returns a fixed public key."""

    def __init__(self, public_key: Any) -> None:
        self._k = _Key(public_key)

    def get_signing_key_from_jwt(self, token: str) -> _Key:
        return self._k


@pytest.fixture(scope="session")
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="session")
def verifier(rsa_key) -> TokenVerifier:
    return TokenVerifier(get_settings(), StaticJWKClient(rsa_key.public_key()))


@pytest.fixture(scope="session")
def make_token(rsa_key):
    def _make(
        roles: list[str],
        *,
        mfa: bool = True,
        auth_age: int = 10,
        sub: str | None = None,
        azp: str = "cortex-web",
        username: str = "alice",
        ttl: int = 900,
        **extra: Any,
    ) -> str:
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": ["cortex-api", "account"],
            "sub": sub or str(uuid.uuid4()),
            "iat": now,
            "exp": now + ttl,
            "auth_time": now - auth_age,
            "azp": azp,
            "preferred_username": username,
            "realm_access": {"roles": [*roles, "offline_access", "default-roles-cortex"]},
            "amr": ["pwd", "otp"] if mfa else ["pwd"],
            **extra,
        }
        return jwt.encode(claims, rsa_key, algorithm="RS256")

    return _make


if os.name == "nt":
    # psycopg async can't use the Windows ProactorEventLoop.
    import asyncio

    @pytest.fixture(scope="session")
    def event_loop_policy():
        return asyncio.WindowsSelectorEventLoopPolicy()
