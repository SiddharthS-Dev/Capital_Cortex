"""JSON-safe conversion of DB rows (UUID, datetime, Decimal) shared by every layer."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

# Columns declared BOOLEAN in scripts/schema_mysql.sql. MySQL stores BOOLEAN as TINYINT(1) and the driver returns 0/1;
# PostgreSQL returns bool. row() turns 0/1 back into false/true for exactly these names (kept in sync with the schema by
# tests/unit/test_mysql_serialization.py), so the API contract is the same on both databases.
BOOL_COLUMNS = frozenset(
    {
        "is_demo", "legal_hold", "enabled", "trained_on_demo", "recipient_external", "mfa", "is_latest", "is_default",
        "incomplete", "dry_run", "approved_repo", "active",
    }
)  # fmt: skip


def jsonable(v: Any) -> Any:
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, datetime):
        # Instants are stored in UTC. MySQL DATETIME comes back naive: emit it with an explicit +00:00, otherwise a
        # browser parses the offset-less string as *local* time. Aware values keep their own offset.
        return (v.replace(tzinfo=UTC) if v.tzinfo is None else v).isoformat()
    if isinstance(v, date):
        return v.isoformat()  # date-only: no time zone
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, dict):
        return {k: jsonable(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [jsonable(x) for x in v]
    if isinstance(v, (bytes, bytearray)):
        try:
            return jsonable(json.loads(v.decode("utf-8")))
        except Exception:
            return v.decode("utf-8", errors="replace")
    if isinstance(v, str) and len(v) >= 2 and v[0] in ("{", "[") and v[-1] in ("}", "]"):
        try:
            parsed = json.loads(v)
            if isinstance(parsed, (dict, list)):
                return jsonable(parsed)
        except ValueError:
            pass
    return v


def _bool_col(k: str, v: Any) -> Any:
    return bool(v) if k in BOOL_COLUMNS and type(v) is int and v in (0, 1) else v


def row(r: Any) -> dict[str, Any]:
    return {k: jsonable(_bool_col(k, v)) for k, v in dict(r).items()}


_MISSING: Any = object()


def json_obj(v: Any, default: Any = _MISSING) -> Any:
    """Decode a JSON column value read with ``text()`` SQL.

    PostgreSQL ``jsonb`` arrives already decoded (dict/list/scalar); MySQL ``JSON`` arrives as its text
    (asyncmy/pymysql) or bytes. This returns the decoded value in both cases, so callers can index/iterate it.

    - ``None`` (SQL NULL) → ``default`` if given, else ``None``.
    - str/bytes → ``json.loads`` of it (objects, arrays, ``null``, booleans and numbers keep their JSON types).
    - Malformed text raises ``ValueError``: a corrupt document must not be silently treated as empty.

    Only for columns of SQL type JSON/jsonb: a plain text column holding a non-JSON string would raise.
    """
    if v is None:
        return None if default is _MISSING else default
    if isinstance(v, bytes | bytearray):
        v = v.decode("utf-8")
    if isinstance(v, str):
        return json.loads(v)
    return v


def as_utc(v: Any) -> Any:
    """Normalise a timestamp read from the database to a timezone-aware UTC ``datetime``.

    Cortex stores instants in UTC: PostgreSQL ``timestamptz`` returns aware values; MySQL ``DATETIME`` returns naive
    values that hold UTC (server and session ``time_zone`` are ``+00:00``). Naive → tagged UTC (not shifted); aware
    → converted to UTC. ``date`` (date-only fields) and ``None`` pass through unchanged.
    """
    if isinstance(v, datetime):
        return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)
    return v
