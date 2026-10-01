"""OIDC access-token verification against the IdP's JWKS (Keycloak).

Services never trust upstream checks (I4): API endpoints and worker jobs both call ``verify``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import jwt
from jwt import PyJWKClient

from platform_core.auth.principal import KNOWN_ROLES, Principal
from platform_core.config import Settings, get_settings
from platform_core.errors import Unauthorized

log = logging.getLogger(__name__)

ALLOWED_ALGS = ["RS256", "RS384", "RS512", "ES256", "PS256"]


class TokenVerifier:
    def __init__(self, settings: Settings | None = None, jwk_client: PyJWKClient | None = None) -> None:
        self.settings = settings or get_settings()
        self._jwks = jwk_client or PyJWKClient(self.settings.jwks_url, cache_keys=True, lifespan=3600)

    def _decode(self, token: str) -> dict[str, Any]:
        try:
            key = self._jwks.get_signing_key_from_jwt(token)
            return jwt.decode(
                token,
                key.key,
                algorithms=ALLOWED_ALGS,
                audience=self.settings.oidc_audience,
                issuer=self.settings.oidc_issuer,
                leeway=30,
                options={"require": ["exp", "iat", "iss", "sub"]},
            )
        except jwt.PyJWKClientError as e:
            log.warning("jwks lookup failed: %s", e)
            raise Unauthorized("Unable to validate token signing key") from e
        except jwt.InvalidTokenError as e:
            raise Unauthorized(f"Invalid token: {e}") from e

    def principal_from_claims(self, claims: dict[str, Any], token: str = "") -> Principal:
        realm_roles = set(claims.get("realm_access", {}).get("roles", []))
        roles = frozenset(r for r in realm_roles if r in KNOWN_ROLES)
        grants = frozenset(claims.get("cortex_grants", []) or [])
        client_id = claims.get("azp") or claims.get("client_id")
        username = claims.get("preferred_username") or claims.get("sub", "")
        is_service = "service" in roles or username.startswith("service-account-")
        amr = claims.get("amr") or []
        if isinstance(amr, str):
            amr = [amr]
        return Principal(
            sub=claims["sub"],
            username=username,
            roles=roles,
            grants=grants,
            email=claims.get("email"),
            name=claims.get("name"),
            client_id=client_id,
            is_service=is_service,
            amr=tuple(amr),
            acr=str(claims["acr"]) if claims.get("acr") is not None else None,
            auth_time=claims.get("auth_time"),
            token=token,
            claims=claims,
            mfa_acr_values=tuple(self.settings.oidc_mfa_acr_values),
        )

    def verify_sync(self, token: str) -> Principal:
        if not token:
            raise Unauthorized()
        return self.principal_from_claims(self._decode(token), token)

    async def verify(self, token: str) -> Principal:
        # PyJWKClient does blocking I/O on a cache miss; keep it off the event loop.
        return await asyncio.to_thread(self.verify_sync, token)


_verifier: TokenVerifier | None = None


def get_verifier() -> TokenVerifier:
    global _verifier
    if _verifier is None:
        _verifier = TokenVerifier()
    return _verifier


def set_verifier(v: TokenVerifier | None) -> None:
    """Test hook."""
    global _verifier
    _verifier = v


class ServiceTokenProvider:
    """Client-credentials token for worker/service accounts, refreshed before expiry."""

    def __init__(self, token_url: str, client_id: str, client_secret: str) -> None:
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self._token: str | None = None
        self._exp: float = 0.0
        self._lock = asyncio.Lock()

    async def get(self) -> str:
        async with self._lock:
            if self._token and time.time() < self._exp - 30:
                return self._token
            import httpx

            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(
                    self.token_url,
                    data={"grant_type": "client_credentials"},
                    auth=(self.client_id, self.client_secret),
                )
                r.raise_for_status()
                body = r.json()
            self._token = body["access_token"]
            self._exp = time.time() + float(body.get("expires_in", 300))
            return self._token
