"""Capital outreach workbook (FR-04-OUT): importer, attributes, taxonomy aliases.

The real workbook in docs/ is read-only test input; edge cases use small workbooks built here.
"""

import io
import re
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from openpyxl import Workbook

from cortex.l1_perception.adapters.tabular import SheetNotFound, read_rows, sheet_names
from cortex.l1_perception.inspect import inspect_upload
from cortex.l1_perception.models import RawItem, Signal
from cortex.l1_perception.normalizer import NormalizationError, normalize
from cortex.l1_perception.registry import SourceConfig, load_configs
from cortex.l2_representation.classifier import classify_rules
from cortex.l2_representation.taxonomy import find

WORKBOOK = Path(__file__).resolve().parents[2] / "docs" / "Meris_Capital_Cortex_Outreach_Workbook_2026-10-06_9405.xlsx"
IMPORT_SHEET = "12_Meris_Import"
OUTREACH_KEYS = {
    "category", "route", "engagement_outlook", "cash_outlook", "relevance", "accessibility", "readiness",
    "priority_score", "country_order", "country_rank", "contact_channel", "official_source_url", "verified_on",
    "programme_status", "next_action", "status", "proposed_owner",
}  # fmt: skip

# Categories the workbook uses (29); D-079 aliases 15 of them. Measured with the rules classifier, 13 of the other 14
# stay unclassified; "Industry / government ecosystem" (CC-044) is classified university_program by the existing
# "incubator" keyword in its own description, not by an alias.
ALIASED = {
    "VC": "venture_equity", "Angel / VC": "venture_equity", "VC / angel platform": "venture_equity",
    "PE": "private_equity",
    "Academia": "university_program", "Academia / incubator": "university_program",
    "Academia / accelerator": "university_program", "Academia / ecosystem": "university_program",
    "Academia / AI ecosystem": "university_program",
    "Government grant": "grant", "Government grant / voucher": "grant",
    "Government RD&D": "government_program", "Government seed fund": "government_program",
    "Government co-investment": "government_program", "State seed support": "government_program",
}  # fmt: skip
UNCLASSIFIED = {
    "Accelerator", "Accelerator / investment support", "Catalytic investment", "Cloud credits", "Corporate accelerator",
    "Government / corporate pilots", "Government / industry network", "Government accelerator", "Industry consortium",
    "Industry consortium / research", "Utility / ESCO partner", "Utility programme", "VC / ecosystem",
}  # fmt: skip


@pytest.fixture(scope="module")
def workbook() -> bytes:
    return WORKBOOK.read_bytes()


@pytest.fixture(scope="module")
def cfgs() -> dict[str, SourceConfig]:
    return load_configs()


def _run(cfg: SourceConfig, rows: list[dict]) -> tuple[list[Signal], Counter]:
    ok, failed = [], Counter()
    for n, r in enumerate(rows):
        payload = {"_row": r.pop("_row", n + 2), **r}
        try:
            ok.append(normalize(cfg, RawItem(payload=payload, url=f"upload://w#row={n}", fetched_at=datetime.now(UTC))))
        except NormalizationError as e:
            failed[str(e)] += 1
    return ok, failed


@pytest.fixture(scope="module")
def signals(workbook, cfgs) -> list[Signal]:
    cfg = cfgs["capital_outreach"]
    sigs, failed = _run(cfg, read_rows(workbook, WORKBOOK.name, cfg.sheet, with_meta=True))
    assert not failed
    return sigs


def _xlsx(sheets: dict[str, list[list]]) -> bytes:
    wb = Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for r in rows:
            ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ----------------------------------------------------------------------------------------- baseline regression
def test_baseline_default_sheet_is_read_me_and_its_rows_are_rejected(workbook, cfgs):
    # measured before the change: csv_upload read the first sheet (00_Read_Me) and imported 0 / 16
    rows = read_rows(workbook, WORKBOOK.name)
    assert len(rows) == 16 and "Topic" in rows[0]
    _, failed = _run(cfgs["csv_upload"], rows)
    assert failed == Counter({"mapping produced no title": 16})
    # the outreach source rejects them too, with a named reason
    _, failed = _run(cfgs["capital_outreach"], read_rows(workbook, WORKBOOK.name, "00_Read_Me"))
    assert failed == Counter({"not a Capital Cortex import row": 16})


def test_baseline_import_sheet_imports_all_52(workbook, cfgs, signals):
    assert cfgs["capital_outreach"].sheet == IMPORT_SHEET
    assert len(signals) == 52
    assert len({s.external_key for s in signals}) == 52
    # csv_upload alone still can't read it (no title header): the behaviour of the generic source is unchanged
    _, failed = _run(cfgs["csv_upload"], read_rows(workbook, WORKBOOK.name, IMPORT_SHEET))
    assert failed == Counter({"mapping produced no title": 52})


def test_missing_sheet_names_the_available_ones(workbook):
    with pytest.raises(SheetNotFound) as e:
        read_rows(workbook, WORKBOOK.name, "13_Nope")
    assert "sheet '13_Nope' not found; available: ['00_Read_Me'" in str(e.value)
    assert sheet_names(workbook, WORKBOOK.name)[12] == IMPORT_SHEET and len(e.value.available) == 14
    assert sheet_names(b"a,b\n1,2\n", "x.csv") == []


def test_default_sheet_and_plain_rows_unchanged_without_meta():
    data = _xlsx({"First": [["title", "amount"], ["A", 5], [None, None], ["B", 6]], "Second": [["title"], ["Z"]]})
    assert read_rows(data, "f.xlsx") == [{"title": "A", "amount": 5}, {"title": "B", "amount": 6}]
    assert [r["_row"] for r in read_rows(data, "f.xlsx", with_meta=True)] == [2, 4]  # real sheet rows
    assert read_rows(data, "f.xlsx", "Second") == [{"title": "Z"}]


# ----------------------------------------------------------------------------------------- signals
def test_every_signal_carries_identity_and_outreach_attributes(signals):
    for s in signals:
        assert re.fullmatch(r"CC-0\d\d", s.external_id or "") and s.external_key == f"capital_outreach:{s.external_id}"
        assert s.title and s.countries and s.url and s.url.startswith("https://")
        assert set(s.attributes) == OUTREACH_KEYS, s.external_id
        for k in OUTREACH_KEYS:
            assert s.field_sources[f"attributes.{k}"].startswith("raw:"), (s.external_id, k)
        assert isinstance(s.attributes["verified_on"], date) and s.attributes["verified_on"] == date(2026, 10, 6)
        assert all(isinstance(s.attributes[k], int) for k in ("relevance", "accessibility", "readiness"))
        assert "gate" in s.eligibility
    assert Counter(c for s in signals for c in s.countries) == Counter({"US": 18, "AE": 12, "SG": 11, "IN": 11})


def test_no_amount_currency_or_deadline_is_ever_imported(signals):
    # I1 + cash discipline: published benefits are text, contact windows are not deadlines
    for s in signals:
        assert s.amount_min is None and s.amount_max is None and s.currency is None
        assert s.deadline is None and s.open_date is None
        assert not {"amount_min", "amount_max", "currency", "deadline", "open_date"} & set(s.field_sources)


def test_attributes_take_part_in_the_content_hash(signals):
    s = signals[0]
    changed = s.model_copy(update={"attributes": {**s.attributes, "route": "Watch next intake"}})
    assert changed.content_hash() != s.content_hash()


def test_existing_sources_keep_their_content_hashes():
    # a signal without attributes hashes exactly as before the field existed, so a re-poll of any existing source
    # doesn't turn every stored signal into "new"
    import hashlib
    import json

    sig = Signal(
        source_key="grants_gov", external_id="1", title="T", countries=["US"], field_sources={"title": "raw:t"}
    )
    body = sig.model_dump(mode="json", exclude={"field_sources", "attributes"})
    legacy = hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
    assert sig.content_hash() == legacy


def test_adapter_mapping_matches_the_real_27_headers(workbook, cfgs):
    report = inspect_upload(cfgs["capital_outreach"], workbook, WORKBOOK.name)
    assert report["sheet"] == IMPORT_SHEET and len(report["headers"]) == 27
    assert report["unmapped_headers"] == [] and report["required_missing"] == []
    assert all(f["matched"] for f in report["fields"])
    assert (report["rows"], report["would_import"], report["would_fail"]) == (52, 52, 0)
    assert report["preview"][0] == {
        **report["preview"][0],
        "ok": True,
        "external_id": "CC-001",
        "title": "AWS Activate",
    }
    assert len(report["preview"]) == 5


def test_inspect_reports_missing_title_for_the_generic_source(workbook, cfgs):
    report = inspect_upload(cfgs["csv_upload"], workbook, WORKBOOK.name)
    assert report["sheet"] == "00_Read_Me" and report["required_missing"] == ["title"]
    assert report["would_import"] == 0 and report["preview"][0]["error"] == "mapping produced no title"
    with pytest.raises(SheetNotFound):
        inspect_upload(cfgs["csv_upload"], workbook, WORKBOOK.name, "missing")


# ----------------------------------------------------------------------------------------- row guards
def _outreach_rows(*rows: list) -> bytes:
    header = ["prospect_id", "engine", "module", "organization", "country", "priority_score"]
    return _xlsx({IMPORT_SHEET: [header, *rows]})


def test_require_values_guard(cfgs):
    data = _outreach_rows(
        ["CC-900", "Meris", "Capital Cortex", "Org A", "USA", 50],
        ["CC-901", "Other", "Capital Cortex", "Org B", "USA", 50],
        ["CC-902", "meris", "capital cortex", "Org C", "USA", 50],  # values compare case-insensitively
        ["CC-903", "Meris", None, "Org D", "USA", 50],
    )
    sigs, failed = _run(cfgs["capital_outreach"], read_rows(data, "w.xlsx", IMPORT_SHEET, with_meta=True))
    assert [s.external_id for s in sigs] == ["CC-900", "CC-902"]
    assert failed == Counter({"not a Capital Cortex import row": 2})


def test_formula_without_cached_value_fails_only_that_row(cfgs):
    # openpyxl writes formulas without cached values (as an app that never computed them would)
    data = _outreach_rows(
        ["CC-910", "Meris", "Capital Cortex", "Org A", "USA", 40],
        ["CC-911", "Meris", "Capital Cortex", "Org B", "USA", "=5*10+3*6+2*4"],
        ["CC-912", "Meris", "Capital Cortex", "Org C", "USA", 70],
    )
    rows = read_rows(data, "w.xlsx", IMPORT_SHEET, with_meta=True)
    assert rows[1]["_uncached_formula"] == ["priority_score"] and rows[1]["priority_score"] is None
    sigs, failed = _run(cfgs["capital_outreach"], rows)
    assert [s.external_id for s in sigs] == ["CC-910", "CC-912"]
    (reason,) = failed
    assert reason.startswith("formula without a cached value in priority_score")
    assert read_rows(data, "w.xlsx", IMPORT_SHEET)[1] == {  # plain readers see the blank, not the formula
        "prospect_id": "CC-911", "engine": "Meris", "module": "Capital Cortex", "organization": "Org B",
        "country": "USA", "priority_score": None,
    }  # fmt: skip


# ----------------------------------------------------------------------------------------- taxonomy (D-079)
def test_aliased_categories_classify_to_their_class(signals):
    seen = set()
    for s in signals:
        cat = s.attributes["category"]
        if cat in ALIASED:
            c = classify_rules(s)
            assert c.capital_class == ALIASED[cat], (s.external_id, cat, c.rationale)
            assert any(e["signal"] == "class_hint" for e in c.evidence)
            seen.add(cat)
    assert seen == set(ALIASED)


def test_non_cash_categories_stay_unclassified(signals):
    unclassified = {s.attributes["category"] for s in signals if classify_rules(s).capital_class is None}
    assert unclassified == UNCLASSIFIED
    assert sum(1 for s in signals if classify_rules(s).capital_class is None) == 20
    by_id = {s.external_id: s for s in signals}
    assert classify_rules(by_id["CC-044"]).capital_class == "university_program"  # keyword "incubator", not an alias


def test_negated_keywords_are_not_evidence():
    # D-085: "no direct grant" / "not guaranteed grant" (CC-020 / CC-010) were classified grant before
    assert find("Retrofit network; no direct grant", ["grant"], skip_negated=True) == []
    assert find("Mentoring; not guaranteed grant", ["grant"], skip_negated=True) == []
    assert find("without a grant", ["grant"], skip_negated=True) == []
    assert find("non-dilutive grant", ["grant", "non-dilutive"], skip_negated=True) == ["grant", "non-dilutive"]
    assert find("a grant, not a loan", ["grant"], skip_negated=True) == ["grant"]
    assert find("no direct grant", ["grant"]) == ["grant"]  # default unchanged for other callers
    sig = Signal(source_key="x", title="Cleantech Open", description="Mentoring / competition; not guaranteed grant")
    assert classify_rules(sig).capital_class is None


# ----------------------------------------------------------------------------------------- outreach profile (step 2)
def test_real_rows_give_clean_research_values(signals):
    from cortex.l2_representation.outreach_writer import is_outreach, research_values

    for s in signals:
        assert is_outreach(s)
        v = research_values(s)
        assert v["research_warnings"] == [] and v["priority_inconsistent"] is False, s.external_id
        assert v["prospect_id"] == s.external_id and v["verified_on"] == date(2026, 10, 6)
        assert v["analyst_priority"] == s.attributes["priority_score"]
    assert not is_outreach(Signal(source_key="grants_gov", title="A grant"))


def test_priority_is_recomputed_and_a_disagreement_is_flagged_not_fixed():
    from cortex.l2_representation.outreach_writer import priority, research_values

    assert priority({"relevance": 5, "accessibility": 4, "readiness": 4, "priority_score": 90}) == (90, 90, False)
    assert priority({"relevance": 5, "accessibility": 4, "readiness": 4, "priority_score": 95}) == (95, 90, True)
    assert priority({"relevance": 5, "priority_score": 95}) == (95, None, False)  # can't recompute: not flagged
    sig = Signal(
        source_key="capital_outreach",
        external_id="CC-999",
        title="X",
        attributes={"route": "Contact now", "relevance": 5, "accessibility": 4, "readiness": 4, "priority_score": 95},
    )
    v = research_values(sig)
    assert v["analyst_priority"] == 95 and v["priority_inconsistent"] is True  # the stated value is kept


def test_values_outside_the_workbook_vocabulary_become_warnings_not_guesses():
    from cortex.l2_representation.outreach_writer import research_values

    sig = Signal(
        source_key="capital_outreach",
        external_id="CC-998",
        title="X",
        attributes={"route": "Call them", "engagement_outlook": "Huge", "relevance": 7, "verified_on": "soon"},
    )
    v = research_values(sig)
    assert v["route"] is None and v["engagement_outlook"] is None and v["relevance"] is None
    assert v["verified_on"] is None
    assert {w["field"] for w in v["research_warnings"]} == {"route", "engagement_outlook", "relevance", "verified_on"}


@pytest.mark.parametrize(
    ("channel", "emails", "phones", "person"),
    [
        ("info@colab.is | +1 423-281-0811", ["info@colab.is"], ["+1 423-281-0811"], None),
        ("Darrel Hugh | dhugh@ahla.com", ["dhugh@ahla.com"], [], "Darrel Hugh"),
        ("AWS Activate application team", [], [], None),
        ("Business inquiry via official contact page", [], [], None),
        ("ors@ku.ac.ae (research) | ip@ku.ac.ae (licensing)", ["ors@ku.ac.ae", "ip@ku.ac.ae"], [], None),
        ("Sunil Kumar Verma | sk.verma@beeindia.gov.in | 011-26766700", ["sk.verma@beeindia.gov.in"], ["011-26766700"],
         "Sunil Kumar Verma"),
        ("Mumbai office +91 22 4043 6000", [], ["+91 22 4043 6000"], None),
        ("Pitch team via official contact form; warm intro preferred", [], [], None),
        (None, [], [], None),
    ],
)  # fmt: skip
def test_contact_channel_parser_on_the_workbook_strings(channel, emails, phones, person):
    from cortex.l2_representation.outreach_writer import parse_contact_channel

    out = parse_contact_channel(channel)
    assert [e["email"] for e in out["emails"]] == emails
    assert out["phones"] == phones and out["person"] == person
