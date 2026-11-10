"""Apply scripts/schema_mysql.sql statement by statement.

The schema file is written for the mysql CLI: it switches to ``DELIMITER $$`` for trigger bodies, which a
naive ``split(";")`` breaks apart. ``split_mysql_script`` honours DELIMITER so drivers that execute one
statement at a time (pymysql, Alembic) install the triggers too.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

SCHEMA_FILE = Path(__file__).resolve().parents[2] / "scripts" / "schema_mysql.sql"

# Server-level statements that need administrative privileges. The application user cannot run them;
# they belong to MySQL provisioning (infra/mysql/init), not to the application schema.
_ADMIN_PREFIXES = ("CREATE DATABASE", "GRANT ")


def split_mysql_script(sql: str) -> list[str]:
    """Split a mysql-CLI script into executable statements, honouring DELIMITER and dropping comments."""
    statements: list[str] = []
    delimiter = ";"
    buf: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if not buf and (not stripped or stripped.startswith("--")):
            continue
        if stripped.upper().startswith("DELIMITER "):
            delimiter = stripped.split(None, 1)[1]
            continue
        if stripped.startswith("--"):
            continue
        buf.append(line)
        if stripped.endswith(delimiter):
            stmt = "\n".join(buf).strip()
            stmt = stmt[: -len(delimiter)].strip()
            if stmt:
                statements.append(stmt)
            buf = []
    tail = "\n".join(buf).strip()
    if tail:
        raise ValueError(f"unterminated statement at end of script: {tail[:80]!r}")
    return statements


def schema_statements(path: Path = SCHEMA_FILE, include_admin: bool = False) -> list[str]:
    """Statements of the MySQL application schema, optionally keeping CREATE DATABASE / GRANT."""
    stmts = split_mysql_script(path.read_text(encoding="utf-8"))
    if include_admin:
        return stmts
    return [s for s in stmts if not s.upper().startswith(_ADMIN_PREFIXES)]


def apply_statements(cursor, statements: Iterable[str]) -> None:
    """Execute statements on a DB-API cursor (no parameter interpolation)."""
    for stmt in statements:
        cursor.execute(stmt)
