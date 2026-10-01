from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

KNOWN_ROLES = frozenset({"admin", "analyst", "approver", "auditor", "executive", "service"})


@dataclass(frozen=True)
class Principal:
    """An authenticated caller: a human user or a service account."""

    sub: str
    username: str
    roles: frozenset[str]
    grants: frozenset[str] = frozenset()
    email: str | None = None
    name: str | None = None
    client_id: str | None = None
    is_service: bool = False
    amr: tuple[str, ...] = ()
    acr: str | None = None
    auth_time: int | None = None
    token: str = field(default="", repr=False)
    claims: dict[str, Any] = field(default_factory=dict, repr=False)
    mfa_acr_values: tuple[str, ...] = ("mfa", "2", "gold")

    @property
    def mfa(self) -> bool:
        """True when the IdP reports a second factor (AMR otp/mfa, or an MFA-level ACR)."""
        return bool({"otp", "mfa", "hwk", "swk"} & set(self.amr)) or (
            self.acr is not None and self.acr in self.mfa_acr_values
        )

    def auth_age_seconds(self, now: float | None = None) -> float | None:
        if self.auth_time is None:
            return None
        return (now or time.time()) - self.auth_time

    def to_opa(self) -> dict[str, Any]:
        return {
            "sub": self.sub,
            "username": self.username,
            "roles": sorted(self.roles),
            "grants": sorted(self.grants),
            "is_service": self.is_service,
            "client_id": self.client_id,
            "mfa": self.mfa,
        }
