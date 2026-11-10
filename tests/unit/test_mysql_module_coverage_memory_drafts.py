"""MySQL coverage for four modules that had no MySQL tests (docs/archive/migration-history/CORTEX_MYSQL_COMPLETE_OPEN_BLOCKER_AUDIT.md §D rows
5, 6, 8, 18): l3_memory.consolidation_job, l3_memory.interaction_ingest, l3_memory.recall_api (+ GET /v1/recall) and
l7_governance.drafts (+ POST/PATCH /v1/outbox, POST /v1/contacts/{id}/draft-follow-up).

MySQL unit database only (MYSQL_TEST_DATABASE=cortex_unit); every database test runs inside a transaction that is
rolled back, so nothing is left behind. The 403 tests never open a session (get_session is overridden by a sentinel).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.auth.principal import Principal
from platform_core.config import get_settings
from platform_core.db.compat import mysql_error_code
from platform_core.db.session import create_engine_from_url, get_mysql_test_url, reset_engine
from platform_core.errors import NotFound, Problem
from platform_core.jsonutil import as_utc, json_obj, row
from platform_core.signing import content_hash

ORG = "00000000-0000-0000-0000-000000000001"
ACTOR = Principal(sub=f"usr_md_{uuid.uuid4().hex[:12]}", username="md@test", roles=frozenset(["admin"]), token="t")
SRC = {"kind": "test", "suite": "memory_drafts"}
FK_VIOLATION = 1452
CHECK_VIOLATION = 3819


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


# ----------------------------------------------------------------------------- seed helpers (plain SQL)
def _uid() -> str:
    return str(uuid.uuid4())


async def _org(s: AsyncSession, name: str, *, is_demo: bool = False) -> str:
    oid = _uid()
    await s.execute(
        text(
            "INSERT INTO organization (id, org_id, name, kind, source_ref, is_demo) "
            "VALUES (:id, :org, :n, 'counterparty', CAST(:src AS JSON), :d)"
        ),
        {"id": oid, "org": ORG, "n": name, "src": json.dumps(SRC), "d": is_demo},
    )
    return oid


async def _contact(
    s: AsyncSession, organization_id: str | None, name: str, emails: list[str], *, is_demo: bool = False
) -> str:
    cid = _uid()
    await s.execute(
        text(
            "INSERT INTO contact (id, org_id, organization_id, name, emails, consent_basis, source_ref, is_demo) "
            "VALUES (:id, :org, :o, :n, CAST(:e AS JSON), 'legitimate_interest', CAST(:src AS JSON), :d)"
        ),
        {
            "id": cid,
            "org": ORG,
            "o": organization_id,
            "n": name,
            "e": json.dumps(emails),
            "src": json.dumps(SRC),
            "d": is_demo,
        },
    )
    return cid


async def _interaction(
    s: AsyncSession,
    *,
    organization_id: str | None,
    kind: str,
    at: datetime,
    contact_id: str | None = None,
    opportunity_id: str | None = None,
    summary: str | None = None,
    created_at: datetime | None = None,
) -> str:
    iid = _uid()
    await s.execute(
        text(
            "INSERT INTO interaction (id, org_id, contact_id, organization_id, opportunity_id, kind, occurred_at, summary, "
            "weight, recorded_by, source_ref, created_at) VALUES (:id, :org, :c, :o, :opp, :k, :at, :sm, 1.0, 'test', "
            "CAST(:src AS JSON), COALESCE(:ca, CURRENT_TIMESTAMP(6)))"
        ),
        {
            "id": iid, "org": ORG, "c": contact_id, "o": organization_id, "opp": opportunity_id, "k": kind, "at": at,
            "sm": summary, "src": json.dumps(SRC), "ca": created_at,
        },
    )  # fmt: skip
    return iid


async def _opportunity(s: AsyncSession, counterparty_id: str | None, title: str = "Test opportunity") -> str:
    oid = _uid()
    await s.execute(
        text(
            "INSERT INTO opportunity (id, org_id, title, counterparty_id, source_ref) "
            "VALUES (:id, :org, :t, :cp, CAST(:src AS JSON))"
        ),
        {"id": oid, "org": ORG, "t": title, "cp": counterparty_id, "src": json.dumps(SRC)},
    )
    return oid


async def _outcome(s: AsyncSession, opportunity_id: str, result: str, closed_at: datetime) -> str:
    ocid = _uid()
    await s.execute(
        text(
            "INSERT INTO outcome (id, org_id, opportunity_id, result, amount, currency, closed_at, recorded_by, source_ref) "
            "VALUES (:id, :org, :opp, :r, 1000.50, 'EUR', :at, 'test', CAST(:src AS JSON))"
        ),
        {"id": ocid, "org": ORG, "opp": opportunity_id, "r": result, "at": closed_at, "src": json.dumps(SRC)},
    )
    return ocid


async def _milestone(
    s: AsyncSession,
    *,
    due_at: datetime,
    title: str,
    organization_id: str | None = None,
    contact_id: str | None = None,
    opportunity_id: str | None = None,
    status: str = "open",
) -> str:
    mid = _uid()
    await s.execute(
        text(
            "INSERT INTO milestone (id, org_id, organization_id, contact_id, opportunity_id, kind, title, due_at, status, "
            "source_ref) VALUES (:id, :org, :o, :c, :opp, 'follow_up', :t, :due, :st, CAST(:src AS JSON))"
        ),
        {
            "id": mid, "org": ORG, "o": organization_id, "c": contact_id, "opp": opportunity_id, "t": title, "due": due_at,
            "st": status, "src": json.dumps(SRC),
        },
    )  # fmt: skip
    return mid


async def _relationship_met(
    s: AsyncSession, contact_id: str, organization_id: str, strength: float, last: datetime
) -> None:
    await s.execute(
        text(
            "INSERT INTO relationship (id, org_id, from_type, from_id, to_type, to_id, type, strength, last_touch_at, "
            "source_ref) VALUES (:id, :org, 'contact', :c, 'organization', :o, 'met', :st, :t, CAST(:src AS JSON))"
        ),
        {
            "id": _uid(),
            "org": ORG,
            "c": contact_id,
            "o": organization_id,
            "st": strength,
            "t": last,
            "src": json.dumps(SRC),
        },
    )


async def _memory_row(s: AsyncSession, key: str):
    return (
        (
            await s.execute(
                text(
                    "SELECT id, tier, kind, subject_type, subject_id, is_demo, value, source_ref, expires_at "
                    "FROM memory WHERE org_id = :org AND `key` = :k"
                ),
                {"org": ORG, "k": key},
            )
        )
        .mappings()
        .all()
    )


async def _scalar(s: AsyncSession, sql: str, **params):
    return (await s.execute(text(sql), params)).scalar()


# ============================================================================= consolidation_job
NOW = datetime(2026, 11, 5, 12, 0, tzinfo=UTC)


async def _seed_consolidation(s: AsyncSession) -> dict:
    o = await _org(s, "Consolidation Capital", is_demo=True)
    alice = await _contact(s, o, "Alice Warm", ["alice@cc.example"])
    bob = await _contact(s, o, "Bob Cold", ["bob@cc.example"])
    ids = {
        "b_note": await _interaction(s, organization_id=o, contact_id=bob, kind="note", at=NOW - timedelta(days=200)),
        "a_meeting": await _interaction(s, organization_id=o, contact_id=alice, kind="meeting", at=NOW - timedelta(days=100)),
        "a_call": await _interaction(s, organization_id=o, contact_id=alice, kind="call", at=NOW - timedelta(days=10)),
        "org_note": await _interaction(s, organization_id=o, kind="note", at=NOW - timedelta(days=5)),
        "a_email": await _interaction(s, organization_id=o, contact_id=alice, kind="email_reply", at=NOW - timedelta(days=2)),
    }  # fmt: skip
    opp = await _opportunity(s, o)
    won = await _outcome(s, opp, "won", NOW - timedelta(days=40))
    lost = await _outcome(s, opp, "lost", NOW - timedelta(days=60))
    overdue = await _milestone(s, organization_id=o, due_at=NOW - timedelta(days=3), title="Send deck")
    future = await _milestone(s, organization_id=o, due_at=NOW + timedelta(days=10), title="Call back")
    done = await _milestone(s, organization_id=o, due_at=NOW - timedelta(days=20), title="Done one", status="done")
    # Another counterparty's history must not leak into this reflection.
    other = await _org(s, "Other Counterparty")
    oc = await _contact(s, other, "Olga Other", ["olga@other.example"])
    foreign = await _interaction(s, organization_id=other, contact_id=oc, kind="call", at=NOW - timedelta(days=1))
    return {
        "org": o, "alice": alice, "bob": bob, "ids": ids, "won": won, "lost": lost, "overdue": overdue,
        "future": future, "done": done, "foreign": foreign,
    }  # fmt: skip


async def test_consolidate_organization_writes_cited_reflection_mysql(s: AsyncSession):
    from cortex.l3_memory.consolidation_job import consolidate_organization
    from cortex.l3_memory.warmth import Touch, warmth

    d = await _seed_consolidation(s)
    o, ids = d["org"], d["ids"]
    mid = await consolidate_organization(s, o, now=NOW)

    rows = await _memory_row(s, f"reflection:organization:{o}")
    assert len(rows) == 1 and str(rows[0]["id"]) == mid
    raw = rows[0]
    assert (raw["tier"], raw["kind"], raw["subject_type"], str(raw["subject_id"])) == (
        "warm",
        "reflection",
        "organization",
        o,
    )
    # MySQL specifics: JSON comes back as text, BOOLEAN as 0/1, DATETIME naive (UTC).
    assert not isinstance(raw["value"], dict) and not isinstance(raw["source_ref"], dict)
    assert raw["is_demo"] == 1 and row(raw)["is_demo"] is True
    assert raw["expires_at"].tzinfo is None and as_utc(raw["expires_at"]) > datetime.now(UTC) + timedelta(days=300)

    value = json_obj(raw["value"])
    st = value["stats"]
    assert st["interactions_total"] == 5 and st["interactions_90d"] == 3
    assert st["by_kind"] == {"note": 2, "meeting": 1, "call": 1, "email_reply": 1}
    assert st["open_milestones"] == 2 and st["overdue_milestones"] == 1
    assert st["outcomes"] == {"won": 1, "lost": 1, "withdrawn": 0}
    assert as_utc(datetime.fromisoformat(st["first_touch"])) == NOW - timedelta(days=200)
    assert as_utc(datetime.fromisoformat(st["last_touch"])) == NOW - timedelta(days=2)
    assert [c["contact_id"] for c in st["contacts"]] == [d["alice"], d["bob"]]  # warmest first
    a_touches = [
        Touch("meeting", NOW - timedelta(days=100)), Touch("call", NOW - timedelta(days=10)),
        Touch("email_reply", NOW - timedelta(days=2)),
    ]  # fmt: skip
    assert st["contacts"][0]["warmth"] == warmth(a_touches, NOW)
    assert st["contacts"][0]["warmth_30d_ago"] == warmth(a_touches[:1], NOW - timedelta(days=30))
    assert st["contacts"][0]["interactions"] == 3 and st["contacts"][0]["name"] == "Alice Warm"
    assert st["warmth_trend"] == "warming"

    expected_refs = (
        [f"interaction:{ids[k]}" for k in ("b_note", "a_meeting", "a_call", "org_note", "a_email")]
        + [f"outcome:{d['won']}", f"outcome:{d['lost']}"]  # closed_at DESC
        + [f"milestone:{d['overdue']}", f"milestone:{d['future']}"]  # open only, due_at ASC
    )
    assert value["refs"] == expected_refs
    assert f"interaction:{d['foreign']}" not in value["refs"] and f"milestone:{d['done']}" not in value["refs"]
    assert value["consolidated_at"] == NOW.isoformat()
    assert value["summary"].startswith("5 recorded interaction(s) with Consolidation Capital, 3 in the last 90 days.")
    top_warmth = st["contacts"][0]["warmth"]
    assert f"Warmest contact: Alice Warm (warmth {top_warmth:.2f}, warming)." in value["summary"]
    assert "1 overdue follow-up(s)" in value["summary"]
    assert "Realised outcomes: 1 won, 1 lost, 0 withdrawn." in value["summary"]
    src = json_obj(raw["source_ref"])
    assert src["kind"] == "consolidation" and src["refs"] == expected_refs and src["at"] == NOW.isoformat()


async def test_consolidation_touch_timestamps_carry_utc_offset_mysql(s: AsyncSession):
    """MySQL DATETIME is naive: stats.first_touch/last_touch are written with .isoformat() of the raw value, so on MySQL
    they lose the +00:00 that PostgreSQL timestamptz gives (a browser then reads them as local time). Expected to FAIL
    until consolidation_job.py:125-126 goes through _as_utc()/jsonable()."""
    from cortex.l3_memory.consolidation_job import consolidate_organization

    d = await _seed_consolidation(s)
    await consolidate_organization(s, d["org"], now=NOW)
    st = json_obj((await _memory_row(s, f"reflection:organization:{d['org']}"))[0]["value"])["stats"]
    assert st["first_touch"] == (NOW - timedelta(days=200)).isoformat()
    assert st["last_touch"] == (NOW - timedelta(days=2)).isoformat()


async def test_consolidate_missing_invalid_and_empty_organizations_mysql(s: AsyncSession):
    from cortex.l3_memory.consolidation_job import consolidate_organization

    missing = _uid()
    assert await consolidate_organization(s, missing, now=NOW) is None
    assert await consolidate_organization(s, "not-a-uuid", now=NOW) is None
    quiet = await _org(s, "No History Ltd")
    await _milestone(s, organization_id=quiet, due_at=NOW - timedelta(days=1), title="Only a milestone")
    assert await consolidate_organization(s, quiet, now=NOW) is None  # milestones alone are not a history
    for oid in (missing, "not-a-uuid", quiet):
        assert await _memory_row(s, f"reflection:organization:{oid}") == []


async def test_consolidate_rerun_upserts_one_row_mysql(s: AsyncSession):
    from cortex.l3_memory.consolidation_job import consolidate_organization

    d = await _seed_consolidation(s)
    first = await consolidate_organization(s, d["org"], now=NOW)
    later = NOW + timedelta(days=1)
    await _interaction(s, organization_id=d["org"], contact_id=d["alice"], kind="call", at=later - timedelta(hours=1))
    second = await consolidate_organization(s, d["org"], now=later)
    assert second == first  # ON DUPLICATE KEY UPDATE on (org_id, `key`), id unchanged
    rows = await _memory_row(s, f"reflection:organization:{d['org']}")
    assert len(rows) == 1
    v = json_obj(rows[0]["value"])
    assert v["consolidated_at"] == later.isoformat() and v["stats"]["interactions_total"] == 6
    assert json_obj(rows[0]["source_ref"])["at"] == later.isoformat()


async def test_reflection_provenance_check_rejects_losing_source_ref_mysql(s: AsyncSession):
    from cortex.l3_memory.consolidation_job import consolidate_organization

    d = await _seed_consolidation(s)
    mid = await consolidate_organization(s, d["org"], now=NOW)
    for bad in ("NULL", "JSON_OBJECT()"):  # ck_memory_provenance: non-empty OBJECT/ARRAY or inference_id
        with pytest.raises(DBAPIError) as ei:
            async with s.begin_nested():
                await s.execute(text(f"UPDATE memory SET source_ref = {bad} WHERE id = :id"), {"id": mid})
        assert mysql_error_code(ei.value) == CHECK_VIOLATION
    still = json_obj(await _scalar(s, "SELECT source_ref FROM memory WHERE id = :id", id=mid))
    assert still["kind"] == "consolidation"


async def test_run_consolidates_only_recent_activity_mysql(s: AsyncSession):
    from cortex.l3_memory.consolidation_job import run

    now = datetime.now(UTC).replace(microsecond=0)
    recent = await _org(s, "Recent Interaction Org")
    await _interaction(s, organization_id=recent, kind="note", at=now - timedelta(hours=2))
    stale = await _org(s, "Stale Interaction Org")
    await _interaction(
        s, organization_id=stale, kind="note", at=now - timedelta(days=10), created_at=now - timedelta(days=10)
    )
    outcome_only = await _org(s, "Outcome Only Org")
    won = await _outcome(s, await _opportunity(s, outcome_only), "won", now - timedelta(hours=3))

    n = await run(s, since=now - timedelta(hours=1))
    assert n >= 2
    assert len(await _memory_row(s, f"reflection:organization:{recent}")) == 1
    assert await _memory_row(s, f"reflection:organization:{stale}") == []
    oo = await _memory_row(s, f"reflection:organization:{outcome_only}")
    assert len(oo) == 1
    st = json_obj(oo[0]["value"])
    assert st["stats"]["interactions_total"] == 0 and st["stats"]["first_touch"] is None
    assert st["stats"]["contacts"] == [] and st["stats"]["outcomes"]["won"] == 1
    assert st["refs"] == [f"outcome:{won}"]
    assert row(oo[0])["is_demo"] is False


# ============================================================================= interaction_ingest
SELF = "me@ours.test"


async def _interactions_for(s: AsyncSession, contact_id: str):
    return (
        (
            await s.execute(
                text(
                    "SELECT id, kind, direction, occurred_at, external_id, recorded_by, meeting_id, source_ref, is_demo "
                    "FROM interaction WHERE contact_id = :c ORDER BY occurred_at, external_id"
                ),
                {"c": contact_id},
            )
        )
        .mappings()
        .all()
    )


async def test_ingest_inbound_email_logs_known_sender_once_mysql(s: AsyncSession):
    from cortex.l3_memory.interaction_ingest import ingest

    o = await _org(s, "Partner Fund")
    jane = await _contact(s, o, "Jane Doe", ["jane@partner.example"])
    bob = await _contact(s, o, "Bob Roe", ["bob@partner.example"])
    sig = _uid()
    when = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=3)
    raw = {
        "kind": "email", "external_id": "msg-in-1", "occurred_at": when.isoformat(), "from": "Jane@Partner.Example",
        "to": [SELF, "bob@partner.example"], "subject": "Re: intro",
    }  # fmt: skip

    assert await ingest(s, sig, raw, "mailbox", [SELF]) == {"interactions": 1}
    rows = await _interactions_for(s, jane)
    assert len(rows) == 1
    r = rows[0]
    assert (r["kind"], r["direction"], r["external_id"]) == ("email_reply", "inbound", "msg-in-1:jane@partner.example")
    assert r["recorded_by"] == "svc:adapter:mailbox"
    assert r["occurred_at"].tzinfo is None and as_utc(r["occurred_at"]) == when  # naive DATETIME holds UTC
    assert json_obj(r["source_ref"]) == {
        "kind": "signal",
        "signal_id": sig,
        "source_key": "mailbox",
        "external_id": "msg-in-1",
    }
    assert r["is_demo"] == 0 and row(r)["is_demo"] is False
    assert await _interactions_for(s, bob) == []  # inbound: only the sender counts
    rel = (
        (
            await s.execute(
                text(
                    "SELECT strength, last_touch_at FROM relationship WHERE from_id = :c AND to_id = :o AND type = 'met'"
                ),
                {"c": jane, "o": o},
            )
        )
        .mappings()
        .one()
    )
    assert float(rel["strength"]) > 0 and as_utc(rel["last_touch_at"]) == when
    assert (
        await _scalar(
            s,
            "SELECT COUNT(*) FROM audit_log WHERE action = 'interaction.logged' AND target = :t",
            t=f"interaction:{r['id']}",
        )
        == 1
    )

    # Re-reading the same message is a no-op (duplicate key skipped, not an error).
    assert await ingest(s, sig, raw, "mailbox", [SELF]) == {"interactions": 0}
    assert len(await _interactions_for(s, jane)) == 1


async def test_ingest_outbound_email_by_internal_domain_mysql(s: AsyncSession, monkeypatch):
    from cortex.l3_memory.interaction_ingest import ingest

    monkeypatch.setattr(get_settings(), "internal_email_domains", ["ours.test"])
    o = await _org(s, "Outbound Partner")
    jane = await _contact(s, o, "Jane Out", ["jane.out@partner.example"])
    bob = await _contact(s, o, "Bob Out", ["bob.out@partner.example"], is_demo=True)
    raw = {
        "kind": "email", "external_id": "msg-out-1", "occurred_at": datetime.now(UTC).isoformat(),
        "from": "colleague@ours.test", "to": ["jane.out@partner.example", "nobody@unknown.example"],
        "cc": ["BOB.OUT@partner.example"], "subject": "Follow-up",
    }  # fmt: skip
    assert await ingest(s, _uid(), raw, "mailbox", []) == {"interactions": 2}
    for cid, demo in ((jane, False), (bob, True)):
        (r,) = await _interactions_for(s, cid)
        assert (r["kind"], r["direction"]) == ("email_sent", "outbound")
        assert row(r)["is_demo"] is demo  # BOOLEAN 0/1 -> false/true
    unknown = await _scalar(
        s,
        "SELECT COUNT(*) FROM contact c, JSON_TABLE(c.emails, '$[*]' COLUMNS (email VARCHAR(255) PATH '$')) jt "
        "WHERE LOWER(jt.email) = 'nobody@unknown.example'",
    )
    assert unknown == 0  # unknown people are never auto-created


async def test_ingest_calendar_event_logs_meeting_once_mysql(s: AsyncSession):
    from cortex.l3_memory.interaction_ingest import ingest

    o = await _org(s, "Event Partner")
    jane = await _contact(s, o, "Jane Event", ["jane.evt@partner.example"])
    bob = await _contact(s, o, "Bob Event", ["bob.evt@partner.example"], is_demo=True)
    sig, xid = _uid(), f"evt-{uuid.uuid4().hex[:8]}"
    when = datetime.now(UTC).replace(microsecond=0) - timedelta(hours=2)
    raw = {
        "kind": "event", "external_id": xid, "occurred_at": when.isoformat(), "status": "CONFIRMED",
        "attendees": ["Jane.Evt@Partner.Example", "bob.evt@partner.example", "stranger@nowhere.example"],
        "organizer": SELF, "subject": "Quarterly sync",
    }  # fmt: skip

    out = await ingest(s, sig, raw, "calendar", [SELF])
    assert out["interactions"] == 2
    m = (
        (
            await s.execute(
                text("SELECT contact_ids, occurred_at, summary, source_ref, is_demo FROM meeting WHERE id = :id"),
                {"id": out["meeting_id"]},
            )
        )
        .mappings()
        .one()
    )
    assert sorted(json_obj(m["contact_ids"])) == sorted([jane, bob])
    assert as_utc(m["occurred_at"]) == when and m["summary"] == "Quarterly sync"
    assert json_obj(m["source_ref"])["external_id"] == xid
    assert row(m)["is_demo"] is True  # any(is_demo) over 0/1 values
    for cid in (jane, bob):
        (r,) = await _interactions_for(s, cid)
        assert (r["kind"], r["direction"], str(r["meeting_id"])) == ("meeting", "internal", out["meeting_id"])
        assert r["external_id"] == f"{xid}:{cid}"

    again = await ingest(s, sig, raw, "calendar", [SELF])
    assert again == {"interactions": 0, "reason": "already recorded"}
    ext = "source_ref ->> '$.external_id'"
    assert await _scalar(s, f"SELECT COUNT(*) FROM meeting WHERE org_id = :org AND {ext} = :x", org=ORG, x=xid) == 1


async def test_ingest_rejects_invalid_items_without_writing_mysql(s: AsyncSession):
    from cortex.l3_memory.interaction_ingest import ingest

    o = await _org(s, "Invalid Items Partner")
    jane = await _contact(s, o, "Jane Invalid", ["jane.inv@partner.example"])
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    who = ["jane.inv@partner.example"]
    cases = [
        ({"kind": "email", "external_id": "x1", "from": who[0]}, "no timestamp"),
        ({"kind": "event", "external_id": "x2", "occurred_at": future, "attendees": who}, "future event"),
        ({"kind": "event", "external_id": "x3", "occurred_at": past, "attendees": who, "status": "cancelled"}, "cancelled event"),
        ({"kind": "event", "external_id": "x4", "occurred_at": past, "attendees": ["ghost@nowhere.example"]}, "no known contact attended"),
        ({"kind": "task", "external_id": "x5", "occurred_at": past}, "unknown item kind 'task'"),
    ]  # fmt: skip
    for raw, reason in cases:
        out = await ingest(s, _uid(), raw, "calendar", [SELF])
        assert out["interactions"] == 0 and out["reason"].startswith(reason), (raw, out)
    with pytest.raises(ValueError):
        await ingest(s, _uid(), {"kind": "email", "occurred_at": "yesterday", "from": who[0]}, "mailbox", [SELF])
    assert await _interactions_for(s, jane) == []
    ext = "source_ref ->> '$.external_id'"
    assert (
        await _scalar(s, f"SELECT COUNT(*) FROM meeting WHERE org_id = :org AND {ext} IN ('x2','x3','x4')", org=ORG)
        == 0
    )


async def test_ingest_overlong_message_id_raises_not_skipped_mysql(s: AsyncSession):
    """interaction.external_id is VARCHAR(255): an over-long id must raise (strict mode), not be swallowed like the
    duplicate-key case that insert_or_skip_duplicate skips."""
    from cortex.l3_memory.interaction_ingest import ingest

    o = await _org(s, "Long Id Partner")
    jane = await _contact(s, o, "Jane Long", ["jane.long@partner.example"])
    raw = {
        "kind": "email",
        "external_id": "m" * 300,
        "occurred_at": datetime.now(UTC).isoformat(),
        "from": "jane.long@partner.example",
    }
    with pytest.raises(DBAPIError):
        async with s.begin_nested():
            await ingest(s, _uid(), raw, "mailbox", [SELF])
    assert await _interactions_for(s, jane) == []


async def test_ingest_event_count_matches_rows_for_contact_with_two_addresses_mysql(s: AsyncSession):
    """A contact with two addresses that both attend gets ONE meeting interaction (log_meeting dedupes contacts), but
    ingest returns len(found), which counts addresses. Expected to FAIL until interaction_ingest.py:82 counts contacts."""
    from cortex.l3_memory.interaction_ingest import ingest

    o = await _org(s, "Two Address Partner")
    carol = await _contact(s, o, "Carol Two", ["carol@partner.example", "c.two@partner.example"])
    raw = {
        "kind": "event", "external_id": f"evt-{uuid.uuid4().hex[:8]}",
        "occurred_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat(),
        "attendees": ["carol@partner.example", "c.two@partner.example"], "subject": "1:1",
    }  # fmt: skip
    out = await ingest(s, _uid(), raw, "calendar", [SELF])
    written = await _interactions_for(s, carol)
    assert len(written) == 1
    assert out["interactions"] == len(written)


# ============================================================================= recall_api
UNTIL = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


async def _seed_recall(s: AsyncSession) -> dict:
    from cortex.l3_memory.memory_manager import put_warm

    o = await _org(s, "Recall Ventures")
    a = await _contact(s, o, "Ann Recall", ["ann@recall.example"])
    b = await _contact(s, o, "Ben NoRel", ["ben@recall.example"])
    c = await _contact(s, o, "Cat Recall", ["cat@recall.example"])
    await _relationship_met(s, a, o, 0.8, UNTIL - timedelta(days=1))
    await _relationship_met(s, c, o, 0.3, UNTIL - timedelta(days=30))
    opp = await _opportunity(s, o, "Recall opp")
    i_call = await _interaction(
        s,
        organization_id=o,
        contact_id=a,
        kind="call",
        at=UNTIL - timedelta(days=1),
        opportunity_id=opp,
        summary="Pricing",
    )
    i_meet = await _interaction(s, organization_id=o, contact_id=a, kind="meeting", at=UNTIL - timedelta(days=10))
    i_cat = await _interaction(s, organization_id=o, contact_id=c, kind="email_reply", at=UNTIL - timedelta(days=30))
    i_old = await _interaction(s, organization_id=o, contact_id=a, kind="note", at=UNTIL - timedelta(days=400))
    i_after = await _interaction(s, organization_id=o, contact_id=a, kind="note", at=UNTIL + timedelta(days=2))
    other = await _org(s, "Recall Other")
    i_other = await _interaction(s, organization_id=other, kind="call", at=UNTIL - timedelta(days=1))
    m_over = await _milestone(s, organization_id=o, due_at=UNTIL - timedelta(days=5), title="Overdue")
    m_fut = await _milestone(s, organization_id=o, due_at=UNTIL + timedelta(days=5), title="Upcoming")
    m_done = await _milestone(s, organization_id=o, due_at=UNTIL - timedelta(days=6), title="Done", status="done")
    m_other = await _milestone(s, organization_id=other, due_at=UNTIL - timedelta(days=5), title="Other")
    m_contact = await _milestone(s, contact_id=a, due_at=UNTIL - timedelta(days=2), title="Ann follow-up")
    m_opp = await _milestone(s, opportunity_id=opp, due_at=UNTIL + timedelta(days=3), title="Opp deadline")
    refl = await put_warm(
        s, f"reflection:organization:{o}", {"summary": "warm", "stats": {"n": 3}}, source_ref=SRC, kind="reflection",
        subject_type="organization", subject_id=o,
    )  # fmt: skip
    await put_warm(s, f"note:{o}", {"x": 1}, source_ref=SRC, kind="note", subject_type="organization", subject_id=o)
    return locals()


async def test_recall_by_organization_mysql(s: AsyncSession):
    from cortex.l3_memory.recall_api import recall

    d = await _seed_recall(s)
    out = await recall(s, organization_id=d["o"], until=UNTIL)
    assert out["window"] == {"since": (UNTIL - timedelta(days=365)).isoformat(), "until": UNTIL.isoformat()}
    assert [i["id"] for i in out["interactions"]] == [d["i_call"], d["i_meet"], d["i_cat"]]  # in window, DESC
    first = out["interactions"][0]
    assert first["ref"] == f"interaction:{d['i_call']}" and first["contact_name"] == "Ann Recall"
    assert first["occurred_at"] == (UNTIL - timedelta(days=1)).isoformat()  # naive DATETIME emitted with +00:00
    assert first["opportunity_id"] == d["opp"] and out["interactions"][1]["opportunity_id"] is None
    assert first["summary"] == "Pricing" and first["kind"] == "call" and first["organization_id"] == d["o"]
    ids = {i["id"] for i in out["interactions"]}
    assert not ids & {d["i_old"], d["i_after"], d["i_other"]}

    # contacts: strength DESC with NULL last (MySQL order_by_nulls); DECIMAL -> float.
    assert [c["id"] for c in out["contacts"]] == [d["a"], d["c"], d["b"]]
    assert out["contacts"][0]["warmth"] == 0.8 and isinstance(out["contacts"][0]["warmth"], float)
    assert out["contacts"][0]["last_touch_at"] == (UNTIL - timedelta(days=1)).isoformat()
    assert out["contacts"][2]["warmth"] is None and out["contacts"][2]["last_touch_at"] is None
    assert out["contacts"][1]["ref"] == f"contact:{d['c']}"

    ms = out["open_milestones"]
    assert [m["id"] for m in ms] == [d["m_over"], d["m_fut"]]
    assert [m["overdue"] for m in ms] == [True, False]  # naive due_at compared as UTC
    assert ms[0]["due_at"] == (UNTIL - timedelta(days=5)).isoformat() and ms[0]["ref"] == f"milestone:{d['m_over']}"

    (refl,) = out["reflections"]
    assert refl["id"] == d["refl"] and refl["ref"] == f"memory:{d['refl']}"
    assert refl["value"] == {"summary": "warm", "stats": {"n": 3}}  # JSON text decoded to a document
    assert refl["key"] == f"reflection:organization:{d['o']}" and refl["ts"].endswith("+00:00")
    assert out["warmth"] is None
    json.dumps(out)  # whole payload is JSON-serialisable


async def test_recall_by_contact_and_opportunity_mysql(s: AsyncSession):
    from cortex.l3_memory.recall_api import recall
    from cortex.l3_memory.warmth import Touch, warmth

    d = await _seed_recall(s)
    by_c = await recall(s, contact_id=d["a"], until=UNTIL)
    assert [i["id"] for i in by_c["interactions"]] == [d["i_call"], d["i_meet"]]
    assert by_c["contacts"] == [] and by_c["reflections"] == []
    assert [m["id"] for m in by_c["open_milestones"]] == [d["m_contact"]] and by_c["open_milestones"][0][
        "overdue"
    ] is True
    expected = warmth([Touch("call", UNTIL - timedelta(days=1)), Touch("meeting", UNTIL - timedelta(days=10))], UNTIL)
    assert by_c["warmth"] == expected and expected > 0

    by_opp = await recall(s, opportunity_id=d["opp"], until=UNTIL)
    assert [i["id"] for i in by_opp["interactions"]] == [d["i_call"]]
    assert [m["id"] for m in by_opp["open_milestones"]] == [d["m_opp"]] and by_opp["warmth"] is None
    # opportunity filter is ignored when a contact is given
    mixed = await recall(s, contact_id=d["c"], opportunity_id=d["opp"], until=UNTIL)
    assert [i["id"] for i in mixed["interactions"]] == [d["i_cat"]]
    assert [i["id"] for i in (await recall(s, organization_id=d["o"], until=UNTIL, limit=1))["interactions"]] == [
        d["i_call"]
    ]


async def test_recall_missing_subjects_and_empty_window_mysql(s: AsyncSession):
    from cortex.l3_memory.recall_api import recall

    d = await _seed_recall(s)
    for kw in ({"organization_id": _uid()}, {"contact_id": _uid()}, {"opportunity_id": _uid()}):
        out = await recall(s, until=UNTIL, **kw)
        assert out["interactions"] == [] and out["contacts"] == [] and out["reflections"] == []
        assert out["open_milestones"] == [] and out["warmth"] is None
    inverted = await recall(s, organization_id=d["o"], since=UNTIL, until=UNTIL - timedelta(days=30))
    assert inverted["interactions"] == []


async def test_recall_route_direct_mysql(s: AsyncSession):
    from cortex.l3_memory.recall_api import recall
    from cortex.l8_actuation.api.routers import relationships

    d = await _seed_recall(s)
    via_route = await relationships.recall_endpoint(
        organization_id=d["o"], contact_id=None, opportunity_id=None, since=None, until=UNTIL, _=ACTOR, session=s
    )
    assert via_route == await recall(s, organization_id=d["o"], until=UNTIL)
    with pytest.raises(Problem) as ei:
        await relationships.recall_endpoint(
            organization_id=None, contact_id=None, opportunity_id=None, since=None, until=None, _=ACTOR, session=s
        )
    assert ei.value.status == 422


# ============================================================================= drafts (outbox)
async def _outbox(s: AsyncSession, oid: str):
    return (
        (
            await s.execute(
                text(
                    "SELECT id, channel, payload, content_hash, status, created_by, kind, recipient, recipient_external, "
                    "flags, recommendation_id, opportunity_id, approval_id, approval_token FROM outbox WHERE id = :id"
                ),
                {"id": oid},
            )
        )
        .mappings()
        .one()
    )


async def _actor_rows(s: AsyncSession) -> tuple[int, int]:
    n_out = await _scalar(s, "SELECT COUNT(*) FROM outbox WHERE created_by = :by", by=ACTOR.sub)
    n_aud = await _scalar(s, "SELECT COUNT(*) FROM audit_log WHERE actor = :a", a=f"user:{ACTOR.sub}")
    return n_out, n_aud


async def _audit(s: AsyncSession, action: str, target: str):
    return (
        (
            await s.execute(
                text("SELECT actor, meta FROM audit_log WHERE action = :a AND target = :t ORDER BY seq"),
                {"a": action, "t": target},
            )
        )
        .mappings()
        .all()
    )


async def _approve(s: AsyncSession, oid: str, status: str = "approved") -> str:
    aid = _uid()
    h = (await _outbox(s, oid))["content_hash"]
    await s.execute(
        text(
            "INSERT INTO approval (id, org_id, subject_type, subject_id, content_hash, requested_by, approver_id, decision, "
            "decided_at) VALUES (:id, :org, 'outbox', :sid, :h, :by, 'usr_approver_md', 'approved', CURRENT_TIMESTAMP(6))"
        ),
        {"id": aid, "org": ORG, "sid": oid, "h": h, "by": ACTOR.sub},
    )
    await s.execute(
        text("UPDATE outbox SET status = :st, approval_id = :a, approval_token = 'tok' WHERE id = :id"),
        {"st": status, "a": aid, "id": oid},
    )
    return aid


async def test_create_email_draft_mysql(s: AsyncSession):
    from cortex.l7_governance.drafts import create_draft

    payload = {"to": "Investor@Fund.example", "subject": "Intro", "body": "Please find our term sheet attached."}
    out = await create_draft(s, ACTOR, "email", payload)
    assert out["status"] == "draft"
    assert out["flags"] == {"contains_financial_terms": True, "contains_pii": False, "is_grant_submission": False}
    r = await _outbox(s, out["id"])
    assert not isinstance(r["payload"], dict)  # MySQL JSON arrives as text
    assert json_obj(r["payload"]) == payload and json_obj(r["flags"]) == out["flags"]
    assert r["content_hash"] == content_hash(payload)
    assert (r["channel"], r["status"], r["kind"], r["recipient"], r["created_by"]) == (
        "email", "draft", "outbound", "Investor@Fund.example", ACTOR.sub,
    )  # fmt: skip
    assert r["recipient_external"] == 1 and row(r)["recipient_external"] is True
    assert r["approval_id"] is None and r["opportunity_id"] is None
    (a,) = await _audit(s, "outbox.draft_created", f"outbox:{out['id']}")
    meta = json_obj(a["meta"])
    assert a["actor"] == f"user:{ACTOR.sub}" and meta["channel"] == "email" and meta["flags"] == out["flags"]


async def test_create_internal_webhook_and_export_drafts_mysql(s: AsyncSession, monkeypatch):
    from cortex.l7_governance.drafts import create_draft

    monkeypatch.setattr(get_settings(), "internal_email_domains", ["ours.test"])
    opp = await _opportunity(s, None, "Draft opp")
    internal = await create_draft(s, ACTOR, "email", {"to": "cfo@OURS.test", "body": "fyi"}, opportunity_id=opp)
    r = await _outbox(s, internal["id"])
    assert r["recipient_external"] == 0 and row(r)["recipient_external"] is False and r["opportunity_id"] == opp
    hook = await create_draft(s, ACTOR, "webhook", {"url": "https://hooks.example/x", "event": "deal"})
    r = await _outbox(s, hook["id"])
    assert (r["recipient"], r["kind"], row(r)["recipient_external"]) == ("https://hooks.example/x", "outbound", True)
    export = await create_draft(s, ACTOR, "portal_export", {"document_id": "d1"})
    r = await _outbox(s, export["id"])
    assert (r["kind"], r["recipient"], row(r)["recipient_external"]) == ("export", None, True)
    sub = await create_draft(s, ACTOR, "portal_export", {"portal": "EU F&T"}, kind="submission")
    assert sub["flags"]["is_grant_submission"] is True and (await _outbox(s, sub["id"]))["kind"] == "submission"


async def test_create_draft_invalid_input_writes_nothing_mysql(s: AsyncSession):
    from cortex.l7_governance.drafts import create_draft

    before = await _actor_rows(s)
    bad = [
        ("email", {"to": "not-an-address", "body": "x"}),
        ("email", {"to": "a@b.example", "body": "   "}),
        ("webhook", {"url": "http://insecure.example"}),
        ("fax", {"to": "123"}),
    ]
    for channel, payload in bad:
        with pytest.raises(Problem) as ei:
            await create_draft(s, ACTOR, channel, payload)  # type: ignore[arg-type]
        assert ei.value.status == 422
    assert await _actor_rows(s) == before


async def test_create_draft_fk_violations_raise_mysql(s: AsyncSession):
    from cortex.l7_governance.drafts import create_draft

    before = await _actor_rows(s)
    payload = {"to": "x@fund.example", "body": "hello"}
    for kw in ({"opportunity_id": _uid()}, {"recommendation_id": _uid()}):
        with pytest.raises(IntegrityError) as ei:
            async with s.begin_nested():
                await create_draft(s, ACTOR, "email", payload, **kw)
        assert mysql_error_code(ei.value) == FK_VIOLATION
    assert await _actor_rows(s) == before  # no outbox row, no audit entry


async def test_edit_draft_updates_row_and_audits_mysql(s: AsyncSession, monkeypatch):
    from cortex.l7_governance.drafts import create_draft, edit_draft

    monkeypatch.setattr(get_settings(), "internal_email_domains", ["ours.test"])
    d = await create_draft(s, ACTOR, "email", {"to": "a@ext.example", "body": "hello"})
    new = {"to": "b@ours.test", "subject": "s", "body": "call me on +44 20 7946 0958"}
    out = await edit_draft(s, ACTOR, d["id"], new)
    assert out == {"id": d["id"], "status": "draft", "approval_invalidated": False}
    r = await _outbox(s, d["id"])
    assert json_obj(r["payload"]) == new and r["content_hash"] == content_hash(new) and r["recipient"] == "b@ours.test"
    assert row(r)["recipient_external"] is False and json_obj(r["flags"])["contains_pii"] is True
    (a,) = await _audit(s, "outbox.edited", f"outbox:{d['id']}")
    meta = json_obj(a["meta"])
    assert (meta["previous_status"], meta["approval_invalidated"], meta["content_hash"]) == (
        "draft",
        False,
        content_hash(new),
    )


async def test_edit_approved_draft_invalidates_approval_via_trigger_mysql(s: AsyncSession):
    from cortex.l7_governance.drafts import create_draft, edit_draft

    d = await create_draft(s, ACTOR, "email", {"to": "a@ext.example", "body": "v1"})
    aid = await _approve(s, d["id"])
    out = await edit_draft(s, ACTOR, d["id"], {"to": "a@ext.example", "body": "v2"})
    assert out == {"id": d["id"], "status": "draft", "approval_invalidated": True}
    r = await _outbox(s, d["id"])
    assert (r["status"], r["approval_id"], r["approval_token"]) == ("draft", None, None)
    assert await _scalar(s, "SELECT decision FROM approval WHERE id = :id", id=aid) == "invalidated"
    (a,) = await _audit(s, "outbox.edited", f"outbox:{d['id']}")
    assert json_obj(a["meta"])["previous_status"] == "approved" and json_obj(a["meta"])["approval_invalidated"] is True


async def test_edit_approved_draft_with_identical_payload_keeps_approval_mysql(s: AsyncSession):
    from cortex.l7_governance.drafts import create_draft, edit_draft

    payload = {"to": "a@ext.example", "subject": "same", "body": "unchanged"}
    d = await create_draft(s, ACTOR, "email", payload)
    aid = await _approve(s, d["id"])
    out = await edit_draft(s, ACTOR, d["id"], {"body": "unchanged", "subject": "same", "to": "a@ext.example"})
    assert out == {"id": d["id"], "status": "approved", "approval_invalidated": False}
    r = await _outbox(s, d["id"])
    assert (r["status"], r["approval_id"]) == ("approved", aid)
    assert await _scalar(s, "SELECT decision FROM approval WHERE id = :id", id=aid) == "approved"


async def test_edit_sent_missing_and_invalid_drafts_mysql(s: AsyncSession):
    from cortex.l7_governance.drafts import create_draft, edit_draft

    sent = await create_draft(s, ACTOR, "email", {"to": "a@ext.example", "body": "final"})
    await _approve(s, sent["id"], status="sent")
    with pytest.raises(Problem) as ei:
        await edit_draft(s, ACTOR, sent["id"], {"to": "a@ext.example", "body": "changed"})
    assert ei.value.status == 409
    assert json_obj((await _outbox(s, sent["id"]))["payload"])["body"] == "final"
    # The DB itself refuses to change a sent payload (trg_outbox_invalidate SIGNAL 45000).
    with pytest.raises(DBAPIError) as db_err:
        async with s.begin_nested():
            await s.execute(
                text("UPDATE outbox SET payload = JSON_OBJECT('body', 'tampered') WHERE id = :id"), {"id": sent["id"]}
            )
    assert "immutable" in str(db_err.value)

    with pytest.raises(NotFound):
        await edit_draft(s, ACTOR, _uid(), {"to": "a@ext.example", "body": "x"})

    hook = await create_draft(s, ACTOR, "webhook", {"url": "https://hooks.example/y"})
    before = await _outbox(s, hook["id"])
    with pytest.raises(Problem) as ei:
        await edit_draft(s, ACTOR, hook["id"], {"url": "http://downgrade.example"})
    assert ei.value.status == 422
    after = await _outbox(s, hook["id"])
    assert (after["payload"], after["content_hash"]) == (before["payload"], before["content_hash"])
    assert await _audit(s, "outbox.edited", f"outbox:{hook['id']}") == []


async def test_outbox_routes_direct_mysql(s: AsyncSession, monkeypatch):
    from cortex.l8_actuation.api.routers import approvals

    events: list[dict] = []

    async def _capture(ev: dict) -> None:
        events.append(ev)

    monkeypatch.setattr(approvals, "publish_event", _capture)  # Redis bus stubbed; DB is real
    created = await approvals.create_outbox(
        body=approvals.DraftIn(channel="email", payload={"to": "r@ext.example", "body": "hi"}), p=ACTOR, session=s
    )
    assert (await _outbox(s, created["id"]))["status"] == "draft"
    edited = await approvals.edit_outbox(
        id=created["id"], body=approvals.EditIn(payload={"to": "r@ext.example", "body": "hi again"}), p=ACTOR, session=s
    )
    assert edited["status"] == "draft"
    assert events == [{"type": "outbox.updated", "status": "draft", "ids": [created["id"]]}]
    assert json_obj((await _outbox(s, created["id"]))["payload"])["body"] == "hi again"


async def test_draft_follow_up_route_decodes_contact_emails_mysql(s: AsyncSession):
    from cortex.l8_actuation.api.routers import relationships

    o = await _org(s, "Follow Up Partner")
    c = await _contact(s, o, "Fran Follow", ["fran@partner.example", "f2@partner.example"])
    body = relationships.FollowUpIn(subject="Next steps", body="Thanks for the call.")
    out = await relationships.draft_follow_up(id=c, body=body, p=ACTOR, session=s)
    r = await _outbox(s, out["id"])
    assert r["recipient"] == "fran@partner.example"  # first element of the JSON array, not a character of its text
    assert json_obj(r["payload"])["contact_id"] == c

    before = await _actor_rows(s)
    no_mail = await _contact(s, o, "Nemo NoMail", [])
    with pytest.raises(Problem) as ei:
        await relationships.draft_follow_up(id=no_mail, body=body, p=ACTOR, session=s)
    assert ei.value.status == 422  # '[]' text on MySQL must count as empty
    with pytest.raises(NotFound):
        await relationships.draft_follow_up(id=_uid(), body=body, p=ACTOR, session=s)
    assert await _actor_rows(s) == before


# ============================================================================= authorization (no database)
@pytest.fixture
def api_client(verifier):
    from fastapi.testclient import TestClient

    from cortex.l8_actuation.api.app import create_app
    from platform_core.auth import oidc
    from platform_core.auth.rbac import get_rbac
    from platform_core.db import get_session
    from platform_core.policy import opa
    from platform_core.policy.opa import PolicyDecision

    class RbacOPA:
        async def evaluate(self, package, input_):
            perms = get_rbac().permissions_for(set(input_["subject"]["roles"]))
            ok = "*" in perms or input_["action"] in perms
            return PolicyDecision(ok, [] if ok else ["rbac"])

    opened: list[bool] = []

    async def _no_db():
        opened.append(True)
        yield None

    app = create_app()
    app.dependency_overrides[get_session] = _no_db
    oidc.set_verifier(verifier)
    opa.set_opa(RbacOPA())  # type: ignore[arg-type]
    c = TestClient(app, raise_server_exceptions=False)
    c.db_opened = opened  # type: ignore[attr-defined]
    yield c
    oidc.set_verifier(None)
    opa.set_opa(None)


FAKE = "11111111-1111-1111-1111-111111111111"


@pytest.mark.parametrize("role", ["auditor", "executive"])
def test_recall_route_forbidden_for_roles_without_relationship_read(api_client, make_token, role):
    r = api_client.get(
        "/v1/recall", params={"organization_id": FAKE}, headers={"Authorization": f"Bearer {make_token([role])}"}
    )
    assert r.status_code == 403 and r.json()["permission"] == "relationship:read"
    assert api_client.db_opened == []


@pytest.mark.parametrize("role", ["approver", "auditor", "executive"])
def test_draft_routes_forbidden_for_roles_without_outbox_draft(api_client, make_token, role):
    h = {"Authorization": f"Bearer {make_token([role])}"}
    calls = [
        ("POST", "/v1/outbox", {"channel": "email", "payload": {"to": "a@b.example", "body": "x"}}),
        ("PATCH", f"/v1/outbox/{FAKE}", {"payload": {"to": "a@b.example", "body": "x"}}),
        ("POST", f"/v1/contacts/{FAKE}/draft-follow-up", {"subject": "s", "body": "b"}),
    ]
    for method, url, body in calls:
        r = api_client.request(method, url, headers=h, json=body)
        assert r.status_code == 403, (method, url, r.status_code)
        assert r.json()["permission"] == "outbox:draft"
    assert api_client.db_opened == []  # rejected before any session is opened
