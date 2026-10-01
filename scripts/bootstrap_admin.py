"""Create or update the platform administrator in the Keycloak `cortex` realm (idempotent).

Reads CORTEX_ADMIN_EMAIL / CORTEX_ADMIN_PASSWORD from the environment or from `.env` (gitignored), so the real
credential never lands in the committed realm export. The user gets the realm roles admin + approver (the
Founder mapping, R10). With CORTEX_MFA_REQUIRED unset/true, admin requires MFA (R5) and the user enrols TOTP at
first login. With CORTEX_MFA_REQUIRED=false (local development only), OTP is skipped (D-033).

Usage: python scripts/bootstrap_admin.py   (runs as part of `make up`)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    env.update({k: v for k, v in os.environ.items() if k.startswith(("CORTEX_", "KEYCLOAK"))})
    return env


def main() -> int:
    env = load_env()
    email, password = env.get("CORTEX_ADMIN_EMAIL", ""), env.get("CORTEX_ADMIN_PASSWORD", "")
    if not email or not password:
        print("bootstrap_admin: CORTEX_ADMIN_EMAIL/CORTEX_ADMIN_PASSWORD not set; skipping")
        return 0
    kc = f"http://localhost:{env.get('KEYCLOAK_PORT', '8380')}"
    with httpx.Client(base_url=kc, timeout=20) as c:
        tok = c.post(
            "/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": env.get("KEYCLOAK_ADMIN", "kcadmin"),
                "password": env.get("KEYCLOAK_ADMIN_PASSWORD", "kcadmin-dev-pw"),
            },
        )
        tok.raise_for_status()
        c.headers["Authorization"] = f"Bearer {tok.json()['access_token']}"
        base = "/admin/realms/cortex"

        found = c.get(f"{base}/users", params={"email": email, "exact": "true"}).json()
        user = {
            "username": email,
            "email": email,
            "emailVerified": True,
            "enabled": True,
            "firstName": "Inspironics",
            "lastName": "Admin",
        }
        if found:
            uid = found[0]["id"]
            c.put(f"{base}/users/{uid}", json=user).raise_for_status()
            action = "updated"
        else:
            r = c.post(f"{base}/users", json=user)
            r.raise_for_status()
            uid = r.headers["Location"].rsplit("/", 1)[-1]
            action = "created"

        c.put(
            f"{base}/users/{uid}/reset-password", json={"type": "password", "value": password, "temporary": False}
        ).raise_for_status()

        roles = [c.get(f"{base}/roles/{n}").json() for n in ("admin", "approver")]
        c.post(f"{base}/users/{uid}/role-mappings/realm", json=roles).raise_for_status()

        # CORTEX_MFA_REQUIRED=false (local development only, D-033): privileged roles stop implying
        # mfa-required, so the login flow skips OTP. true (the default) restores the composites.
        mfa_on = env.get("CORTEX_MFA_REQUIRED", "true").lower() != "false"
        marker = c.get(f"{base}/roles/mfa-required").json()
        for role in ("admin", "approver", "auditor", "executive"):
            comps = c.get(f"{base}/roles/{role}/composites").json()
            has = any(r["name"] == "mfa-required" for r in comps)
            if mfa_on and not has:
                c.post(f"{base}/roles/{role}/composites", json=[marker]).raise_for_status()
            elif not mfa_on and has:
                c.request("DELETE", f"{base}/roles/{role}/composites", json=[marker]).raise_for_status()

        creds = c.get(f"{base}/users/{uid}/credentials").json()
        needs_totp = mfa_on and not any(cr.get("type") == "otp" for cr in creds)
        c.put(
            f"{base}/users/{uid}", json={**user, "requiredActions": ["CONFIGURE_TOTP"] if needs_totp else []}
        ).raise_for_status()
    print(f"bootstrap_admin: {action} {email} (roles admin, approver; MFA {'required' if mfa_on else 'OFF'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
