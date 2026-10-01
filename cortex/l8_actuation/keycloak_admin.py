"""Keycloak admin API client for the Admin screen: users, realm roles, MFA status, role changes.

Uses the admin credentials from a secret ref (``keycloak_admin_password_ref``). Only the platform's own roles
(KNOWN_ROLES) can be granted or removed; Keycloak remains the source of truth for identities (R5, §10).
"""

from __future__ import annotations

from typing import Any

import httpx

from platform_core import secrets
from platform_core.auth.principal import KNOWN_ROLES
from platform_core.config import get_settings
from platform_core.errors import Problem, ServiceUnavailable


async def _client() -> tuple[httpx.AsyncClient, str]:
    st = get_settings()
    password = secrets.resolve(st.keycloak_admin_password_ref)
    if not password:
        raise ServiceUnavailable("Keycloak admin credentials not configured (KEYCLOAK_ADMIN_PASSWORD)")
    c = httpx.AsyncClient(base_url=st.keycloak_admin_url.rstrip("/"), timeout=15)
    r = await c.post("/realms/master/protocol/openid-connect/token",
                     data={"grant_type": "password", "client_id": "admin-cli", "username": st.keycloak_admin_user, "password": password})  # fmt: skip
    if r.status_code != 200:
        await c.aclose()
        raise ServiceUnavailable(f"Keycloak admin login failed (HTTP {r.status_code})")
    c.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
    return c, f"/admin/realms/{st.keycloak_realm}"


async def list_users(limit: int = 200) -> list[dict[str, Any]]:
    c, base = await _client()
    try:
        users = (await c.get(f"{base}/users", params={"max": limit, "briefRepresentation": "false"})).json()
        out = []
        for u in users:
            if u.get("username", "").startswith("service-account-"):
                continue
            roles = [
                r["name"]
                for r in (await c.get(f"{base}/users/{u['id']}/role-mappings/realm")).json()
                if r["name"] in KNOWN_ROLES
            ]
            creds = (await c.get(f"{base}/users/{u['id']}/credentials")).json()
            out.append({
                "id": u["id"], "username": u.get("username"), "email": u.get("email"), "name": " ".join(filter(None, [u.get("firstName"), u.get("lastName")])),
                "enabled": u.get("enabled", False), "roles": sorted(roles), "grants": (u.get("attributes") or {}).get("cortex_grants", []),
                "mfa_configured": any(cr.get("type") == "otp" for cr in creds), "required_actions": u.get("requiredActions", []),
                "created": u.get("createdTimestamp"),
            })  # fmt: skip
        return out
    finally:
        await c.aclose()


async def set_roles(user_id: str, roles: list[str]) -> dict[str, Any]:
    unknown = set(roles) - KNOWN_ROLES - {"service"}
    if unknown or "service" in roles:
        raise Problem(422, "Invalid roles", f"assignable roles: {sorted(KNOWN_ROLES - {'service'})}", "validation")
    c, base = await _client()
    try:
        cur = [
            r for r in (await c.get(f"{base}/users/{user_id}/role-mappings/realm")).json() if r["name"] in KNOWN_ROLES
        ]
        if not cur and (await c.get(f"{base}/users/{user_id}")).status_code == 404:
            raise Problem(404, "Not Found", "user not found", "not-found")
        want = set(roles)
        have = {r["name"] for r in cur}
        add = [(await c.get(f"{base}/roles/{n}")).json() for n in sorted(want - have)]
        remove = [r for r in cur if r["name"] not in want]
        if add:
            (await c.post(f"{base}/users/{user_id}/role-mappings/realm", json=add)).raise_for_status()
        if remove:
            (await c.request("DELETE", f"{base}/users/{user_id}/role-mappings/realm", json=remove)).raise_for_status()
        return {"user_id": user_id, "roles": sorted(want), "added": sorted(want - have), "removed": sorted(have - want)}
    finally:
        await c.aclose()
