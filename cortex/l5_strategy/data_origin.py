"""Data origin of an opportunity (FR-07): where its record came from, so dashboards can be read per origin.

  demo     synthetic seed data (``is_demo``)
  live     official feeds polled by the platform (source kind api / rss / html)
  upload   files a user uploaded (source kind file: CSV / XLSX upload, the outreach workbook)
  manual   entered by hand, internal, mailbox / calendar / data room, or no source signal

The origin is derived from the opportunity's signal → source, never stored, so it can't drift from provenance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

ORIGINS = ("demo", "live", "upload", "manual")
LABELS = {
    "demo": "Demo / seeded",
    "live": "Live feeds",
    "upload": "Uploaded files",
    "manual": "Manual / other",
}
LIVE_KINDS = ("api", "rss", "html")
UPLOAD_KINDS = ("file",)

_KIND_TO_ORIGIN = (
    f"CASE WHEN s.kind IN ({', '.join(repr(k) for k in LIVE_KINDS)}) THEN 'live' "
    f"WHEN s.kind IN ({', '.join(repr(k) for k in UPLOAD_KINDS)}) THEN 'upload' ELSE 'manual' END"
)


def origin_expr(alias: str) -> str:
    """SQL for the origin of the opportunity row ``alias`` (a correlated lookup of its signal's source)."""
    return (
        f"CASE WHEN {alias}.is_demo THEN 'demo' ELSE COALESCE((SELECT {_KIND_TO_ORIGIN} FROM signal sg "
        f"JOIN source s ON s.id = sg.source_id WHERE sg.id = {alias}.signal_id), 'manual') END"
    )


def source_key_expr(alias: str) -> str:
    return f"(SELECT s.adapter_key FROM signal sg JOIN source s ON s.id = sg.source_id WHERE sg.id = {alias}.signal_id)"


@dataclass(frozen=True)
class Scope:
    """Which opportunities a dashboard figure covers. With no origins and no sources it is every origin (subject
    to ``include_demo``), and adds no SQL, so the unfiltered dashboard runs exactly as before."""

    include_demo: bool = True
    origins: tuple[str, ...] = ()
    sources: tuple[str, ...] = ()

    @classmethod
    def build(
        cls, include_demo: bool = True, origins: list[str] | None = None, sources: list[str] | None = None
    ) -> Scope:
        bad = sorted(set(origins or ()) - set(ORIGINS))
        if bad:
            from platform_core.errors import Problem

            raise Problem(422, "Invalid origin", f"origin must be one of {list(ORIGINS)}; got {bad}", "validation")
        o = tuple(dict.fromkeys(origins or ()))
        # selecting the demo origin implies demo rows are shown; selecting only other origins hides them
        demo = ("demo" in o) if o else include_demo
        return cls(demo, o, tuple(dict.fromkeys(sources or ())))

    @property
    def filtered(self) -> bool:
        return bool(self.origins or self.sources)

    def sql(self, alias: str) -> str:
        """Predicate to AND into a WHERE over opportunity ``alias`` (always includes the demo rule)."""
        parts = [f"(:demo OR NOT {alias}.is_demo)"]
        if self.origins:
            parts.append(f"{origin_expr(alias)} = ANY(CAST(:scope_origins AS text[]))")
        if self.sources:
            parts.append(f"{source_key_expr(alias)} = ANY(CAST(:scope_sources AS text[]))")
        return " AND ".join(parts)

    def params(self) -> dict[str, Any]:
        p: dict[str, Any] = {"demo": self.include_demo}
        if self.origins:
            p["scope_origins"] = list(self.origins)
        if self.sources:
            p["scope_sources"] = list(self.sources)
        return p
