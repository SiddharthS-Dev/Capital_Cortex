from datetime import UTC, datetime, timedelta

from platform_core.audit.chain import GENESIS_HASH, AuditRecord, compute_hash, verify_records


def _chain(n: int) -> list[AuditRecord]:
    recs, prev = [], GENESIS_HASH
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    for i in range(1, n + 1):
        r = AuditRecord(
            i,
            "org",
            "user:a",
            "x.do",
            f"t:{i}",
            {"k": i, "nested": {"b": 1, "a": [1, 2]}},
            t0 + timedelta(seconds=i),
            prev,
        )
        r.hash = compute_hash(prev, r.payload())
        prev = r.hash
        recs.append(r)
    return recs


def test_valid_chain_verifies():
    res = verify_records(_chain(25))
    assert res.ok and res.checked == 25 and res.head_seq == 25


def test_empty_chain_is_ok():
    assert verify_records([]).ok


def test_tampered_meta_detected():
    recs = _chain(10)
    recs[4].meta["k"] = 999
    res = verify_records(recs)
    assert not res.ok and res.first_broken_seq == 5 and "hash" in res.reason


def test_deleted_record_detected():
    recs = _chain(10)
    del recs[3]
    res = verify_records(recs)
    assert not res.ok and res.first_broken_seq == 5


def test_relinked_forgery_detected():
    """An attacker rewrites a record and recomputes its own hash but can't fix the successors."""
    recs = _chain(6)
    recs[2].actor = "user:mallory"
    recs[2].hash = compute_hash(recs[2].prev_hash, recs[2].payload())
    res = verify_records(recs)
    assert not res.ok and res.first_broken_seq == 4


def test_hash_is_key_order_independent():
    a = compute_hash(GENESIS_HASH, {"a": 1, "b": {"y": 2, "x": 1}})
    b = compute_hash(GENESIS_HASH, {"b": {"x": 1, "y": 2}, "a": 1})
    assert a == b
