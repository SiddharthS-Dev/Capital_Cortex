"""Raw item → ``Signal`` using the source's declarative mapping, with per-field provenance."""

from __future__ import annotations

import re
from typing import Any

from pydantic import ValidationError

from cortex.l1_perception.mapping import resolve, strip_html, to_date, to_number, to_range
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
            fields[f] = to_date(
                v, dayfirst=cfg.date_dayfirst, require_day=True, tz=cfg.date_timezone, end_of_day=f == "deadline"
            )
        elif f in NUMBER_FIELDS:
            rng = to_range(v)
            if rng:  # "10,000 to 50,000" in one field fills both ends (an explicit other field still wins)
                fields[f] = rng[0] if f == "amount_min" else rng[1]
                other = "amount_max" if f == "amount_min" else "amount_min"
                if other not in fields:
                    fields[other] = rng[1] if f == "amount_min" else rng[0]
                    sources[other] = sources[f]
            else:
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
    # a non-positive amount means "not stated" (e.g. Grants.gov's 0 ceiling): drop it first, then order min/max;
    # swapping first dropped the real figure and kept the 0
    for k in ("amount_min", "amount_max"):
        if fields.get(k) is not None and fields[k] <= 0:
            fields.pop(k)
            sources.pop(k, None)
    amin, amax = fields.get("amount_min"), fields.get("amount_max")
    if amin is not None and amax is not None and amin > amax:
        fields["amount_min"], fields["amount_max"] = amax, amin
        if "amount_min" in sources and "amount_max" in sources:
            sources["amount_min"], sources["amount_max"] = sources["amount_max"], sources["amount_min"]
    try:
        return Signal(source_key=cfg.key, field_sources=sources, **fields)
    except ValidationError as e:  # one bad row (e.g. a number where text belongs) fails that row, not the run
        raise NormalizationError(f"invalid field values: {e.error_count()} error(s): {e.errors()[0]['msg']}") from e
