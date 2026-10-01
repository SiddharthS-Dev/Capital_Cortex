"""Admin settings (screen 17): versioned overrides in ``setting``, applied over the YAML/JSON defaults at runtime.

Keys and what they may change (everything else stays file-controlled and reviewed in git):
* ``llm_router``   — per-tier model, max_tokens and prices (providers and secret refs stay in config)
* ``budgets``      — daily $ cap and per-feature caps
* ``governance``   — allow_self_approval, auto_release_on_approval, business_hours_only, timezone,
                     approval_due_days, webhook_allowlist (the Rego itself is not editable at runtime)
* ``retention``    — per-policy durations (the audit log's 7-year immutability can't be changed)
* ``taxonomy``     — class labels and rule keywords for the 11 classes (class keys are fixed: the DB enum)
Every write is audited with the before/after values and bumps the version.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l7_governance import audit_service
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.errors import Problem

KEYS = ("llm_router", "budgets", "governance", "retention", "taxonomy")
GOVERNANCE_KEYS: dict[str, type] = {"allow_self_approval": bool, "auto_release_on_approval": bool, "business_hours_only": bool,
                   "timezone": str, "approval_due_days": int, "webhook_allowlist": list}  # fmt: skip
TIER_KEYS: dict[str, type | tuple[type, ...]] = {
    "model": str,
    "max_tokens": int,
    "price_in_per_mtok": (int, float),
    "price_out_per_mtok": (int, float),
}

_current: dict[str, Any] = {}


def current(key: str) -> Any:
    return copy.deepcopy(_current.get(key))


def validate(key: str, value: Any) -> Any:
    if key not in KEYS:
        raise Problem(422, "Unknown setting", f"one of {KEYS}", "validation")
    if not isinstance(value, dict):
        raise Problem(422, "Invalid setting", "value must be an object", "validation")
    if key == "governance":
        for k, v in value.items():
            if k not in GOVERNANCE_KEYS or not isinstance(v, GOVERNANCE_KEYS[k]):
                raise Problem(
                    422, "Invalid governance setting", f"{k}: allowed {sorted(GOVERNANCE_KEYS)}", "validation"
                )
        if any(not str(u).startswith("https://") for u in value.get("webhook_allowlist", [])):
            raise Problem(422, "Invalid allowlist", "webhook destinations must be https URLs", "validation")
    if key == "llm_router":
        for tier, spec in (value.get("tiers") or {}).items():
            if tier not in ("small", "mid", "large") or not isinstance(spec, dict):
                raise Problem(422, "Invalid tier", "tiers are small / mid / large", "validation")
            for k, v in spec.items():
                if k not in TIER_KEYS or not isinstance(v, TIER_KEYS[k]) or (isinstance(v, int | float) and v < 0):
                    raise Problem(422, "Invalid tier setting", f"{tier}.{k}: allowed {sorted(TIER_KEYS)}", "validation")
    if key == "budgets":
        cap = value.get("daily_cap_usd")
        if cap is not None and (not isinstance(cap, int | float) or cap < 0):
            raise Problem(422, "Invalid budget", "daily_cap_usd must be ≥ 0", "validation")
        for f, c in (value.get("feature_caps") or {}).items():
            if not isinstance(c, int | float) or c < 0:
                raise Problem(422, "Invalid budget", f"feature cap {f} must be ≥ 0", "validation")
    if key == "retention":
        from cortex.l7_governance.retention import duration, policies

        known = policies()
        for pol, spec in value.items():
            if pol not in known or pol == "audit_log":
                raise Problem(422, "Invalid retention policy", f"{pol} can't be overridden", "validation")
            for k, v in spec.items():
                if k in ("retain", "warm"):
                    try:
                        duration(v)
                    except ValueError as e:
                        raise Problem(422, "Invalid duration", str(e), "validation") from e
    if key == "taxonomy":
        from cortex.l2_representation.taxonomy import base_taxonomy

        classes = base_taxonomy()["classes"]
        for cls, spec in (value.get("classes") or {}).items():
            if cls not in classes:
                raise Problem(422, "Unknown class", "the 11 class keys are fixed", "validation")
            if not set(spec) <= {"label", "keywords"}:
                raise Problem(422, "Invalid class setting", "only label and keywords are editable", "validation")
    return value


def apply(key: str, value: Any) -> None:
    """Push an override into the running process (idempotent)."""
    _current[key] = value
    if key == "governance":
        from cortex.l7_governance import policy_engine

        policy_engine.set_overrides(value)
    elif key in ("llm_router", "budgets"):
        from platform_core.llm import router

        router.set_overrides(_current.get("llm_router") or {}, _current.get("budgets") or {})
    elif key == "taxonomy":
        from cortex.l2_representation import taxonomy

        taxonomy.set_overrides(value)


async def load_all(s: AsyncSession) -> dict[str, int]:
    rows = (
        await s.execute(
            text("SELECT key, value, version FROM setting WHERE org_id = :org"), {"org": get_settings().org_id}
        )
    ).all()
    for r in rows:
        if r.key in KEYS:
            apply(r.key, r.value)
    return {r.key: r.version for r in rows}


async def get(s: AsyncSession, key: str) -> dict[str, Any] | None:
    r = (
        (await s.execute(text("SELECT value, version, updated_by, updated_at FROM setting WHERE org_id = :org AND key = :k"),
                         {"org": get_settings().org_id, "k": key}))
        .mappings()
        .first()
    )  # fmt: skip
    return dict(r) if r else None


async def put(s: AsyncSession, actor: Principal, key: str, value: Any) -> dict[str, Any]:
    value = validate(key, value)
    before = await get(s, key)
    version = int(
        (
            await s.execute(
                text(
                    "INSERT INTO setting (org_id, key, value, version, updated_by) VALUES (:org, :k, CAST(:v AS jsonb), 1, :by) "
                    "ON CONFLICT (org_id, key) DO UPDATE SET value = EXCLUDED.value, version = setting.version + 1, "
                    "updated_by = EXCLUDED.updated_by RETURNING version"
                ),
                {"org": get_settings().org_id, "k": key, "v": json.dumps(value), "by": actor.sub},
            )
        ).scalar_one()
    )
    apply(key, value)
    await audit_service.record(s, actor, f"setting.{key}.updated", f"setting:{key}",
                               {"version": version, "before": (before or {}).get("value"), "after": value})  # fmt: skip
    return {"key": key, "version": version, "value": value}
