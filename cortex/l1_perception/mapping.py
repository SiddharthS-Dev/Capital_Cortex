"""Declarative field mapping from raw payloads to ``Signal`` fields (adding a source is config, not code).

A mapping entry is one of:
  "a.b.c"                         dotted path (``items[*].name`` collects a list; ``items[0]`` indexes)
  ["a.b", "c.d"]                  first path that yields a non-empty value
  {"template": "https://x/{id}"}  format string over the payload's top-level keys
  {"value": "USD"}                a literal (recorded as a source default in field_sources)
  {"paths": [...], "transform": "date" | "number" | "html" | "list" | "upper"}
"""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from dateutil import parser as dateparser
from dateutil import tz

_TOKEN = re.compile(r"([^.\[\]]+)|\[(\*|\d+)\]")
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
_TZINFOS = {
    "EST": tz.gettz("America/New_York"),
    "EDT": tz.gettz("America/New_York"),
    "CST": tz.gettz("America/Chicago"),
    "CDT": tz.gettz("America/Chicago"),
    "PST": tz.gettz("America/Los_Angeles"),
    "PDT": tz.gettz("America/Los_Angeles"),
}


def get_path(obj: Any, path: str) -> Any:
    cur: list[Any] = [obj]
    fan_out = False
    for key, idx in _TOKEN.findall(path):
        nxt: list[Any] = []
        for c in cur:
            if key:
                if isinstance(c, dict) and key in c:
                    nxt.append(c[key])
            elif idx == "*":
                fan_out = True
                if isinstance(c, list):
                    nxt.extend(c)
            elif isinstance(c, list) and int(idx) < len(c):
                nxt.append(c[int(idx)])
        cur = nxt
    if fan_out:
        return [v for v in cur if v not in (None, "")]
    return cur[0] if cur else None


def _empty(v: Any) -> bool:
    return v is None or v == "" or v == [] or v == {}


def strip_html(s: str) -> str:
    for _ in range(3):  # some sources double-escape entities (&amp;nbsp;)
        u = html.unescape(s)
        if u == s:
            break
        s = u
    return _WS.sub(" ", _TAGS.sub(" ", s).replace(" ", " ")).strip()


def to_date(v: Any) -> datetime | None:
    if _empty(v):
        return None
    if isinstance(v, datetime):
        d = v
    else:
        try:
            d = dateparser.parse(str(v), tzinfos=_TZINFOS)
        except (ValueError, OverflowError):
            return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def to_number(v: Any) -> Decimal | None:
    if _empty(v):
        return None
    try:
        return Decimal(re.sub(r"[^\d.\-]", "", str(v)))
    except InvalidOperation:
        return None


TRANSFORMS = {
    "date": to_date,
    "number": to_number,
    "html": lambda v: strip_html(str(v)) if not _empty(v) else None,
    "upper": lambda v: str(v).upper() if not _empty(v) else None,
    "list": lambda v: v if isinstance(v, list) else ([] if _empty(v) else [v]),
}


def resolve(payload: dict[str, Any], spec: Any) -> tuple[Any, str | None]:
    """Return (value, provenance note) for one mapping entry."""
    transform = None
    if isinstance(spec, dict):
        transform = spec.get("transform")
        if "value" in spec:
            return spec["value"], "source_default"
        if "template" in spec:
            try:
                return spec["template"].format(
                    **{k: v for k, v in payload.items() if not isinstance(v, dict | list)}
                ), f"template:{spec['template']}"
            except (KeyError, IndexError):
                return None, None
        paths = spec.get("paths") or ([spec["path"]] if "path" in spec else [])
    elif isinstance(spec, list):
        paths = spec
    else:
        paths = [spec]
    for p in paths:
        v = get_path(payload, p)
        if not _empty(v):
            if transform:
                v = TRANSFORMS[transform](v)
            if not _empty(v):
                return v, f"raw:{p}"
    return None, None
