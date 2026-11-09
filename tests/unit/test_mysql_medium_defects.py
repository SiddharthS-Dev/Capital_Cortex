"""Regression tests for the Medium MySQL defects M1–M10 and the H10 function-level path
(docs/CORTEX_MYSQL_COMPLETE_OPEN_BLOCKER_AUDIT.md §C). MySQL unit database (MYSQL_TEST_DATABASE=cortex_unit); every
test runs in a transaction that is rolled back."""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.auth.principal import Principal
from platform_core.db.compat import insert_or_skip_duplicate
from platform_core.db.session import create_engine_from_url, get_mysql_test_url, reset_engine
from platform_core.jsonutil import BOOL_COLUMNS, json_obj, jsonable, row

ORG = "00000000-0000-0000-0000-000000000001"
ADMIN = Principal(sub="usr_m_tests", username="m@test", roles=frozenset(["admin"]), token="t")
IST = timezone(timedelta(hours=5, minutes=30))
ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


@pytest.fixture
async def s():
    engine = create_engine_from_url(get_mysql_test_url(driver="asyncmy"), pool_size=2, max_overflow=0)
    reset_engine(engine)
    async with engine.connect() as conn:
        tx = await conn.begin()
        session = AsyncSession(bind=conn, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            await session.close()
            await tx.rollback()
    reset_engine(None)
    await engine.dispose()


# ----------------------------------------------------------------------------- M8 / M9 (no database)
def test_m8_bool_columns_match_the_schema():
    declared = set(re.findall(r"^\s+([a-z_]+) BOOLEAN", _read("scripts/schema_mysql.sql"), re.M))
    assert set(BOOL_COLUMNS) == declared


def test_m8_row_turns_boolean_columns_into_bools_only():
    r = row({"is_demo": 1, "enabled": 0, "count": 1, "active": True, "legal_hold": None, "score": 0})
    assert r == {"is_demo": True, "enabled": False, "count": 1, "active": True, "legal_hold": None, "score": 0}


def test_m9_datetimes_carry_an_offset_and_dates_do_not():
    assert jsonable(datetime(2026, 11, 4, 10, 0)) == "2026-11-04T10:00:00+00:00"  # naive DB value = UTC
    assert jsonable(datetime(2026, 11, 4, 15, 30, tzinfo=IST)) == "2026-11-04T15:30:00+05:30"  # offset preserved
    assert jsonable(date(2026, 11, 4)) == "2026-11-04"
    assert jsonable(None) is None
    emitted = jsonable(datetime(2026, 11, 4, 10, 0))  # browser/API round trip: same instant back
    assert datetime.fromisoformat(emitted) == datetime(2026, 11, 4, 10, 0, tzinfo=UTC)


async def test_m8_m9_on_real_mysql_values(s: AsyncSession):
    r = (
        (
            await s.execute(
                text("SELECT TRUE AS is_demo, FALSE AS enabled, CAST('2026-11-04 10:00:00' AS DATETIME) AS t")
            )
        )
        .mappings()
        .one()
    )
    assert r["is_demo"] == 1 and not isinstance(r["is_demo"], bool)  # what the driver returns
    assert row(r) == {"is_demo": True, "enabled": False, "t": "2026-11-04T10:00:00+00:00"}


# ----------------------------------------------------------------------------- M1
async def test_m1_aware_datetimes_are_stored_as_utc(s: AsyncSession):
    ist = datetime(2026, 11, 4, 15, 30, tzinfo=IST)
    assert (await s.execute(text("SELECT CAST(:d AS DATETIME)"), {"d": ist})).scalar() == datetime(2026, 11, 4, 10, 0)
    naive = datetime(2026, 11, 4, 8, 0)
    assert (await s.execute(text("SELECT CAST(:d AS DATETIME)"), {"d": naive})).scalar() == naive  # unchanged


# ----------------------------------------------------------------------------- M2
async def test_m2_duplicates_skip_but_real_constraint_errors_raise(s: AsyncSession):
    await s.execute(
        text(
            "CREATE TEMPORARY TABLE m2_probe (k VARCHAR(10) NOT NULL PRIMARY KEY, n INT NOT NULL, "
            "CONSTRAINT ck_m2_positive CHECK (n > 0))"
        )
    )
    ins = text("INSERT INTO m2_probe (k, n) VALUES (:k, :n)")
    assert (await insert_or_skip_duplicate(s, ins, {"k": "a", "n": 1})).rowcount == 1
    assert (await insert_or_skip_duplicate(s, ins, {"k": "a", "n": 2})).rowcount == 0  # duplicate: skipped
    with pytest.raises(DBAPIError):
        await insert_or_skip_duplicate(s, ins, {"k": "b", "n": -1})  # CHECK violation is not hidden
    with pytest.raises(DBAPIError):
        await insert_or_skip_duplicate(s, ins, {"k": "c", "n": None})  # NOT NULL violation is not hidden
    rows = (await s.execute(text("SELECT k, n FROM m2_probe ORDER BY k"))).all()
    assert [tuple(r) for r in rows] == [("a", 1)]  # session still usable after the savepoint rollbacks


def test_m2_no_insert_ignore_left_in_application_code():
    hits = [
        str(p.relative_to(ROOT))
        for base in ("cortex", "seed")
        for p in (ROOT / base).rglob("*.py")
        if any(
            "INSERT IGNORE" in line and not line.lstrip().startswith("#")
            for line in p.read_text(encoding="utf-8").splitlines()
        )
    ]
    assert hits == []  # platform_core keeps two deliberate uses (audit_lock seed row, idempotency cache)


# ----------------------------------------------------------------------------- M3
class _Raw:
    payload = {"title": "race"}
    url = "https://example.org/race"
    fetched_at = datetime(2026, 11, 4, tzinfo=UTC)

    def __getattr__(self, _name):
        return None


class _Sig:
    external_id = "race-1"
    source_key = "race"

    def __init__(self, h: str):
        self._h = h

    def content_hash(self) -> str:
        return self._h

    def model_dump_json(self) -> str:
        return json.dumps({"title": "race"})

    def __getattr__(self, _name):
        return None


class _LostRace:
    """Session proxy whose first query (the duplicate pre-check) sees nothing, as when a concurrent ingest commits the
    same content between the check and the insert."""

    def __init__(self, s: AsyncSession):
        self._s, self._first = s, True

    async def execute(self, *a, **k):
        if self._first:
            self._first = False
            return SimpleNamespace(scalar_one_or_none=lambda: None)
        return await self._s.execute(*a, **k)

    def __getattr__(self, name):
        return getattr(self._s, name)


async def test_m3_concurrent_duplicate_is_skipped_not_fatal(s: AsyncSession):
    from cortex.l1_perception.ingestion import _store_signal

    await s.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
    try:
        h, src = uuid.uuid4().hex, str(uuid.uuid4())
        assert await _store_signal(s, src, "t1", _Raw(), _Sig(h))  # inserted
        assert await _store_signal(_LostRace(s), src, "t1", _Raw(), _Sig(h)) is None  # was IntegrityError 1062
        count = (await s.execute(text("SELECT count(*) FROM `signal` WHERE content_hash = :h"), {"h": h})).scalar()
        assert count == 1
    finally:
        await s.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


# ----------------------------------------------------------------------------- M5
async def test_m5_citation_key_with_special_characters(s: AsyncSession):
    rid, key = str(uuid.uuid4()), "tool:terms-compare/1 a"
    await s.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
    try:
        await s.execute(
            text(
                "INSERT INTO agent_run (id, org_id, agent, task, status, output) "
                "VALUES (:id, :org, 'council', 't', 'succeeded', :o)"
            ),
            {"id": rid, "org": ORG, "o": json.dumps({"evidence_pack": {key: {"v": 1}}})},
        )
        sql = "SELECT JSON_EXTRACT(output, CONCAT('$.evidence_pack.', JSON_QUOTE(:k))) FROM agent_run WHERE id = :id"
        assert json.loads((await s.execute(text(sql), {"k": key, "id": rid})).scalar()) == {"v": 1}
        assert "JSON_QUOTE(:k)" in _read("cortex/l7_governance/refs.py")
    finally:
        await s.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


# ----------------------------------------------------------------------------- M7
async def test_m7_settings_version_increments_atomically(s: AsyncSession):
    from cortex.l7_governance import settings_service

    before = await settings_service.get(s, "governance")
    cached = settings_service.current("governance")
    # unchanged value: no side effect. A fresh database has no stored row and an empty cache (load_all runs at app
    # start), so fall back to the empty override, which is what such a database runs with anyway.
    value = (before or {}).get("value") or cached or {}
    try:
        v1 = (await settings_service.put(s, ADMIN, "governance", value))["version"]
        v2 = (await settings_service.put(s, ADMIN, "governance", value))["version"]
        assert v2 == v1 + 1
        stored = (
            await s.execute(text("SELECT version FROM setting WHERE org_id = :o AND `key` = 'governance'"), {"o": ORG})
        ).scalar()
        assert stored == v2
    finally:  # the DB write rolls back with the fixture; put() also updated the in-process cache, so restore it
        settings_service.apply("governance", cached or {})


# ----------------------------------------------------------------------------- M10
def test_m10_calendar_deadlines_are_emitted_as_utc():
    from platform_core.jsonutil import as_utc

    assert 'as_utc(r["deadline"]).isoformat()' in _read("cortex/l8_actuation/api/routers/calendar.py")
    # the ICS writer parses this string with fromisoformat(...).astimezone(UTC): exact with an explicit offset;
    # without one Python assumed the server's local zone (IST: -5:30)
    start = as_utc(datetime(2026, 11, 10, 9, 0)).isoformat()
    assert datetime.fromisoformat(start).astimezone(UTC) == datetime(2026, 11, 10, 9, 0, tzinfo=UTC)


# ----------------------------------------------------------------------------- M6 (run level)
async def test_m6_retention_archives_signal_raw_as_a_document_once_encoded(s: AsyncSession, monkeypatch):
    """M6: on MySQL `signal.raw` comes back as JSON text; json.dumps(r.raw) stored a JSON *string literal* in the cold
    tier. The archived object must decode to the original document, and the row must point at it."""
    from cortex.l7_governance import retention

    stored: dict[str, bytes] = {}

    async def fake_put(bucket, key, data, ctype):  # the object store itself is not under test
        assert bucket == retention.COLD_BUCKET and ctype == "application/json"
        stored[key] = data

    monkeypatch.setattr(retention.objectstore, "put_bytes", fake_put)
    src, sid = str(uuid.uuid4()), str(uuid.uuid4())
    doc = {"title": 'M6 "quoted" / ü', "amount": None, "tags": ["a", "b"], "nested": {"k": 1}}
    await s.execute(
        text("INSERT INTO source (id, org_id, name, kind, adapter_key) VALUES (:id, :org, 'm6', 'manual', :ak)"),
        {"id": src, "org": ORG, "ak": f"m6-{src}"},
    )
    await s.execute(
        text(
            "INSERT INTO `signal` (id, org_id, source_id, raw, content_hash, ingested_at, source_ref) VALUES "
            '(:id, :org, :src, CAST(:raw AS JSON), :h, NOW() - INTERVAL 3650 DAY, CAST(\'{"kind": "test"}\' AS JSON))'
        ),
        {"id": sid, "org": ORG, "src": src, "raw": json.dumps(doc), "h": f"m6-{sid}"},
    )
    out = await retention.run(s, "system:m6-test", dry_run=False, batch=100000)

    assert next(r for r in out["results"] if r["policy"] == "signal")["rows"] >= 1
    archived = json.loads(stored[f"signals/{sid}.json"])
    assert archived == doc and isinstance(archived, dict)  # a document, not a JSON string literal
    after = (await s.execute(text("SELECT raw, raw_key FROM `signal` WHERE id = :id"), {"id": sid})).one()
    assert after.raw is None and after.raw_key == f"s3://{retention.COLD_BUCKET}/signals/{sid}.json"


async def test_m6_retention_dry_run_and_legal_holds_leave_signals_intact(s: AsyncSession, monkeypatch):
    """M6 data integrity: a dry run writes nothing; a signal under legal hold (row flag, or a hold targeting its id) is
    never moved to the cold tier, while an unheld signal of the same age is."""
    from cortex.l7_governance import retention

    stored: dict[str, bytes] = {}

    async def fake_put(bucket, key, data, ctype):
        stored[key] = data

    monkeypatch.setattr(retention.objectstore, "put_bytes", fake_put)
    src = str(uuid.uuid4())
    await s.execute(
        text("INSERT INTO source (id, org_id, name, kind, adapter_key) VALUES (:id, :org, 'm6i', 'manual', :ak)"),
        {"id": src, "org": ORG, "ak": f"m6i-{src}"},
    )
    free, flagged, targeted = (str(uuid.uuid4()) for _ in range(3))
    for sid, flag in ((free, False), (flagged, True), (targeted, False)):
        await s.execute(
            text(
                "INSERT INTO `signal` (id, org_id, source_id, raw, content_hash, ingested_at, legal_hold, source_ref) VALUES "
                '(:id, :org, :src, CAST(:raw AS JSON), :h, NOW() - INTERVAL 3650 DAY, :lh, CAST(\'{"kind": "test"}\' AS JSON))'
            ),
            {"id": sid, "org": ORG, "src": src, "raw": json.dumps({"sid": sid}), "h": f"m6i-{sid}", "lh": flag},
        )
    await s.execute(
        text(
            "INSERT INTO legal_hold (target_table, target_id, reason, created_by) VALUES ('signal', :id, 'm6 test', 'm6')"
        ),
        {"id": targeted},
    )

    async def state(sid: str):
        return (await s.execute(text("SELECT raw, raw_key FROM `signal` WHERE id = :id"), {"id": sid})).one()

    dry = await retention.run(s, "system:m6i-test", dry_run=True, batch=100000)
    sig = next(r for r in dry["results"] if r["policy"] == "signal")
    assert sig["rows"] >= 1 and sig["held"] >= 2
    assert stored == {}  # nothing written to the cold tier
    for sid in (free, flagged, targeted):
        r = await state(sid)
        assert json_obj(r.raw) == {"sid": sid} and r.raw_key is None

    await retention.run(s, "system:m6i-test", dry_run=False, batch=100000)
    assert json.loads(stored[f"signals/{free}.json"]) == {"sid": free}
    assert (await state(free)).raw is None
    for sid in (flagged, targeted):  # held: payload stays in place, nothing archived
        r = await state(sid)
        assert f"signals/{sid}.json" not in stored
        assert json_obj(r.raw) == {"sid": sid} and r.raw_key is None


# ----------------------------------------------------------------------------- H10 (function level)
async def test_h10_ttl_job_archives_the_document_once_encoded(s: AsyncSession, monkeypatch):
    from cortex.l3_memory import memory_manager

    stored: dict[str, bytes] = {}

    async def fake_put(bucket, key, data, ctype):  # the object store itself is not under test
        stored[key] = data

    monkeypatch.setattr(memory_manager.objectstore, "put_bytes", fake_put)
    await s.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
    try:
        mid = str(uuid.uuid4())
        doc = {"note": "warm", "n": None, "items": [1, 2]}
        await s.execute(
            text(
                "INSERT INTO memory (id, org_id, `key`, value, tier, expires_at, source_ref) VALUES (:id, :org, "
                ":k, :v, 'warm', NOW() - INTERVAL 1 DAY, CAST('{\"kind\": \"test\"}' AS JSON))"
            ),
            {"id": mid, "org": ORG, "k": f"m10-{mid}", "v": json.dumps(doc)},
        )
        assert await memory_manager.ttl_job(s, limit=1000) >= 1
        assert json.loads(stored[f"memory/{mid}.json"]) == doc  # a document, not a JSON string literal
    finally:
        await s.execute(text("SET FOREIGN_KEY_CHECKS = 1"))


# ----------------------------------------------------------------------------- M4
def test_m4_merge_keeps_null_keys_and_is_shallow_like_jsonb_concat():
    from cortex.l6_agency.orchestrator import merge_run_output

    old = json.dumps({"a": 1, "nested": {"x": 1, "y": 2}, "keep": True})
    new = json.dumps({"a": None, "nested": {"x": 9}, "convergence_mode": None})
    merged = json.loads(merge_run_output(old, new))
    assert merged == {"a": None, "nested": {"x": 9}, "keep": True, "convergence_mode": None}
    assert json.loads(merge_run_output(None, new)) == json.loads(new)  # NULL column
    assert json.loads(merge_run_output({"k": 1}, new))["k"] == 1  # already-decoded (PostgreSQL) value


async def test_m4_mysql_json_merge_patch_would_drop_the_null_key(s: AsyncSession):
    from cortex.l6_agency.orchestrator import merge_run_output

    old, new = '{"a": 1, "b": 2}', '{"a": null}'
    patched = json.loads((await s.execute(text("SELECT JSON_MERGE_PATCH(:o, :n)"), {"o": old, "n": new})).scalar())
    assert patched == {"b": 2}  # the defect: key "a" disappears
    assert json.loads(merge_run_output(old, new)) == {"a": None, "b": 2}  # the fix keeps it, like jsonb ||
