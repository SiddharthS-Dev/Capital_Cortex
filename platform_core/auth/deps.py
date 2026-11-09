"""FastAPI dependencies: authenticate → role MFA → RBAC → OPA (all must allow).

Usage::

    @router.get("/audit", dependencies=[])
    async def list_audit(p: Principal = Depends(authorize("audit:read", "audit_log"))): ...
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from platform_core.auth.abac import Resource
from platform_core.auth.mfa import enforce_role_mfa, enforce_step_up
from platform_core.auth.oidc import get_verifier
from platform_core.auth.principal import Principal
from platform_core.auth.rbac import get_rbac
from platform_core.config import get_settings
from platform_core.errors import Forbidden, StepUpRequired, Unauthorized
from platform_core.policy.opa import get_opa
from platform_core.security import security_event

_bearer = HTTPBearer(auto_error=False)

OPA_AUTHZ_PACKAGE = "cortex.authz"


async def authenticate(request: Request, creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> Principal:
    if creds is None or creds.scheme.lower() != "bearer":
        security_event("authn.token_missing", "denied", request=request)
        raise Unauthorized()
    try:
        principal = await get_verifier().verify(creds.credentials)
    except Unauthorized:
        security_event("authn.token_rejected", "denied", request=request)
        raise
    request.state.principal = principal
    if get_settings().oidc_enforce_mfa:
        try:
            enforce_role_mfa(principal, get_rbac())
        except Forbidden:
            security_event("authn.mfa_required", "denied", principal=principal, request=request)
            raise
    return principal


async def check_access(principal: Principal, permission: str, resource: Resource, context: dict | None = None) -> None:
    """Service-boundary re-check usable outside FastAPI (workers, internal calls)."""
    if not get_rbac().allows(principal, permission):
        security_event("authz.permission_denied", "denied", principal=principal, resource_type=resource.type,
                       resource_id=resource.id, reason=permission, **_where(context))  # fmt: skip
        raise Forbidden(f"Missing permission {permission}", permission=permission)
    decision = await get_opa().evaluate(
        OPA_AUTHZ_PACKAGE,
        {
            "subject": principal.to_opa(),
            "action": permission,
            "resource": resource.to_opa(),
            "context": {"time": datetime.now(UTC).isoformat(), **(context or {})},
        },
    )
    if not decision.allow:
        security_event("authz.policy_denied", "denied", principal=principal, resource_type=resource.type,
                       resource_id=resource.id, reason=permission, policy_reasons=decision.reasons, **_where(context))  # fmt: skip
        raise Forbidden("Denied by policy", permission=permission, reasons=decision.reasons)


def _where(context: dict | None) -> dict:
    return {k: (context or {})[k] for k in ("method", "path") if k in (context or {})}


ResourceFn = Callable[[Request], Awaitable[Resource] | Resource]


def authorize(
    permission: str,
    resource_type: str,
    resource_fn: ResourceFn | None = None,
    step_up: bool = False,
) -> Callable[..., Awaitable[Principal]]:
    async def _dep(request: Request, principal: Principal = Depends(authenticate)) -> Principal:
        if resource_fn is not None:
            res = resource_fn(request)
            resource = await res if hasattr(res, "__await__") else res
        else:
            resource = Resource(type=resource_type, id=request.path_params.get("id"))
        if step_up:
            s = get_settings()
            try:
                enforce_step_up(principal, s.step_up_max_age_seconds, require_mfa=s.oidc_enforce_mfa)
            except StepUpRequired:
                security_event("authn.step_up_required", "denied", principal=principal, reason=permission,
                               request=request)  # fmt: skip
                raise
        await check_access(
            principal,
            permission,
            resource,
            {"method": request.method, "path": request.url.path},
        )
        return principal

    _dep.__name__ = f"authorize_{permission.replace(':', '_')}"
    _dep.permission = permission  # type: ignore[attr-defined]  # introspected by the authz-matrix test
    return _dep
