"""Attribute-based checks (owner, classification, capital class). OPA makes the final decision; these
helpers build its input and give services a local re-check (I4 defence in depth)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from platform_core.auth.principal import Principal
from platform_core.auth.rbac import RBAC


@dataclass
class Resource:
    type: str
    id: str | None = None
    owner_id: str | None = None
    classification: str | None = None
    capital_class: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_opa(self) -> dict[str, Any]:
        d = {
            "type": self.type,
            "id": self.id,
            "owner_id": self.owner_id,
            "classification": self.classification,
            "capital_class": self.capital_class,
        }
        d.update(self.attrs)
        return d


def classification_allowed(principal: Principal, resource: Resource, rbac: RBAC) -> bool:
    if resource.classification is None:
        return True
    clearance = rbac.clearance(principal.roles)
    return rbac.classification_rank(resource.classification) <= rbac.classification_rank(clearance)


def is_owner(principal: Principal, resource: Resource) -> bool:
    return resource.owner_id is not None and resource.owner_id == principal.sub
