"""Exchange rates (FR-07): daily ECB euro reference rates → one combined weighted-pipeline figure.

Stored amounts never change currency. A combined total is a display figure that names its rate date and source;
any currency without a rate is reported as missing rather than guessed.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from cortex.l1_perception.adapters.base import FetchContext
from platform_core.config import get_settings

ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
SOURCE = "ECB euro foreign exchange reference rates"
# The file is a fixed, flat format; matching its two attribute shapes avoids an XML parser (and XXE) entirely.
_TIME = re.compile(r"<Cube\s+time=['\"](\d{4}-\d{2}-\d{2})['\"]")
_RATE = re.compile(r"<Cube\s+currency=['\"]([A-Z]{3})['\"]\s+rate=['\"]([0-9]+(?:\.[0-9]+)?)['\"]")


def parse_ecb(xml: str) -> tuple[date, dict[str, Decimal]]:
    """Return (rate date, {currency: units per 1 EUR}). EUR itself is 1."""
    m = _TIME.search(xml)
    rates = {c: Decimal(r) for c, r in _RATE.findall(xml)}
    if m is None or not rates:
        raise ValueError("not an ECB daily reference-rate file")
    return date.fromisoformat(m.group(1)), {"EUR": Decimal(1), **rates}


async def refresh(s: AsyncSession) -> dict[str, Any]:
    """Fetch today's ECB file and upsert it (idempotent per rate date)."""
    ctx = FetchContext(min_interval_seconds=0, respect_robots=False, timeout=30)
    try:
        r = await ctx.request("GET", ECB_URL)
    finally:
        await ctx.aclose()
    day, rates = parse_ecb(r.text)
    await s.execute(
        text(
            "INSERT INTO fx_rate (org_id, rate_date, base, quote, rate, source) "
            "SELECT :org, :d, 'EUR', q, r, :src FROM unnest(CAST(:q AS text[]), CAST(:r AS numeric[])) AS t(q, r) "
            "ON CONFLICT (org_id, rate_date, base, quote) DO UPDATE SET rate = EXCLUDED.rate"
        ),
        {
            "org": get_settings().org_id,
            "d": day,
            "src": SOURCE,
            "q": list(rates),
            "r": [str(v) for v in rates.values()],
        },
    )
    return {"rate_date": day.isoformat(), "currencies": len(rates)}


async def latest_rates(s: AsyncSession) -> tuple[date | None, dict[str, Decimal]]:
    rows = (
        await s.execute(
            text(
                "SELECT rate_date, quote, rate FROM fx_rate WHERE org_id = :org AND base = 'EUR' AND rate_date = "
                "(SELECT max(rate_date) FROM fx_rate WHERE org_id = :org AND base = 'EUR')"
            ),
            {"org": get_settings().org_id},
        )
    ).all()
    if not rows:
        return None, {}
    return rows[0].rate_date, {r.quote.strip(): Decimal(r.rate) for r in rows}


def combine(totals: dict[str, float], target: str, rates: dict[str, Decimal]) -> tuple[float | None, list[str]]:
    """Sum per-currency totals in ``target`` via EUR cross rates. Returns (total, currencies without a rate)."""
    if target not in rates:
        return None, sorted(totals)
    missing = sorted(c for c in totals if c not in rates)
    total = sum((Decimal(str(v)) / rates[c] * rates[target] for c, v in totals.items() if c in rates), Decimal(0))
    return round(float(total), 2), missing
