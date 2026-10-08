"""L7 policy engine: builds the OPA ``cortex.governance`` input for a governed action and evaluates it.

The Rego lives in ``config/policies/governance.rego``. This module supplies the facts: the action, the
content flags (computed deterministically from ``config/governance.yaml`` patterns), the approvals recorded
so far, the requester, the org-local time and the config switches.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from platform_core.config import get_settings
from platform_core.policy.opa import PolicyDecision, get_opa
from platform_core.signing import canonical_json

GOVERNANCE_PACKAGE = "cortex.governance"

CHANNEL_KIND = {"email": "outbound", "webhook": "outbound", "portal_export": "export"}


@lru_cache
def _governance_file() -> dict[str, Any]:
    return yaml.safe_load((get_settings().config_dir / "governance.yaml").read_text(encoding="utf-8")) or {}


_overrides: dict[str, Any] = {}


def set_overrides(value: dict[str, Any]) -> None:
    """Admin overrides (settings_service), applied over config/governance.yaml."""
    _overrides.clear()
    _overrides.update(value or {})


def governance_config() -> dict[str, Any]:
    return {**_governance_file(), **_overrides}


def _compiled(key: str) -> list[re.Pattern[str]]:
    return [re.compile(p, re.I) for p in governance_config().get(key, [])]


# Fields that only address the delivery (never scanned). Everything else, the body included, always is.
_ADDRESS_FIELDS = ("to", "recipient", "portal", "url")
# Hyphens, dashes, underscores and unusual spaces that would split a phrase like "term sheet" past a pattern.
_SEPARATORS = re.compile(r"[\s  -​  　_\-‐-―−]+")
_EMAIL_ADDRESS = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def content_flags(payload: dict[str, Any], kind: str, recipient: str | None = None) -> dict[str, bool]:
    """Deterministic flags that select policies (financial terms, PII, grant submission).

    Address fields are dropped by key, never by deleting the recipient's text from the body: a portal name the
    author picks (e.g. "term sheet") must not erase the same words from the content. Only the recipient's own
    e-mail address is ignored, and only for the PII check (greeting the recipient isn't a PII disclosure)."""
    body = canonical_json({k: v for k, v in payload.items() if k not in _ADDRESS_FIELDS})
    variants = (body, _SEPARATORS.sub(" ", body))
    pii_body = body
    if recipient and _EMAIL_ADDRESS.match(recipient):
        pii_body = re.sub(re.escape(recipient), " ", body, flags=re.I)
    return {
        "contains_financial_terms": any(p.search(v) for p in _compiled("financial_terms_patterns") for v in variants),
        "contains_pii": any(p.search(pii_body) for p in _compiled("pii_patterns")),
        "is_grant_submission": kind == "submission",
    }


def is_grant_class(capital_class: str | None) -> bool:
    return bool(capital_class) and capital_class in governance_config().get("grant_submission_classes", [])


def effective_flags(
    stored: dict[str, Any] | None, payload: dict[str, Any], kind: str, recipient: str | None = None
) -> dict[str, bool]:
    """Flags the policies act on: recomputed from the content as it is now, OR-ed with any flag stored on the item.

    Stored flags alone can go stale when a payload is rewritten outside the draft-edit path (e.g. a recommendation
    edit regenerating a linked export), which would let financial or PII content skip its stricter release rule."""
    current = content_flags(payload, kind, recipient)
    stored = stored or {}
    return {k: bool(stored.get(k)) or v for k, v in current.items()} | {
        k: bool(v) for k, v in stored.items() if k not in current
    }


def local_now() -> dict[str, int]:
    tz = ZoneInfo(str(governance_config().get("timezone") or "UTC"))
    now = datetime.now(UTC).astimezone(tz)
    return {"weekday": now.isoweekday(), "hour": now.hour}


def release_input(
    *,
    kind: str,
    channel: str | None,
    subject_type: str,
    recipient_external: bool,
    digest: str,
    flags: dict[str, bool],
    approvals: list[dict[str, Any]],
    requested_by: str | None,
) -> dict[str, Any]:
    cfg = governance_config()
    return {
        "action": {
            "kind": kind,
            "channel": channel,
            "subject_type": subject_type,
            "recipient_external": recipient_external,
        },
        "content": {"hash": digest, **flags},
        "approvals": approvals,
        "requested_by": requested_by,
        "now": local_now(),
        "config": {
            "business_hours_only": bool(cfg.get("business_hours_only", False)),
            "allow_self_approval": bool(cfg.get("allow_self_approval", False)),
        },
    }


async def evaluate_release(input_: dict[str, Any]) -> PolicyDecision:
    return await get_opa().evaluate(GOVERNANCE_PACKAGE, input_)


def required_approvals(flags: dict[str, bool]) -> int:
    """How many distinct approvers the policies will need (shown in the inbox; OPA stays authoritative)."""
    if flags.get("is_grant_submission") or flags.get("contains_financial_terms"):
        return 2
    return 1
