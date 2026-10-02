"""ECB reference rates → one combined pipeline figure (stored amounts never change currency)."""

from datetime import date
from decimal import Decimal

import pytest

from cortex.l5_strategy.fx import combine, parse_ecb

ECB = """<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
<Cube><Cube time='2026-10-01'><Cube currency='USD' rate='1.1298'/><Cube currency='GBP' rate='0.8600'/>
<Cube currency='JPY' rate='162.50'/></Cube></Cube></gesmes:Envelope>"""


def test_parse_ecb_daily_file():
    day, rates = parse_ecb(ECB)
    assert day == date(2026, 10, 1)
    assert rates == {"EUR": 1, "USD": Decimal("1.1298"), "GBP": Decimal("0.8600"), "JPY": Decimal("162.50")}


def test_parse_rejects_other_documents():
    with pytest.raises(ValueError):
        parse_ecb("<html><body>maintenance</body></html>")


def test_combine_converts_through_eur_cross_rates():
    _, rates = parse_ecb(ECB)
    total, missing = combine({"USD": 1129.80, "EUR": 1000.0, "GBP": 860.0}, "USD", rates)
    assert total == pytest.approx(1129.80 * 3, abs=0.01)  # each leg is worth 1000 EUR
    assert missing == []


def test_combine_reports_currencies_without_a_rate_instead_of_guessing():
    _, rates = parse_ecb(ECB)
    total, missing = combine({"USD": 100.0, "XAF": 5000.0}, "USD", rates)
    assert total == pytest.approx(100.0) and missing == ["XAF"]
    assert combine({"USD": 1.0}, "ZZZ", rates) == (None, ["USD"])
