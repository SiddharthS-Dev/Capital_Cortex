"""Hash-chained, append-only audit log.

    hash_n = SHA-256( prev_hash_n || canonical_json({seq, org_id, actor, action, target, meta, ts}) )

The DB trigger ``audit_log_immutable`` rejects UPDATE/DELETE/TRUNCATE. Appends take a transaction-scoped
advisory lock, so ``seq`` and ``prev_hash`` are assigned serially even with concurrent writers.
``verify_chain`` recomputes every link and reports the first break.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from platform_core.observability.metrics import AUDIT_APPENDS

GENESIS_HASH = "0" * 64
_LOCK_KEY = 0x0A0D17  # arbitrary constant for pg_advisory_xact_lock


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _ts(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass
class AuditRecord:
    seq: int
    org_id: str
    actor: str
    action: str
    target: str
    meta: dict[str, Any]
    ts: datetime
    prev_hash: str
    hash: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def payload(self) -> dict[str, Any]:
        return {
            "seq": self.seq,
            "org_id": str(self.org_id),
            "actor": self.actor,
            "action": self.action,
            "target": self.target,
            "meta": self.meta,
            "ts": _ts(self.ts),
        }


def compute_hash(prev_hash: str, payload: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + canonical_json(payload)).encode("utf-8")).hexdigest()


async def append(
    session: AsyncSession,
    *,
    org_id: str,
    actor: str,
    action: str,
    target: str,
    meta: dict[str, Any] | None = None,
) -> AuditRecord:
    """Append one record inside the caller's transaction (the audit row commits with the action)."""
    await session.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})
    last = (await session.execute(text("SELECT seq, hash FROM audit_log ORDER BY seq DESC LIMIT 1"))).first()
    seq = (last.seq + 1) if last else 1
    prev = last.hash if last else GENESIS_HASH
    # Round-trip meta through canonical JSON so the hashed form equals the stored jsonb form.
    meta_c = json.loads(canonical_json(meta or {}))
    rec = AuditRecord(
        seq=seq,
        org_id=org_id,
        actor=actor,
        action=action,
        target=target,
        meta=meta_c,
        ts=datetime.now(UTC),
        prev_hash=prev,
    )
    rec.hash = compute_hash(prev, rec.payload())
    await session.execute(
        text(
            "INSERT INTO audit_log (seq, org_id, actor, action, target, meta, ts, prev_hash, hash) "
            "VALUES (:seq, :org_id, :actor, :action, :target, CAST(:meta AS jsonb), :ts, :prev, :hash)"
        ),
        {
            "seq": rec.seq,
            "org_id": org_id,
            "actor": actor,
            "action": action,
            "target": target,
            "meta": canonical_json(meta_c),
            "ts": rec.ts,
            "prev": prev,
            "hash": rec.hash,
        },
    )
    AUDIT_APPENDS.labels(action=action).inc()
    return rec


@dataclass
class VerifyResult:
    ok: bool
    checked: int
    head_seq: int | None
    head_hash: str | None
    first_broken_seq: int | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def verify_records(records: list[AuditRecord], prev_hash: str = GENESIS_HASH, expected_seq: int = 1) -> VerifyResult:
    """Pure verifier over an ordered list of records (used by the DB verifier and unit tests)."""
    checked = 0
    for r in records:
        if r.seq != expected_seq:
            return VerifyResult(False, checked, r.seq, r.hash, r.seq, f"gap: expected seq {expected_seq}")
        if r.prev_hash != prev_hash:
            return VerifyResult(False, checked, r.seq, r.hash, r.seq, "prev_hash does not link")
        if compute_hash(prev_hash, r.payload()) != r.hash:
            return VerifyResult(False, checked, r.seq, r.hash, r.seq, "content hash mismatch")
        prev_hash, expected_seq = r.hash, expected_seq + 1
        checked += 1
    last = records[-1] if records else None
    return VerifyResult(True, checked, last.seq if last else None, last.hash if last else None)


async def verify_chain(session: AsyncSession, batch: int = 5000) -> VerifyResult:
    prev, expected, total = GENESIS_HASH, 1, 0
    head_seq: int | None = None
    head_hash: str | None = None
    while True:
        rows = (
            await session.execute(
                text(
                    "SELECT seq, org_id, actor, action, target, meta, ts, prev_hash, hash FROM audit_log "
                    "WHERE seq >= :s ORDER BY seq LIMIT :n"
                ),
                {"s": expected, "n": batch},
            )
        ).all()
        if not rows:
            break
        recs = [
            AuditRecord(r.seq, str(r.org_id), r.actor, r.action, r.target, r.meta or {}, r.ts, r.prev_hash, r.hash)
            for r in rows
        ]
        res = verify_records(recs, prev, expected)
        total += res.checked
        if not res.ok:
            res.checked = total
            return res
        prev, expected = recs[-1].hash, recs[-1].seq + 1
        head_seq, head_hash = recs[-1].seq, recs[-1].hash
    return VerifyResult(True, total, head_seq, head_hash)
