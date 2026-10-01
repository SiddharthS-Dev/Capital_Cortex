"""Mapping, normalizer, tabular reader, classifier, typer, resolver, embeddings, geo."""

from datetime import UTC, datetime

from cortex.l1_perception.adapters.tabular import read_rows
from cortex.l1_perception.mapping import get_path, resolve, to_number
from cortex.l1_perception.models import RawItem, Signal
from cortex.l1_perception.normalizer import normalize
from cortex.l1_perception.registry import load_configs
from cortex.l2_representation.classifier import classify_rules
from cortex.l2_representation.entity_resolver import normalize_name, similarity
from cortex.l2_representation.typer import type_signal
from platform_core.embeddings import cosine, embed
from platform_core.geo import normalize_countries, to_iso2

# Recorded (trimmed) Grants.gov search hit + fetchOpportunity detail, 2026-09-29.
GRANTS_GOV_ITEM = {
    "id": "359671",
    "number": "PA-27-100",
    "title": "NIH, CDC and FDA Small Business Innovation Research Grant (Parent SBIR [R43/R44] Clinical Trial Optional)",
    "agency": "National Institutes of Health",
    "openDate": "05/28/2026",
    "closeDate": "04/05/2027",
    "opportunityTitle": "NIH, CDC and FDA Small Business Innovation Research Grant (Parent SBIR [R43/R44] Clinical Trial Optional)",
    "synopsis": {
        "agencyName": "National Institutes of Health",
        "synopsisDesc": "<p>The Small Business Innovation Research (SBIR) program helps United States small "
        "businesses &amp;nbsp;develop health technologies.</p>",
        "responseDate": "Apr 05, 2027 12:00:00 AM EDT",
        "postingDate": "May 28, 2026 12:00:00 AM EDT",
        "awardCeiling": "none",
        "awardFloor": "none",
        "applicantEligibilityDesc": "Only United States small business concerns (SBCs)",
        "fundingActivityCategories": [{"id": "HL", "description": "Health"}],
        "fundingInstruments": [{"id": "G", "description": "Grant"}],
    },
}


def test_get_path_fanout_and_index():
    d = {"a": [{"b": 1}, {"b": 2}], "c": {"d": [5, 6]}}
    assert get_path(d, "a[*].b") == [1, 2]
    assert get_path(d, "c.d[1]") == 6
    assert get_path(d, "missing.x") is None


def test_resolve_fallback_and_template():
    assert resolve({"x": "", "y": "v"}, ["x", "y"]) == ("v", "raw:y")
    assert resolve({"id": 7}, {"template": "https://g/{id}"})[0] == "https://g/7"
    assert resolve({}, {"value": "USD"}) == ("USD", "source_default")
    assert to_number("$1,250,000") == 1250000 and to_number("none") is None


def test_grants_gov_normalization():
    cfg = load_configs()["grants_gov"]
    sig = normalize(cfg, RawItem(payload=GRANTS_GOV_ITEM, url="https://api.grants.gov", fetched_at=datetime.now(UTC)))
    assert sig.external_id == "359671" and sig.external_key == "grants_gov:359671"
    assert sig.counterparty_name == "National Institutes of Health"
    assert sig.deadline and sig.deadline.year == 2027
    assert sig.amount_max is None  # "none" is not a number and is never imputed
    assert "&" not in (sig.description or "") and "<p>" not in (sig.description or "")
    assert sig.countries == ["US"] and sig.field_sources["countries"] == "source_default"
    assert sig.field_sources["deadline"] == "raw:synopsis.responseDate"
    assert sig.eligibility["text"].startswith("Only United States")
    assert sig.url == "https://www.grants.gov/search-results-detail/359671"


def test_content_hash_changes_with_content_only():
    a = Signal(source_key="s", title="T", description="d", field_sources={"title": "raw:x"})
    b = Signal(source_key="s", title="T", description="d", field_sources={"title": "raw:y"})
    c = Signal(source_key="s", title="T", description="d2")
    assert a.content_hash() == b.content_hash() != c.content_hash()


def test_tabular_csv_and_normalize():
    csv = (
        b"Title,Organization,Country,Deadline,Amount Max,Currency,Class\n"
        b"Seed round for climate AI,Veltaris Ventures,Germany,2027-01-15,2000000,EUR,venture equity\n,,,,,,\n"
    )
    rows = read_rows(csv, "list.csv")
    assert len(rows) == 1
    cfg = load_configs()["csv_upload"]
    sig = normalize(cfg, RawItem(payload=rows[0], url="upload://list.csv#row=2", fetched_at=datetime.now(UTC)))
    assert sig.countries == ["DE"] and sig.amount_max == 2000000 and sig.currency == "EUR"
    assert sig.counterparty_name == "Veltaris Ventures" and sig.class_hint == "venture equity"


def test_classifier_rules():
    grant = classify_rules(
        Signal(
            source_key="g",
            title="Small Business Innovation Research Grant",
            class_hint="grant",
            field_sources={"class_hint": "source_default"},
        )
    )
    assert grant.capital_class == "grant" and grant.confidence >= 0.7
    vc = classify_rules(
        Signal(source_key="c", title="Series A equity round", description="venture capital fund", investor_type="vc")
    )
    assert vc.capital_class == "venture_equity"
    debt = classify_rules(Signal(source_key="c", title="Venture debt term loan facility"))
    assert debt.capital_class == "debt_facility"
    none = classify_rules(Signal(source_key="c", title="Quarterly newsletter"))
    assert none.capital_class is None and none.confidence == 0


def test_ambiguous_programme_reports_low_confidence_and_runner_up():
    # An SBIR award from an agency is both a government programme and a grant: the rules say so, not guess.
    r = classify_rules(
        Signal(
            source_key="g",
            title="NSF SBIR Phase I",
            counterparty_kind="agency",
            class_hint="grant",
            field_sources={"class_hint": "source_default"},
        )
    )
    assert {r.capital_class, r.runner_up} == {"government_program", "grant"} and r.confidence < 0.7


def test_typer_tags():
    t = type_signal(
        Signal(
            source_key="s",
            title="Clean energy storage with machine learning",
            description="Decarbonization of grids; solar and wind",
            stage_fit=["Seed"],
        )
    )
    assert "climate_energy" in t.sectors and "ai_data" in t.sectors
    assert "clean_energy" in t.esg and "SDG7" in t.sdg and "seed" in t.stages


def test_resolver_normalization_and_similarity():
    assert normalize_name("The Northwind Climate Fund, Inc.") == "northwind climate fund"
    s, _ = similarity(normalize_name("Northwind Climate Fund LLC"), normalize_name("Northwind Climate Fund"))
    assert s >= 0.92
    s2, ev = similarity("northwind climate fund", "northwind climate fund", "US", "DE")
    assert s2 < 0.92 and ev["country_conflict"] == ["US", "DE"]
    assert similarity("a", "b", a_domain="x.com", b_domain="X.com")[0] == 1.0


def test_embeddings_are_deterministic_and_similar():
    a, b, c = embed("clean energy storage"), embed("energy storage for clean grids"), embed("medieval poetry")
    assert a == embed("clean energy storage")
    assert cosine(a, b) > cosine(a, c)
    assert abs(sum(x * x for x in a) - 1.0) < 1e-9


def test_geo():
    assert to_iso2("Germany") == "DE" and to_iso2("USA") == "US" and to_iso2("gbr") == "GB"
    assert normalize_countries("EU")[:2] == ["AT", "BE"] and "FR" in normalize_countries(["EU"])
    assert normalize_countries(["India; United Kingdom"]) == ["IN", "GB"]
