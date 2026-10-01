"""Role-based access control driven by ``config/roles.yaml`` (the same file OPA loads)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from platform_core.auth.principal import Principal
from platform_core.config import get_settings


def _matches(granted: str, wanted: str) -> bool:
    if granted == "*" or granted == wanted:
        return True
    if granted.endswith(":*"):
        return wanted.split(":", 1)[0] == granted[:-2]
    return False


class RBAC:
    def __init__(self, spec: dict[str, Any]) -> None:
        self.spec = spec
        self.roles: dict[str, dict[str, Any]] = spec.get("roles", {})
        self.service_clients: dict[str, list[str]] = spec.get("service_clients", {})
        self.classifications: list[str] = spec.get("classifications", [])

    @classmethod
    def from_file(cls, path: Path) -> RBAC:
        return cls(yaml.safe_load(path.read_text(encoding="utf-8")))

    def permissions_for(self, roles: frozenset[str] | set[str]) -> set[str]:
        perms: set[str] = set()
        for r in roles:
            perms.update(self.roles.get(r, {}).get("permissions", []))
        return perms

    def mfa_required(self, roles: frozenset[str] | set[str]) -> bool:
        return any(self.roles.get(r, {}).get("mfa") == "required" for r in roles)

    def clearance(self, roles: frozenset[str] | set[str]) -> str:
        levels = [self.roles.get(r, {}).get("clearance", "public") for r in roles] or ["public"]
        return max(levels, key=self.classification_rank)

    def classification_rank(self, level: str) -> int:
        try:
            return self.classifications.index(level)
        except ValueError:
            return len(self.classifications)  # unknown = most restrictive

    def allows(self, principal: Principal, permission: str) -> bool:
        granted = self.permissions_for(principal.roles) | set(principal.grants)
        if not any(_matches(g, permission) for g in granted):
            return False
        if principal.is_service and principal.client_id is not None:
            scoped = self.service_clients.get(principal.client_id)
            # Unknown service clients get nothing (least privilege).
            if scoped is None or not any(_matches(g, permission) for g in scoped):
                return False
        return True


@lru_cache
def get_rbac() -> RBAC:
    return RBAC.from_file(get_settings().config_dir / "roles.yaml")
