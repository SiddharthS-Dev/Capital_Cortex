"""MFA hooks (R5) and step-up checks for approvals (§10)."""

from __future__ import annotations

import time

from platform_core.auth.principal import Principal
from platform_core.auth.rbac import RBAC
from platform_core.errors import Forbidden, StepUpRequired


def enforce_role_mfa(principal: Principal, rbac: RBAC) -> None:
    """Admin/Approver/Auditor/Executive tokens must carry a second factor."""
    if principal.is_service:
        return
    if rbac.mfa_required(principal.roles) and not principal.mfa:
        raise Forbidden(
            "Your role requires multi-factor authentication. Sign in again with your authenticator app.",
            mfa_required=True,
        )


def enforce_step_up(
    principal: Principal, max_age_seconds: int, now: float | None = None, require_mfa: bool = True
) -> None:
    """Approvals need a fresh authentication (within ``max_age_seconds``), with MFA unless it's switched off."""
    if require_mfa and not principal.mfa:
        raise StepUpRequired("Approvals require MFA")
    age = principal.auth_age_seconds(now or time.time())
    if age is None or age > max_age_seconds:
        raise StepUpRequired(f"Re-authenticate (last authentication > {max_age_seconds}s ago)")
