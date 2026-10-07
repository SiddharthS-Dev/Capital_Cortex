"""Dry-run inspection of an upload (FR-04-OUT): which sheet would be read, which header feeds which field, what is
unmapped or missing, and how the first rows would normalise. Reads the file only; writes nothing."""

from __future__ import annotations

import string
from datetime import UTC, datetime
from typing import Any

from cortex.l1_perception.adapters.tabular import apply_joins, join_indexes, read_rows, sheet_names
from cortex.l1_perception.models import RawItem
from cortex.l1_perception.normalizer import NormalizationError, norm_key, normalize
from cortex.l1_perception.registry import SourceConfig

PREVIEW_ROWS = 5
REQUIRED_FIELDS = ("title",)


def _paths(spec: Any) -> tuple[str, list[str]]:
    """(kind, top-level columns a mapping entry reads): kind is path | template | value."""
    if isinstance(spec, dict):
        if "value" in spec:
            return "value", []
        if "template" in spec:
            names = [f for _, f, _, _ in string.Formatter().parse(spec["template"]) if f]
            return "template", names
        spec = spec.get("paths") or ([spec["path"]] if "path" in spec else [])
    paths = spec if isinstance(spec, list) else [spec]
    return "path", [str(p).split(".")[0].split("[")[0] for p in paths]


def _key(cfg: SourceConfig, header: str) -> str:
    return norm_key(header) if cfg.case_insensitive_keys else header


def inspect_upload(
    cfg: SourceConfig, data: bytes, filename: str, sheet: str | None = None, preview: int = PREVIEW_ROWS
) -> dict[str, Any]:
    """Raises ``SheetNotFound`` when ``sheet`` (or the source's configured sheet) isn't in the workbook."""
    names = sheet_names(data, filename)
    chosen = sheet or cfg.sheet if names else None
    rows = read_rows(data, filename, chosen, with_meta=True)
    if names and chosen is None:
        chosen = names[0]
    headers = [h for h in (rows[0] if rows else {}) if not str(h).startswith("_")]
    by_key = {_key(cfg, h): h for h in headers}
    # joined sheets (join_sheets): their prefixed headers can feed fields; their unused columns aren't "unmapped"
    joins = join_indexes(cfg, data, filename)
    joined: list[dict[str, Any]] = []
    for j, index in joins:
        cols = {h for r in index.values() for h in r if not str(h).startswith("_")}
        by_key = {**{_key(cfg, f"{j.prefix}{h}"): f"{j.sheet}: {h}" for h in cols}, **by_key}
        matched_rows = sum(1 for r in rows if index.get(str(r.get(j.main_key) or "").strip().casefold()))
        joined.append({"sheet": j.sheet, "key": j.key, "rows_matched": matched_rows})
    for r in rows:
        apply_joins(r, joins)
    main_keys = {_key(cfg, h) for h in headers}

    fields: list[dict[str, Any]] = []
    used: set[str] = set()
    for field, spec in cfg.mapping.items():
        kind, cols = _paths(spec)
        if kind == "value":
            fields.append({"field": field, "kind": "default", "matched": True, "value": spec["value"]})
            continue
        if kind == "template":
            present = [by_key[c] for c in cols if c in by_key]
            complete = len(present) == len(cols)
            if complete:
                used.update(cols)
            fields.append({"field": field, "kind": "template", "matched": complete, "headers": present,
                           "missing": [c for c in cols if c not in by_key]})  # fmt: skip
            continue
        hit = next((c for c in cols if c in by_key), None)
        used.update(c for c in cols if c in by_key)  # a fallback column is mapped too, not "unmapped"
        fields.append({"field": field, "kind": "path", "matched": hit is not None,
                       "header": by_key.get(hit) if hit else None, "candidates": cols})  # fmt: skip

    guard = {_key(cfg, c): c for c in cfg.require_values}
    used.update(k for k in guard if k in by_key)
    matched = {f["field"] for f in fields if f["matched"]}
    required_missing = [f for f in REQUIRED_FIELDS if f not in matched]
    required_missing += [
        f"{col} (required value {cfg.require_values[col]!r})" for k, col in guard.items() if k not in by_key
    ]

    ok = failed = 0
    sample: list[dict[str, Any]] = []
    for n, row in enumerate(rows):
        r = row.get("_row", n + 2)
        payload = {"_row": r, "_file": filename, **({"_sheet": chosen} if chosen else {}), **row}
        try:
            sig = normalize(
                cfg, RawItem(payload=payload, url=f"upload://{filename}#row={r}", fetched_at=datetime.now(UTC))
            )
            ok += 1
            if len(sample) < preview:
                sample.append({"row": r, "ok": True, "external_id": sig.external_id, "title": sig.title,
                               "countries": sig.countries, "class_hint": sig.class_hint,
                               "attributes": sorted(sig.attributes)})  # fmt: skip
        except NormalizationError as e:
            failed += 1
            if len(sample) < preview:
                sample.append({"row": r, "ok": False, "error": str(e)})
    return {
        "file": filename,
        "sheets": names,
        "sheet": chosen,
        "headers": headers,
        "fields": fields,
        "mapped": sorted(matched),
        "unmapped_headers": [h for k, h in by_key.items() if k in main_keys and k not in used],
        "joined_sheets": joined,
        "required_missing": required_missing,
        "rows": len(rows),
        "would_import": ok,
        "would_fail": failed,
        "preview": sample,
    }
