"""Country normalisation (ISO 3166-1 via pycountry) and the region grouping used by the geography factor."""

from __future__ import annotations

import re
from functools import lru_cache

import pycountry

# Region groups (UN M49 sub-regions, simplified to the markets capital programmes are usually scoped to).
REGIONS: dict[str, list[str]] = {
    "north_america": ["US", "CA", "MX"],
    "latin_america": [
        "AR",
        "BO",
        "BR",
        "CL",
        "CO",
        "CR",
        "CU",
        "DO",
        "EC",
        "GT",
        "HN",
        "JM",
        "NI",
        "PA",
        "PE",
        "PR",
        "PY",
        "SV",
        "TT",
        "UY",
        "VE",
    ],
    "europe": [
        "AD",
        "AL",
        "AT",
        "BA",
        "BE",
        "BG",
        "BY",
        "CH",
        "CY",
        "CZ",
        "DE",
        "DK",
        "EE",
        "ES",
        "FI",
        "FR",
        "GB",
        "GR",
        "HR",
        "HU",
        "IE",
        "IS",
        "IT",
        "LI",
        "LT",
        "LU",
        "LV",
        "MC",
        "MD",
        "ME",
        "MK",
        "MT",
        "NL",
        "NO",
        "PL",
        "PT",
        "RO",
        "RS",
        "SE",
        "SI",
        "SK",
        "SM",
        "UA",
        "XK",
    ],
    "middle_east": ["AE", "BH", "IL", "IQ", "IR", "JO", "KW", "LB", "OM", "PS", "QA", "SA", "SY", "TR", "YE"],
    "africa": [
        "AO",
        "BF",
        "BI",
        "BJ",
        "BW",
        "CD",
        "CF",
        "CG",
        "CI",
        "CM",
        "CV",
        "DJ",
        "DZ",
        "EG",
        "ER",
        "ET",
        "GA",
        "GH",
        "GM",
        "GN",
        "GQ",
        "GW",
        "KE",
        "KM",
        "LR",
        "LS",
        "LY",
        "MA",
        "MG",
        "ML",
        "MR",
        "MU",
        "MW",
        "MZ",
        "NA",
        "NE",
        "NG",
        "RW",
        "SC",
        "SD",
        "SL",
        "SN",
        "SO",
        "SS",
        "ST",
        "SZ",
        "TD",
        "TG",
        "TN",
        "TZ",
        "UG",
        "ZA",
        "ZM",
        "ZW",
    ],
    "south_asia": ["AF", "BD", "BT", "IN", "LK", "MV", "NP", "PK"],
    "east_asia": ["CN", "HK", "JP", "KP", "KR", "MN", "MO", "TW"],
    "southeast_asia": ["BN", "ID", "KH", "LA", "MM", "MY", "PH", "SG", "TH", "TL", "VN"],
    "central_asia": ["KG", "KZ", "TJ", "TM", "UZ", "AM", "AZ", "GE", "RU"],
    "oceania": ["AU", "FJ", "NZ", "PG", "SB", "TO", "VU", "WS"],
}
REGION_OF: dict[str, str] = {c: r for r, cs in REGIONS.items() for c in cs}

_ALIASES = {
    "usa": "US",
    "u.s.": "US",
    "u.s.a.": "US",
    "united states": "US",
    "america": "US",
    "uk": "GB",
    "u.k.": "GB",
    "england": "GB",
    "britain": "GB",
    "great britain": "GB",
    "uae": "AE",
    "south korea": "KR",
    "korea": "KR",
    "north korea": "KP",
    "russia": "RU",
    "vietnam": "VN",
    "iran": "IR",
    "syria": "SY",
    "tanzania": "TZ",
    "bolivia": "BO",
    "venezuela": "VE",
    "laos": "LA",
    "czech republic": "CZ",
    "ivory coast": "CI",
    "taiwan": "TW",
    "palestine": "PS",
    "kosovo": "XK",
    "moldova": "MD",
    "turkey": "TR",
    "eu": "EU",
    "european union": "EU",
}
# EU member states, so "EU" eligibility can be expanded.
EU = [
    "AT",
    "BE",
    "BG",
    "CY",
    "CZ",
    "DE",
    "DK",
    "EE",
    "ES",
    "FI",
    "FR",
    "GR",
    "HR",
    "HU",
    "IE",
    "IT",
    "LT",
    "LU",
    "LV",
    "MT",
    "NL",
    "PL",
    "PT",
    "RO",
    "SE",
    "SI",
    "SK",
]


@lru_cache(maxsize=4096)
def to_iso2(value: str) -> str | None:
    v = value.strip()
    if not v:
        return None
    low = v.lower().strip(". ")
    if low in _ALIASES:
        return _ALIASES[low]
    if len(v) == 2 and v.isalpha():
        return v.upper() if (pycountry.countries.get(alpha_2=v.upper()) or v.upper() in ("EU", "XK")) else None
    if len(v) == 3 and v.isalpha():
        c = pycountry.countries.get(alpha_3=v.upper())
        return c.alpha_2 if c else None
    try:
        return pycountry.countries.lookup(v).alpha_2
    except LookupError:
        pass
    try:
        hits = pycountry.countries.search_fuzzy(v)
        return hits[0].alpha_2 if len(hits) == 1 else None
    except LookupError:
        return None


def normalize_countries(values: list[str] | str | None) -> list[str]:
    if not values:
        return []
    if isinstance(values, str):
        values = [values]
    parts = [p for v in values for p in re.split(r"[;,|/]", str(v))]
    out: list[str] = []
    for v in parts:
        iso = to_iso2(str(v))
        for c in EU if iso == "EU" else [iso] if iso else []:
            if c not in out:
                out.append(c)
    return out


def country_name(iso2: str) -> str:
    c = pycountry.countries.get(alpha_2=iso2)
    return c.name if c else iso2


def numeric_code(iso2: str) -> str | None:
    c = pycountry.countries.get(alpha_2=iso2)
    return c.numeric if c else None
