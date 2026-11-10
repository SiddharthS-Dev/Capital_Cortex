"""Raw item → ``Signal`` using the source's declarative mapping, with per-field provenance."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any

from cortex.l1_perception.mapping import resolve, strip_html, to_date, to_number
from cortex.l1_perception.models import RawItem, Signal
from cortex.l1_perception.registry import SourceConfig
from platform_core.geo import normalize_countries


class NormalizationError(ValueError):
    permanent = True


DATE_FIELDS = {"published_at", "open_date", "deadline"}
NUMBER_FIELDS = {"amount_min", "amount_max"}
LIST_FIELDS = {"countries", "sectors", "categories", "instruments", "stage_fit"}
TEXT_FIELDS = {"title", "description", "counterparty_name"}
_KEY = re.compile(r"[^a-z0-9]+")


def _norm_keys(payload: dict[str, Any]) -> dict[str, Any]:
    return {_KEY.sub("_", str(k).strip().lower()).strip("_"): v for k, v in payload.items()}


def _as_list(v: Any) -> list[str]:
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [s.strip() for s in re.split(r"[;,|]", str(v)) if s.strip()]


def normalize(cfg: SourceConfig, raw: RawItem) -> Signal:
    payload = _norm_keys(raw.payload) if cfg.case_insensitive_keys else raw.payload
    fields: dict[str, Any] = {}
    sources: dict[str, str] = {}
    for field, spec in cfg.mapping.items():
        value, note = resolve(payload, spec)
        if value is None:
            continue
        fields[field], sources[field] = value, note or "raw"
    for field, value in cfg.defaults.items():
        if field not in fields and value not in (None, "", []):
            fields[field], sources[field] = value, "source_default"

    eligibility: dict[str, Any] = {}
    for f in [k for k in fields if k.startswith("eligibility_")]:
        v = fields.pop(f)
        eligibility[f.removeprefix("eligibility_")] = strip_html(str(v)) if isinstance(v, str) else v
        sources[f"eligibility.{f.removeprefix('eligibility_')}"] = sources.pop(f, "raw")
    if eligibility:
        fields["eligibility"] = eligibility

    for f in list(fields):
        v = fields[f]
        if f in DATE_FIELDS:
            fields[f] = to_date(v)
        elif f in NUMBER_FIELDS:
            fields[f] = to_number(v)
        elif f in LIST_FIELDS:
            fields[f] = _as_list(v)
        elif f in TEXT_FIELDS:
            fields[f] = strip_html(str(v))
        elif f == "currency":
            fields[f] = str(v).strip().upper()[:3]
        elif f == "external_id":
            fields[f] = str(v)
        if fields[f] in (None, "", []):
            fields.pop(f)
            sources.pop(f, None)

    if "countries" in fields:
        fields["countries"] = normalize_countries(fields["countries"])
    if fields.get("counterparty_country"):
        cc = normalize_countries([fields["counterparty_country"]])
        fields["counterparty_country"] = cc[0] if cc else None
    if fields.get("description") and len(fields["description"]) > 20_000:
        fields["description"] = fields["description"][:20_000]
    if not fields.get("title"):
        raise NormalizationError("mapping produced no title")
    amin, amax = fields.get("amount_min"), fields.get("amount_max")
    if amin is not None and amax is not None and amin > amax:
        fields["amount_min"], fields["amount_max"] = amax, amin
    if amin is not None and amin <= 0:
        fields.pop("amount_min")
    if amax is not None and amax <= 0:
        fields.pop("amount_max")
    return Signal(source_key=cfg.key, field_sources=sources, **fields)


def accept(cfg: SourceConfig, sig: Signal) -> str | None:
    """Apply the source's ``accept`` rules to a normalised signal. Returns the rejection reason, or None to keep it.

    url_pattern       regex the signal URL must match (e.g. only solicitation pages of a mixed feed)
    require_fields    signal fields that must be present (e.g. [deadline])
    keywords_any      at least one must appear in the title or description (case-insensitive)
    exclude_keywords  none may appear in the title
    future_deadline   true: drop items whose deadline has already passed (closed calls)
    """
    rules = cfg.accept
    if not rules:
        return None
    if rules.get("url_pattern") and not re.search(rules["url_pattern"], sig.url or ""):
        return "url does not match url_pattern"
    for f in rules.get("require_fields") or []:
        if getattr(sig, f, None) in (None, "", []):
            return f"missing required field {f}"
    text_ = f"{sig.title} {sig.description or ''}".lower()
    kws = [k.lower() for k in rules.get("keywords_any") or []]
    if kws and not any(k in text_ for k in kws):
        return "no funding keyword in title or description"
    bad = [k for k in (rules.get("exclude_keywords") or []) if k.lower() in sig.title.lower()]
    if bad:
        return f"excluded keyword {bad[0]!r} in title"
    if rules.get("future_deadline") and sig.deadline is not None and sig.deadline < datetime.now(UTC):
        return "deadline has passed"
    return None
