"""Apache AGE helpers: run parameterised Cypher against a graph inside the current transaction.

Parameters go through AGE's ``agtype`` params argument and are never string-interpolated into the query,
so callers can't inject Cypher. Only the graph name and the column list are formatted into the SQL, and
both are validated as identifiers.
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


def _ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"invalid identifier: {name!r}")
    return name


async def prepare(session: AsyncSession) -> None:
    await session.execute(text("LOAD '$libdir/plugins/age'"))
    await session.execute(text('SET LOCAL search_path = ag_catalog, "$user", public'))


def _dollar_quote(query: str) -> str:
    tag = "$cq$"
    if tag in query:
        raise ValueError("query may not contain $cq$")
    # SQLAlchemy text() would read ":TYPE" in "-[:TYPE]->" as a bind parameter; escape every colon.
    return f"{tag}{query.replace(':', chr(92) + ':')}{tag}"


async def cypher(
    session: AsyncSession,
    graph: str,
    query: str,
    params: dict[str, Any] | None = None,
    columns: tuple[str, ...] = ("result",),
) -> list[dict[str, Any]]:
    """Execute Cypher and return rows as dicts of decoded agtype values."""
    await prepare(session)
    cols = ", ".join(f"{_ident(c)} agtype" for c in columns)
    sql = f"SELECT * FROM ag_catalog.cypher('{_ident(graph)}', {_dollar_quote(query)}"  # noqa: S608
    bind: dict[str, Any] = {}
    if params:
        # AGE requires the 3rd argument to be a bare bind parameter (no CAST); psycopg sends str
        # with the "unknown" type, so Postgres infers agtype from the function signature.
        sql += ", :params"
        bind["params"] = json.dumps(params)
    sql += f") AS ({cols})"
    rows = (await session.execute(text(sql), bind)).mappings().all()
    return [{k: decode_agtype(v) for k, v in r.items()} for r in rows]


_SUFFIX = re.compile(r"::(vertex|edge|path|numeric)(?=\s*[,\]}]|$)")


def decode_agtype(value: Any) -> Any:
    """agtype text → Python. Vertex/edge/path values carry a ``::vertex`` style suffix."""
    if value is None or not isinstance(value, str):
        return value
    try:
        return json.loads(_SUFFIX.sub("", value))
    except json.JSONDecodeError:
        return value
