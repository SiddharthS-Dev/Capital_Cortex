"""Value-level regression tests for the High MySQL defects H8 (tool_registry JSON fields) and H11 (data-room manifest and
proposal DD export ``dd_tags``) — blocker VER-3.

On MySQL a JSON column arrives as text. Before the fix these call sites iterated / tested membership on that text, so they
compared characters, not elements (``"series" in '["series_a"]'`` is True; ``set('["ip"]')`` is a set of characters).
The earlier test (HX-01) only proved the stored values decode to the right Python type. These tests run the real functions
against real MySQL rows and assert the business values they return.

MySQL unit database (MYSQL_TEST_DATABASE=cortex_unit); every test runs in a transaction that is rolled back."""

from __future__ import annotations

import hashlib
import io
import json
import uuid
import zipfile
from datetime import UTC, datetime

import pytest
import yaml
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.db.session import create_engine_from_url, get_mysql_test_url, reset_engine
from platform_core.jsonutil import json_obj

ORG = "00000000-0000-0000-0000-000000000001"
ADMIN = Principal(sub="usr_h8h11", username="h8h11@test", roles=frozenset(["admin"]), token="t")
SRC = json.dumps({"kind": "test", "ref": "h8h11"})


@pytest.fixture
async def s():
    engine = create_engine_from_url(get_mysql_test_url(driver="asyncmy"), pool_size=2, max_overflow=0)
    reset_engine(engine)
    async with engine.connect() as conn:
        tx = await conn.begin()
        session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint")
        # parent rows (counterparty organisation) are not needed for these reads; CHECK constraints still apply
        await session.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        try:
            yield session
        finally:
            await session.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
            await session.close()
            await tx.rollback()
    reset_engine(None)
    await engine.dispose()


def _ctx(s: AsyncSession, opp: dict, me: dict | None = None):
    from cortex.l6_agency.tool_registry import ToolContext

    return ToolContext(s, ADMIN, {"is_demo": False, **opp}, str(uuid.uuid4()), me, datetime.now(UTC))


def _checklist_tags() -> dict[str, list[str]]:
    items = yaml.safe_load((get_settings().config_dir / "dd_checklist.yaml").read_text(encoding="utf-8"))["items"]
    return {i["key"]: i["tags"] for i in items}


async def _document(s: AsyncSession, title: str, tags: list[str], *, approved: bool, data: bytes = b"x") -> str:
    did = str(uuid.uuid4())
    await s.execute(
        text(
            "INSERT INTO document (id, org_id, kind, title, folder, filename, storage_key, checksum, classification, dd_tags, "
            "approved_repo, is_latest, is_demo, source_ref) VALUES (:id, :org, 'report', :t, '/h8h11', :fn, :k, :c, "
            "'confidential', :tags, :ap, TRUE, FALSE, :src)"
        ),
        {
            "id": did,
            "org": ORG,
            "t": title,
            "fn": f"{title}.pdf",
            "k": f"test/{did}",
            "c": hashlib.sha256(data).hexdigest(),
            "tags": json.dumps(tags),
            "ap": approved,
            "src": SRC,
        },
    )
    return did


# ============================================================================ H8: tool_registry
async def test_h8_eligibility_check_returns_the_programme_eligibility_document(s: AsyncSession):
    from cortex.l6_agency.tool_registry import eligibility_check

    gid = str(uuid.uuid4())
    elig = {"min_trl": 4, "sectors": ["energy", "mobility"], "sme_only": True}
    await s.execute(
        text(
            "INSERT INTO grant_program (id, org_id, title, eligibility, source_ref) VALUES (:id, :org, 'H8 programme', :e, :src)"
        ),
        {"id": gid, "org": ORG, "e": json.dumps(elig), "src": SRC},
    )
    r = await eligibility_check(
        _ctx(
            s,
            {"id": str(uuid.uuid4()), "grant_program_id": gid, "geography": ["IN", "SG"]},
            {"id": ORG, "country": "IN"},
        )
    )
    assert r.data["program_eligibility"] == elig  # the object itself, not its JSON text
    assert r.data["eligible"] is True and "geographically eligible" in r.support
    # the human-check gap names the eligibility fields; sorted() of the JSON text listed characters (' ', '"', ...)
    assert "Programme-specific eligibility fields exist and need a human check: min_trl, sectors, sme_only" in r.gaps


async def test_h8_investor_search_compares_stages_as_elements_not_characters(s: AsyncSession):
    from cortex.l6_agency.tool_registry import investor_search

    cp, inv = str(uuid.uuid4()), str(uuid.uuid4())
    await s.execute(
        text(
            "INSERT INTO investor (id, org_id, organization_id, investor_type, stages, geos, ticket_min, ticket_max, currency, "
            "source_ref) VALUES (:id, :org, :cp, 'vc', :st, :ge, 250000, 2000000, 'USD', :src)"
        ),
        {
            "id": inv,
            "org": ORG,
            "cp": cp,
            "st": json.dumps(["seed", "series_a"]),
            "ge": json.dumps(["IN", "SG"]),
            "src": SRC,
        },
    )
    opp = {"id": str(uuid.uuid4()), "counterparty_id": cp, "counterparty_name": "H8 Ventures"}

    hit = await investor_search(_ctx(s, opp, {"id": ORG, "profile": {"stage": "seed"}}))
    x = hit.data["investors"][0]
    assert x["stages"] == ["seed", "series_a"] and x["geos"] == ["IN", "SG"]
    assert "investing at seed, series_a" in hit.facts[0]["text"]  # on text it would join characters
    assert "stage in the investor's stated stages" in hit.support

    # "series" is a substring of the stored JSON text but not one of its elements: the old code matched it
    miss = await investor_search(_ctx(s, opp, {"id": ORG, "profile": {"stage": "series"}}))
    assert "stage in the investor's stated stages" not in miss.support
    assert any(f["text"] == "Our stage (series) is not among its stated stages." for f in miss.facts)


async def test_h8_terms_compare_computes_the_peer_median_from_decoded_terms(s: AsyncSession):
    from cortex.l6_agency.tool_registry import terms_compare

    key = f"h8_rate_{uuid.uuid4().hex[:6]}"  # a key only these peers carry, so other rows can't move the median
    for rate in (0.05, 0.07, 0.11):
        fi = str(uuid.uuid4())
        await s.execute(
            text(
                "INSERT INTO financial_instrument (id, org_id, class, terms, source_ref) VALUES (:id, :org, 'debt_facility', :t, :src)"
            ),
            {"id": fi, "org": ORG, "t": json.dumps({key: rate, "collateral": "none"}), "src": SRC},
        )
        await s.execute(
            text(
                "INSERT INTO opportunity (id, org_id, title, class, instrument_id, is_demo, source_ref) "
                "VALUES (:id, :org, 'H8 peer', 'debt_facility', :fi, FALSE, :src)"
            ),
            {"id": str(uuid.uuid4()), "org": ORG, "fi": fi, "src": SRC},
        )
    peers_in_class = (
        await s.execute(
            text(
                "SELECT COUNT(*) FROM opportunity o JOIN financial_instrument fi ON fi.id = o.instrument_id "
                "WHERE o.class = 'debt_facility' AND o.is_demo = FALSE"
            )
        )
    ).scalar()
    if peers_in_class > 200:
        pytest.skip("more than 200 peers in class: the tool's LIMIT 200 may exclude the probe rows")

    r = await terms_compare(_ctx(s, {"id": str(uuid.uuid4()), "class": "debt_facility", "terms": {key: 0.06}}))
    assert r.data["peer_median"] == {key: 0.07}  # median(0.05, 0.07, 0.11)
    assert r.data["peers"] == peers_in_class
    assert f"Term {key} is 0.06 against a peer median of 0.07" in r.facts[0]["text"]


async def test_h8_checklist_map_marks_items_covered_by_approved_document_tags(s: AsyncSession):
    from cortex.l6_agency.tool_registry import checklist_map

    await _document(s, f"H8 accounts {uuid.uuid4().hex[:6]}", ["financials", "accounts"], approved=True)
    await _document(s, f"H8 caps {uuid.uuid4().hex[:6]}", ["cap_table"], approved=True)
    r = await checklist_map(_ctx(s, {"id": str(uuid.uuid4())}))
    covered = {i["key"]: i["covered"] for i in r.data["items"]}
    assert covered["financials"] is True and covered["cap_table"] is True

    # independent oracle: MySQL's own JSON_OVERLAPS over every approved non-demo document, per checklist item
    tags = _checklist_tags()
    for item in r.data["items"]:
        expected = (
            await s.execute(
                text(
                    "SELECT EXISTS (SELECT 1 FROM document WHERE org_id = :org AND approved_repo AND is_demo = FALSE "
                    "AND JSON_OVERLAPS(dd_tags, CAST(:t AS JSON)))"
                ),
                {"org": ORG, "t": json.dumps(tags[item["key"]])},
            )
        ).scalar()
        assert item["covered"] is bool(expected), item["key"]
    assert r.data["missing"] == sum(1 for i in r.data["items"] if not i["covered"])


# ============================================================================ H11: data room and proposal DD export
async def test_h11_dataroom_manifest_records_dd_tags_as_a_list(s: AsyncSession, monkeypatch):
    from cortex.l8_actuation import dataroom

    data = b"%PDF H11 manifest probe"
    stored: dict[str, bytes] = {}

    async def get_bytes(_bucket: str, _key: str) -> bytes:
        return data

    async def put_bytes(_bucket: str, key: str, blob: bytes, _ctype: str) -> None:
        stored[key] = blob

    monkeypatch.setattr(dataroom.objectstore, "get_bytes", get_bytes)
    monkeypatch.setattr(dataroom.objectstore, "put_bytes", put_bytes)
    did = await _document(s, f"H11 pack {uuid.uuid4().hex[:6]}", ["financials", "legal"], approved=True, data=data)

    pkg = await dataroom.assemble(s, ADMIN, "H11 package", [did], None, False)

    q = "SELECT manifest, JSON_TYPE(JSON_EXTRACT(manifest, '$.files[0].dd_tags')) AS t FROM dataroom_package WHERE id = :id"
    stored_row = (await s.execute(text(q), {"id": pkg["id"]})).mappings().one()
    assert json_obj(stored_row["manifest"])["files"][0]["dd_tags"] == ["financials", "legal"]
    assert stored_row["t"] == "ARRAY"  # a double-encoded value would be STRING
    (blob,) = stored.values()
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        assert json.loads(z.read("MANIFEST.json"))["files"][0]["dd_tags"] == ["financials", "legal"]


async def test_h11_proposal_dd_items_map_documents_by_tag_element(s: AsyncSession):
    from cortex.l8_actuation.proposals import _dd_items

    title = f"H11 patents {uuid.uuid4().hex[:6]}"
    await _document(s, title, ["ip", "patents"], approved=False)
    items = {i["key"]: i for i in await _dd_items(s, False)}
    mine = [d for d in items["ip"]["documents"] if d["title"] == title]
    assert len(mine) == 1 and not mine[0]["approved"]
    # the document maps to the "ip" item only (character matching would map it nowhere)
    assert all(title not in [d["title"] for d in i["documents"]] for k, i in items.items() if k != "ip")
