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
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from dateutil import parser as dateparser
from dateutil import tz

_TOKEN = re.compile(r"([^.\[\]]+)|\[(\*|\d+)\]")
_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")
# "6 October 2026 4:00pm UK time" (UKRI) → the Europe/London zone, so BST/GMT is applied by date
_UK_TIME = re.compile(r"\bUK time\b", re.IGNORECASE)
_TZINFOS = {
    "UKT": tz.gettz("Europe/London"),
    "BST": tz.gettz("Europe/London"),
    "EST": tz.gettz("America/New_York"),
    "EDT": tz.gettz("America/New_York"),
    "CST": tz.gettz("America/Chicago"),
    "CDT": tz.gettz("America/Chicago"),
    "PST": tz.gettz("America/Los_Angeles"),
    "PDT": tz.gettz("America/Los_Angeles"),
    # generic (DST-aware) names that listings use; unknown ones are otherwise silently read as UTC
    "ET": tz.gettz("America/New_York"),
    "CT": tz.gettz("America/Chicago"),
    "MT": tz.gettz("America/Denver"),
    "PT": tz.gettz("America/Los_Angeles"),
    "MST": tz.gettz("America/Denver"),
    "MDT": tz.gettz("America/Denver"),
    "CET": tz.gettz("Europe/Brussels"),
    "CEST": tz.gettz("Europe/Brussels"),
    "EET": tz.gettz("Europe/Athens"),
    "EEST": tz.gettz("Europe/Athens"),
    "IST": tz.gettz("Asia/Kolkata"),
    "SGT": tz.gettz("Asia/Singapore"),
    "JST": tz.gettz("Asia/Tokyo"),
    "AEST": tz.gettz("Australia/Sydney"),
    "AEDT": tz.gettz("Australia/Sydney"),
}
_D1, _D2 = datetime(2000, 1, 1), datetime(2000, 1, 2)
_YEAR_FIRST = re.compile(r"\d{4}[-/.]\d{1,2}")


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


_NOON = datetime(2000, 1, 1, 12, 34, 56)


def to_date(
    v: Any, *, dayfirst: bool = False, require_day: bool = False, tz: str | None = None, end_of_day: bool = False
) -> datetime | None:
    """Parse a date. ``dayfirst`` reads 03/10/2026 as 3 October (the source's convention; ISO dates are unaffected).
    ``require_day`` rejects values without a day ("March 2027") instead of inventing one from today's date.
    ``tz`` (an IANA zone) is the source's local time for values that carry no zone (default UTC). ``end_of_day``
    makes a date with no time of day mean 23:59:59 that day: a deadline of "10/15/2026" closes at the end of the
    15th in the source's zone, not at midnight UTC (which is the evening of the 14th in the Americas)."""
    if _empty(v):
        return None
    zone = ZoneInfo(tz) if tz else UTC
    if isinstance(v, datetime):
        d = v
    else:
        text = _UK_TIME.sub("UKT", str(v))
        # year-first (ISO) values are unambiguous; dateutil would read 2026-10-03 as 10 March under dayfirst
        dayfirst = dayfirst and not _YEAR_FIRST.match(text.strip())
        try:
            d = dateparser.parse(text, tzinfos=_TZINFOS, dayfirst=dayfirst, default=_D1)
            if require_day and dateparser.parse(text, tzinfos=_TZINFOS, dayfirst=dayfirst, default=_D2).day != d.day:
                return None  # the day came from the default, not from the value
            # no time of day in the value: both probe defaults (00:00:00 and 12:34:56) come back unchanged
            no_time = (
                end_of_day
                and d.time() == _D1.time()
                and dateparser.parse(text, tzinfos=_TZINFOS, dayfirst=dayfirst, default=_NOON).time() == _NOON.time()
            )
            if no_time:
                d = d.replace(hour=23, minute=59, second=59)
        except (ValueError, OverflowError):
            return None
    return d if d.tzinfo else d.replace(tzinfo=zone)


_MULTIPLIERS = {
    "k": 10**3, "thousand": 10**3, "m": 10**6, "mn": 10**6, "mm": 10**6, "mio": 10**6, "million": 10**6,
    "millions": 10**6, "b": 10**9, "bn": 10**9, "billion": 10**9, "billions": 10**9,
}  # fmt: skip
# one amount: optional sign, digits with separators (or scientific), optional magnitude word
_AMOUNT = re.compile(
    r"(?P<neg>-)?\s*(?P<num>\d[\d.,' ]*\d|\d)(?P<exp>[eE][+-]?\d+)?\s*(?P<mult>thousand|millions?|billions?|mio|mn|mm|bn|k|m|b)?\b",
    re.IGNORECASE,
)
_RANGE_SEP = re.compile(
    r"\d\s*(?:[kmb]|bn|mn|million|billion|thousand)?\s*(?:-|–|—|\bto\b|\bbis\b|\bà\b)\s*\D{0,4}\d", re.I
)


def _plain_number(s: str) -> Decimal | None:
    """Digits with thousands/decimal separators in either convention: 1,250,000.50 · 1.250.000,50 · 1 250 000."""
    s = s.replace(" ", "").replace("'", "")
    if "," in s and "." in s:  # the later one is the decimal separator
        s = s.replace(",", "") if s.rfind(".") > s.rfind(",") else s.replace(".", "").replace(",", ".")
    elif s.count(",") > 1 or re.fullmatch(r"\d{1,3}(,\d{3})+", s):
        s = s.replace(",", "")
    elif "," in s:  # one comma, not 3 digits after it: European decimal ("1,5")
        s = s.replace(",", ".")
    elif s.count(".") > 1 or re.fullmatch(r"\d{1,3}(\.\d{3}){2,}", s):
        s = s.replace(".", "")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _amounts(text: str) -> list[Decimal]:
    out = []
    for m in _AMOUNT.finditer(text):
        n = _plain_number(m["num"].strip())
        if n is None:
            continue
        if m["exp"]:
            n = n.scaleb(int(m["exp"][1:]))
        if m["mult"]:
            n *= _MULTIPLIERS[m["mult"].lower()]
        out.append(-n if m["neg"] else n)
    return out


def to_range(v: Any) -> tuple[Decimal, Decimal] | None:
    """ "10000 to 50000", "€10k–€50k", "1-2 million" → (low, high); None unless the value is a range."""
    if _empty(v) or isinstance(v, int | float | Decimal) or not _RANGE_SEP.search(str(v)):
        return None
    text = str(v).replace("–", " - ").replace("—", " - ")
    parts = re.split(r"\s+-\s+|(?<=\d)-(?=\d)|(?<=[kmb])-(?=\d)|\bto\b|\bbis\b|\bà\b", text, maxsplit=1, flags=re.I)
    if len(parts) != 2:
        return None
    lo, hi = _amounts(parts[0]), _amounts(parts[1])
    if len(lo) != 1 or len(hi) != 1:
        return None
    low, high = lo[0], hi[0]
    mult_lo, mult_hi = _AMOUNT.search(parts[0]), _AMOUNT.search(parts[1])
    if mult_hi and mult_hi["mult"] and not (mult_lo and mult_lo["mult"]):  # "1-2 million": scale both ends
        low *= _MULTIPLIERS[mult_hi["mult"].lower()]
    return (low, high) if low <= high else (high, low)


def to_number(v: Any) -> Decimal | None:
    """One amount from text: "$1,250,000" · "$5M" · "Up to £500k" · "€1.000.000" · "2.5e6" · "(5,000)" (negative).
    A range or several numbers is ambiguous → None (never guessed); use ``to_range`` for ranges."""
    if _empty(v):
        return None
    if isinstance(v, int | float | Decimal) and not isinstance(v, bool):
        return Decimal(str(v))
    text = str(v).strip()
    negative = text.startswith("(") and text.endswith(")")
    found = _amounts(text.strip("()"))
    if len(found) != 1:
        return None
    return -found[0] if negative else found[0]


TRANSFORMS: dict[str, Callable[[Any], Any]] = {
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
