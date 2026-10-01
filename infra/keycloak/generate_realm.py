"""Generates infra/keycloak/realm-cortex.json (the dev/staging realm import).

Run: python infra/keycloak/generate_realm.py
Dev-only secrets and passwords live here on purpose so a clean `make up` works offline. Prod realms are
provisioned by Terraform, with secrets from Vault (RUNBOOK §Identity).
"""

from __future__ import annotations

import json
from pathlib import Path

DEV_PASSWORD = "Cortex!dev-2026"  # noqa: S105 - dev realm only
SMOKE_TOTP_SECRET = "cortex-dev-smoke-totp-secret"  # noqa: S105 - dev realm only
WEB_ORIGINS = ["http://localhost:3300", "http://localhost:5373"]  # container UI, vite dev server


def user(name, roles, first, totp_required=False, attrs=None, otp_secret=None):
    u = {
        "username": name,
        "enabled": True,
        "emailVerified": True,
        "firstName": first,
        "lastName": "Dev",
        "email": f"{name}@cortex.local",
        "realmRoles": roles,
        "credentials": [{"type": "password", "value": DEV_PASSWORD, "temporary": False}],
        "requiredActions": ["CONFIGURE_TOTP"] if totp_required else [],
    }
    if attrs:
        u["attributes"] = attrs
    if otp_secret:
        u["credentials"].append(
            {
                "type": "otp",
                "userLabel": "smoke-seeded (dev only)",
                "secretData": json.dumps({"value": otp_secret}),
                "credentialData": json.dumps(
                    {"subType": "totp", "digits": 6, "counter": 0, "period": 30, "algorithm": "HmacSHA1"}
                ),
            }
        )
    return u


def svc(client, roles):
    return {
        "username": f"service-account-{client}",
        "enabled": True,
        "serviceAccountClientId": client,
        "realmRoles": roles,
    }


def aud(n):
    return {
        "name": f"audience-{n}",
        "protocol": "openid-connect",
        "protocolMapper": "oidc-audience-mapper",
        "config": {
            "included.client.audience": n,
            "access.token.claim": "true",
            "id.token.claim": "false",
            "introspection.token.claim": "true",
        },
    }


AMR = {
    "name": "amr",
    "protocol": "openid-connect",
    "protocolMapper": "oidc-amr-mapper",
    "config": {"access.token.claim": "true", "id.token.claim": "true", "introspection.token.claim": "true"},
}
GRANTS = {
    "name": "cortex-grants",
    "protocol": "openid-connect",
    "protocolMapper": "oidc-usermodel-attribute-mapper",
    "config": {
        "user.attribute": "cortex_grants",
        "claim.name": "cortex_grants",
        "jsonType.label": "String",
        "multivalued": "true",
        "access.token.claim": "true",
        "id.token.claim": "false",
        "introspection.token.claim": "true",
    },
}


def role(n, d, mfa=False):
    r = {"name": n, "description": d}
    if mfa:  # composite: holding this role implies mfa-required, which the login flow checks
        r |= {"composite": True, "composites": {"realm": ["mfa-required"]}}
    return r


def execution(authenticator=None, flow=None, requirement="REQUIRED", priority=10, config=None):
    e = {
        "authenticatorFlow": flow is not None,
        "requirement": requirement,
        "priority": priority,
        "userSetupAllowed": False,
    }
    if flow:
        e["flowAlias"] = flow
    else:
        e["authenticator"] = authenticator
    if config:
        e["authenticatorConfig"] = config
    return e


def flow(alias, desc, executions, top=False):
    return {
        "alias": alias,
        "description": desc,
        "providerId": "basic-flow",
        "topLevel": top,
        "builtIn": False,
        "authenticationExecutions": executions,
    }


REALM = {
    "realm": "cortex",
    "displayName": "Inspironics Capital Cortex",
    "enabled": True,
    "sslRequired": "external",
    "registrationAllowed": False,
    "resetPasswordAllowed": True,
    "bruteForceProtected": True,
    "accessTokenLifespan": 900,
    "ssoSessionIdleTimeout": 1800,
    "ssoSessionMaxLifespan": 36000,
    "revokeRefreshToken": True,
    "refreshTokenMaxReuse": 0,
    "passwordPolicy": "length(12) and notUsername and upperCase(1) and digits(1) and specialChars(1)",
    "otpPolicyType": "totp",
    "otpPolicyAlgorithm": "HmacSHA1",
    "otpPolicyDigits": 6,
    "otpPolicyPeriod": 30,
    "otpPolicyLookAheadWindow": 1,
    "browserFlow": "browser-cortex",
    "roles": {
        "realm": [
            role("mfa-required", "Marker: login must include OTP (R5)"),
            role("admin", "Platform administrator", mfa=True),
            role("analyst", "Capital analyst (MFA optional)"),
            role("approver", "Human-in-the-loop approver", mfa=True),
            role("auditor", "Read-only oversight", mfa=True),
            role("executive", "Board / executive", mfa=True),
            role("service", "Non-human workers"),
        ]
    },
    "clients": [
        {
            "clientId": "cortex-web",
            "name": "Capital Cortex UI",
            "enabled": True,
            "publicClient": True,
            "standardFlowEnabled": True,
            "directAccessGrantsEnabled": False,
            "implicitFlowEnabled": False,
            "redirectUris": [o + "/*" for o in WEB_ORIGINS],
            "webOrigins": WEB_ORIGINS,
            "attributes": {
                "pkce.code.challenge.method": "S256",
                "post.logout.redirect.uris": "##".join(o + "/*" for o in WEB_ORIGINS),
            },
            "protocolMappers": [aud("cortex-api"), AMR, GRANTS],
        },
        {
            "clientId": "cortex-api",
            "name": "Capital Cortex API (audience only)",
            "enabled": True,
            "publicClient": False,
            "standardFlowEnabled": False,
            "directAccessGrantsEnabled": False,
            "serviceAccountsEnabled": False,
            "secret": "dev-api-secret-change-me",
        },
        {
            "clientId": "cortex-worker",
            "name": "Capital Cortex workers",
            "enabled": True,
            "publicClient": False,
            "standardFlowEnabled": False,
            "directAccessGrantsEnabled": False,
            "serviceAccountsEnabled": True,
            "secret": "dev-worker-secret-change-me",
            "protocolMappers": [aud("cortex-api")],
        },
        {
            "clientId": "cortex-ingestion",
            "name": "Capital Cortex ingestion",
            "enabled": True,
            "publicClient": False,
            "standardFlowEnabled": False,
            "directAccessGrantsEnabled": False,
            "serviceAccountsEnabled": True,
            "secret": "dev-ingestion-secret-change-me",
            "protocolMappers": [aud("cortex-api")],
        },
    ],
    "users": [
        user("dev-admin", ["admin", "approver"], "Founder", totp_required=True),
        user("dev-analyst", ["analyst"], "Analyst"),
        user("dev-finance", ["analyst"], "Finance", attrs={"cortex_grants": ["forecast:write"]}),
        user("dev-approver", ["approver"], "Approver", totp_required=True),
        user(
            "dev-legal",
            ["auditor", "approver"],
            "Legal",
            totp_required=True,
            attrs={"cortex_grants": ["compliance:review", "dataroom:approve", "legal_hold:write"]},
        ),
        user("dev-executive", ["executive"], "Board", totp_required=True),
        user("smoke-auditor", ["auditor"], "Smoke", otp_secret=SMOKE_TOTP_SECRET),
        svc("cortex-worker", ["service"]),
        svc("cortex-ingestion", ["service"]),
    ],
    "authenticatorConfig": [
        {"alias": "amr-pwd", "config": {"default.reference.value": "pwd", "default.reference.maxAge": "36000"}},
        {"alias": "amr-otp", "config": {"default.reference.value": "otp", "default.reference.maxAge": "36000"}},
        {
            "alias": "amr-otp-optional",
            "config": {"default.reference.value": "otp", "default.reference.maxAge": "36000"},
        },
        {"alias": "cond-mfa-required", "config": {"condUserRole": "mfa-required", "negate": "false"}},
        {"alias": "cond-not-mfa-required", "config": {"condUserRole": "mfa-required", "negate": "true"}},
    ],
    "authenticationFlows": [
        flow(
            "browser-cortex",
            "Browser login; OTP required for Admin/Approver/Auditor/Executive (R5)",
            [
                execution("auth-cookie", requirement="ALTERNATIVE", priority=10),
                execution(flow="browser-cortex forms", requirement="ALTERNATIVE", priority=20),
            ],
            top=True,
        ),
        flow(
            "browser-cortex forms",
            "Password, then OTP",
            [
                execution("auth-username-password-form", priority=10, config="amr-pwd"),
                execution(flow="browser-cortex mfa-required", requirement="CONDITIONAL", priority=20),
                execution(flow="browser-cortex mfa-optional", requirement="CONDITIONAL", priority=30),
            ],
        ),
        flow(
            "browser-cortex mfa-required",
            "Privileged roles must use OTP",
            [
                execution("conditional-user-role", priority=10, config="cond-mfa-required"),
                execution("auth-otp-form", priority=20, config="amr-otp"),
            ],
        ),
        flow(
            "browser-cortex mfa-optional",
            "Analysts who enrolled OTP use it",
            [
                execution("conditional-user-role", priority=10, config="cond-not-mfa-required"),
                execution("conditional-user-configured", priority=20),
                execution("auth-otp-form", priority=30, config="amr-otp-optional"),
            ],
        ),
    ],
}

if __name__ == "__main__":
    out = Path(__file__).with_name("realm-cortex.json")
    out.write_text(json.dumps(REALM, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")
