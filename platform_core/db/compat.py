"""SQL compatibility helpers for dialect-agnostic queries across PostgreSQL and MySQL 8.4."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

MYSQL_DUP_KEY = 1062  # ER_DUP_ENTRY: duplicate value for a PRIMARY/UNIQUE key


def mysql_error_code(exc: BaseException) -> int | None:
    """The MySQL error number behind a SQLAlchemy DBAPIError (e.g. 1062 duplicate key, 1452 FK, 3819 CHECK), or None.

    Used to treat *only* a duplicate key as "already there" (PostgreSQL ON CONFLICT DO NOTHING) while every other
    integrity error still raises, unlike INSERT IGNORE, which also silences FK/CHECK/NOT NULL violations."""
    orig = getattr(exc, "orig", None)
    args = getattr(orig, "args", None) or ()
    return args[0] if args and isinstance(args[0], int) else None


async def insert_or_skip_duplicate(session: AsyncSession, stmt: Any, params: dict[str, Any]) -> Any:
    """MySQL equivalent of PostgreSQL ``INSERT … ON CONFLICT DO NOTHING``: run a plain INSERT in a savepoint and treat
    *only* a duplicate key (1062) as "already there". Returns an object with ``rowcount`` (1 inserted, 0 duplicate), so
    callers written against ``INSERT IGNORE`` keep working, but FK/CHECK/NOT NULL violations now raise instead of being
    silently downgraded to warnings."""
    try:
        async with session.begin_nested():
            await session.execute(stmt, params)
        return SimpleNamespace(rowcount=1)
    except IntegrityError as e:
        if mysql_error_code(e) != MYSQL_DUP_KEY:
            raise
        return SimpleNamespace(rowcount=0)


def is_mysql_session(session: AsyncSession) -> bool:
    """Check if the session bind dialect is MySQL."""
    bind = session.get_bind()
    return bool(bind is not None and getattr(bind, "dialect", None) and bind.dialect.name == "mysql")


def in_clause(
    col: str,
    *args: Any,
    prefix: str | None = None,
    values: list[Any] | set[Any] | tuple[Any, ...] | None = None,
    params: dict[str, Any] | None = None,
) -> Any:
    """Generate a parameter-safe `col IN (:p_0, :p_1, ...)` clause.

    Supports two calling conventions:
    1. In-place dict: in_clause(col, prefix, values, params) -> returns str (updates params in place)
    2. Tuple return: in_clause(col, values, prefix="p") -> returns (clause_str, params_dict)
    """
    return_tuple = False
    actual_prefix = "p"
    actual_values: list[Any] = []
    actual_params: dict[str, Any] = {}

    if len(args) == 3:
        # in_clause(col, prefix, values, params)
        actual_prefix = str(args[0])
        actual_values = list(args[1]) if args[1] is not None else []
        actual_params = args[2]
        return_tuple = False
    elif len(args) == 2:
        if isinstance(args[1], dict):
            # in_clause(col, values, params)
            actual_values = list(args[0]) if args[0] is not None else []
            actual_params = args[1]
            actual_prefix = prefix or "p"
            return_tuple = False
        else:
            # in_clause(col, prefix, values)
            actual_prefix = str(args[0])
            actual_values = list(args[1]) if args[1] is not None else []
            return_tuple = True
    elif len(args) == 1:
        # in_clause(col, values, prefix=...)
        actual_values = list(args[0]) if args[0] is not None else []
        actual_prefix = prefix or "p"
        if params is not None:
            actual_params = params
            return_tuple = False
        else:
            return_tuple = True
    else:
        # kwargs only
        if values is not None:
            actual_values = list(values)
        if prefix is not None:
            actual_prefix = prefix
        if params is not None:
            actual_params = params
            return_tuple = False
        else:
            return_tuple = True

    if not actual_values:
        clause = "1=0"
    else:
        keys: list[str] = []
        for i, v in enumerate(actual_values):
            k = f"{actual_prefix}_{i}"
            keys.append(f":{k}")
            actual_params[k] = v
        clause = f"{col} IN ({', '.join(keys)})"

    if return_tuple:
        return clause, actual_params
    return clause


def order_by_nulls(
    col: str,
    direction: str = "ASC",
    nulls: str = "LAST",
    nulls_first: bool | None = None,
    asc: bool | None = None,
    nulls_last: bool | None = None,
) -> str:
    """Generate ANSI/MySQL-compatible NULL ordering.

    `NULLS LAST` on ASC: `(col IS NULL), col ASC`
    `NULLS LAST` on DESC: `(col IS NULL), col DESC`
    `NULLS FIRST` on ASC: `(col IS NOT NULL), col ASC`
    `NULLS FIRST` on DESC: `(col IS NOT NULL), col DESC`
    """
    if asc is not None:
        direction = "ASC" if asc else "DESC"
    if nulls_last is not None:
        nulls = "LAST" if nulls_last else "FIRST"
    if nulls_first is not None:
        nulls = "FIRST" if nulls_first else "LAST"
    dir_upper = direction.upper().strip()
    nulls_upper = nulls.upper().strip()
    if nulls_upper == "LAST":
        return f"({col} IS NULL), {col} {dir_upper}"
    else:  # FIRST
        return f"({col} IS NOT NULL), {col} {dir_upper}"
