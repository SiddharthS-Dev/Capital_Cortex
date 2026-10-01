"""Evidence appendix labels: ref → (what the record is, where it came from). Resolved inside the caller's scope."""

from __future__ import annotations

from typing import Any

from cortex.l7_governance.citation_checker import Resolved
from cortex.l7_governance.refs import DBRefResolver


def _source(rec: dict[str, Any]) -> str:
    src = rec.get("source_ref") or {}
    if not isinstance(src, dict):
        return ""
    kind = src.get("kind", "")
    if kind in ("signal", "signal_source"):
        return " · ".join(str(x) for x in (src.get("source_key"), src.get("url")) if x)
    if kind == "manual_entry":
        return f"entered by {src.get('entered_by', '?')}"
    if kind == "synthetic_seed":
        return "synthetic DEMO seed"
    return kind


def label(r: Resolved) -> tuple[str, str]:
    rec, kind, fld = r.record, r.kind, None
    if "field" in rec and "value" in rec:
        fld = rec.get("field")
    name = rec.get("title") or rec.get("name")
    if kind == "tool":
        key = r.ref.split(":")[-1].split("#")[0]
        return (
            f"{key.replace('_', ' ')}: deterministic tool result",
            "computed by Capital Cortex from the cited records",
        )
    if kind == "config":
        return f"declared assumption ({r.ref.removeprefix('config:')})", "configuration file"
    if kind == "financial_snapshot":
        return f"financial snapshot {rec.get('period', '')}", _source(rec)
    if kind == "interaction":
        return f"{str(rec.get('kind', '')).replace('_', ' ')} on {str(rec.get('occurred_at', ''))[:10]}", _source(rec)
    if kind == "recommendation":
        return f"capital council recommendation ({rec.get('stance', '')})", "agent council run"
    if kind == "memory":
        return "relationship reflection (consolidated memory)", "consolidation job"
    if kind == "document":
        return f"data-room document {name} v{rec.get('version', '')}", f"sha256 {str(rec.get('checksum', ''))[:12]}"
    base = f"{kind.replace('_', ' ')}{': ' + str(name) if name else ''}"
    return (f"{base} · {fld}" if fld else base), _source(rec)


async def labels(resolver: DBRefResolver, refs: list[str]) -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for ref in refs:
        r = await resolver.resolve(ref)
        out[ref] = label(r) if r else ("unresolved reference", "")
    return out
