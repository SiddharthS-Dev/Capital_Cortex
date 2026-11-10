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
from urllib.parse import urlsplit

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l7_governance import audit_service
from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.db import is_mysql_session
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
        for u in value.get("webhook_allowlist", []):
            parts = urlsplit(str(u))
            if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password
                    or parts.query or parts.fragment):  # fmt: skip
                raise Problem(422, "Invalid allowlist",
                              "webhook destinations must be https://host[:port][/path] (no credentials, query or fragment)",
                              "validation")  # fmt: skip
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
    col_k = "`key`" if is_mysql_session(s) else "key"
    rows = (
        await s.execute(
            text(f"SELECT {col_k}, value, version FROM setting WHERE org_id = :org"), {"org": get_settings().org_id}
        )
    ).all()
    out = {}
    for r in rows:
        k = getattr(r, "key", r[0])
        val = getattr(r, "value", r[1])
        ver = getattr(r, "version", r[2])
        if isinstance(val, str):
            try:
                val = json.loads(val)
            except ValueError:
                pass
        if k in KEYS:
            apply(k, val)
        out[k] = ver
    return out


async def get(s: AsyncSession, key: str) -> dict[str, Any] | None:
    col_k = "`key`" if is_mysql_session(s) else "key"
    r = (
        (await s.execute(text(f"SELECT value, version, updated_by, updated_at FROM setting WHERE org_id = :org AND {col_k} = :k"),
                         {"org": get_settings().org_id, "k": key}))
        .mappings()
        .first()
    )  # fmt: skip
    if not r:
        return None
    d = dict(r)
    if isinstance(d.get("value"), str):
        try:
            d["value"] = json.loads(d["value"])
        except ValueError:
            pass
    return d


async def put(s: AsyncSession, actor: Principal, key: str, value: Any) -> dict[str, Any]:
    value = validate(key, value)
    before = await get(s, key)
    mysql = is_mysql_session(s)
    if mysql:
        # atomic like PostgreSQL's `version = setting.version + 1 … RETURNING`: the increment happens in the row
        # update (no read-modify-write race), then the row (locked by the upsert) is read back in this transaction
        await s.execute(
            text(
                "INSERT INTO setting (org_id, `key`, value, version, updated_by) VALUES (:org, :k, CAST(:v AS JSON), 1, :by) "
                "AS new ON DUPLICATE KEY UPDATE value = new.value, version = setting.version + 1, updated_by = new.updated_by"
            ),
            {"org": get_settings().org_id, "k": key, "v": json.dumps(value), "by": actor.sub},
        )
        version = int(
            (
                await s.execute(
                    text("SELECT version FROM setting WHERE org_id = :org AND `key` = :k"),
                    {"org": get_settings().org_id, "k": key},
                )
            ).scalar_one()
        )
    else:
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
