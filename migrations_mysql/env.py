"""Alembic environment for the MySQL 8.4 schema (the default: ``alembic upgrade head``; ``-n mysql`` is equivalent).

The PostgreSQL history in ``migrations/`` is PostgreSQL-only DDL (extensions, plpgsql, jsonb); this tree
versions the MySQL schema independently, starting from scripts/schema_mysql.sql.
"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine, pool

config = context.config


def _url() -> str:
    url = os.environ.get("DATABASE_URL") or config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    if not url.startswith("mysql"):
        raise RuntimeError(
            "migrations_mysql only targets MySQL; use `alembic -n postgres` for the PostgreSQL rollback history"
        )
    # Alembic runs synchronously.
    return url.replace("+asyncmy", "+pymysql").replace("+aiomysql", "+pymysql")


def run_migrations_offline() -> None:
    context.configure(url=_url(), literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
