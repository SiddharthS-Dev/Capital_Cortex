"""PostgreSQL 16 to MySQL 8.4 ETL Migration and Reconciliation Tool (Phase 10).

Features:
- Streaming / chunked batch extraction from PostgreSQL
- Data type transformations: UUID -> string VARCHAR(36), text[]/uuid[] -> JSON array,
  vector -> IEEE-754 float32 packed VARBINARY(4096) via to_blob(), timestamps, booleans
- Target safety guard: prevents writing to default production ports or databases without confirmation
- Transactional batch insertion into MySQL with FOREIGN_KEY_CHECKS toggled safely in finally blocks
- Dry-run mode for non-destructive pre-flight verification
- Reconciliation that fails closed: table and column coverage against an explicit policy registry,
  row counts, order-independent SHA-256 checksums of source rows vs rows read back from MySQL,
  foreign-key orphan detection, audit-mutex presence and audit chain verification (verify_records)
"""

from __future__ import annotations

import argparse
import decimal
import hashlib
import json
import logging
import os
import re
import sys
import time
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

# Ensure root is in sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from platform_core.audit.chain import GENESIS_HASH, AuditRecord, verify_records
from platform_core.db.vector import to_blob, validate_blob
from scripts import secure_connect

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
log = logging.getLogger("cortex_etl")

DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000001"

# Canonical table dependency order for migration: every table appears after every table it references
# (checked against scripts/schema_mysql.sql by tests/unit/test_migrate_pg_to_mysql.py).
TABLE_MIGRATION_ORDER: list[str] = [
    "tenant",
    "inference",
    "scoring_profile",
    "source",
    "source_run",
    "`signal`",
    "organization",
    "entity",
    "relationship_edge",
    "entity_merge_candidate",
    "investor",
    "fund",
    "grant_program",
    "financial_instrument",
    "opportunity",
    "embedding",
    "contact",
    "meeting",
    "interaction",
    "relationship",
    "milestone",
    "factor_history",
    "financial_snapshot",
    "forecast",
    "ml_model",
    "outcome",
    "memory",
    "agent_run",
    "recommendation",
    "approval",
    "approval_decision",
    "outbox",
    "alert_rule",
    "alert",
    "alert_delivery",
    "document",
    "dataroom_package",
    "document_access",
    "share_link",
    "proposal",
    "proposal_version",
    "proposal_export",
    "board_report",
    "legal_hold",
    "retention_run",
    "setting",
    "audit_log",
    "api_idempotency",
]

# Every table found in either database must have exactly one policy: copied (TABLE_MIGRATION_ORDER),
# target-only, or source-only. Anything else fails preflight instead of being silently ignored.
TARGET_ONLY_TABLES: dict[str, str] = {
    "audit_lock": "MySQL-only mutex row for audit appends; seeded by schema_mysql.sql (id=1), never copied",
    "alembic_version": "MySQL schema version bookkeeping (migrations_mysql); not application data",
}
SOURCE_ONLY_TABLES: dict[str, str] = {
    "alembic_version": "PostgreSQL schema version bookkeeping; MySQL keeps its own history",
}

# Rows schema_mysql.sql inserts into copied tables. They are removed right before the table is loaded so
# the source copy of the same row lands without a duplicate-key error.
SCHEMA_SEED_ROWS: dict[str, tuple[str, tuple[str, ...]]] = {
    "tenant": ("id", (DEFAULT_TENANT_ID,)),
}

# Source columns deliberately not carried over, as {table: {column: reason}}. Generated columns are skipped
# automatically; any other source column without a MySQL counterpart fails preflight.
DROPPED_SOURCE_COLUMNS: dict[str, dict[str, str]] = {}

# pgvector columns, packed to IEEE-754 float32 VARBINARY(4096) on the MySQL side.
VECTOR_COLUMNS: frozenset[tuple[str, str]] = frozenset({("embedding", "vector")})

# Declared value rewrites, applied both when loading and when computing the expected source checksum.
VALUE_MAPPINGS: dict[tuple[str, str], dict[Any, Any]] = {
    ("source_run", "status"): {"success": "succeeded"},
}

_GENERATED_EXTRA = re.compile(r"\b(VIRTUAL|STORED) GENERATED\b", re.IGNORECASE)


class MigrationError(Exception):
    """Raised when ETL migration encounters a fatal error."""


def migrated_tables() -> list[str]:
    """TABLE_MIGRATION_ORDER without identifier quoting."""
    return [t.strip("`") for t in TABLE_MIGRATION_ORDER]


def validate_migration_registry() -> None:
    """Reject duplicate entries and tables with more than one policy."""
    tables = migrated_tables()
    dupes = sorted({t for t in tables if tables.count(t) > 1})
    if dupes:
        raise MigrationError(f"Duplicate tables in TABLE_MIGRATION_ORDER: {dupes}")
    overlap = sorted(set(tables) & (set(TARGET_ONLY_TABLES) | set(SOURCE_ONLY_TABLES)))
    if overlap:
        raise MigrationError(f"Tables listed as both migrated and not migrated: {overlap}")


def check_table_inventory(source_tables: Iterable[str], target_tables: Iterable[str]) -> list[str]:
    """Compare live table inventories with the policy registry; return one message per problem."""
    src, tgt, mig = set(source_tables), set(target_tables), set(migrated_tables())
    problems = [f"{t}: required source table missing" for t in sorted(mig - src)]
    problems += [f"{t}: required target table missing" for t in sorted(mig - tgt)]
    problems += [f"{t}: source table has no migration policy" for t in sorted(src - mig - set(SOURCE_ONLY_TABLES))]
    problems += [f"{t}: target table has no migration policy" for t in sorted(tgt - mig - set(TARGET_ONLY_TABLES))]
    return problems


@dataclass
class ColumnPlan:
    """How one table's columns map from PostgreSQL to MySQL."""

    table: str
    insert_cols: list[str] = field(default_factory=list)
    source_json_cols: set[str] = field(default_factory=set)  # PG json/jsonb: always serialised on load
    target_json_cols: set[str] = field(default_factory=set)  # MySQL JSON: parsed when read back
    array_cols: set[str] = field(default_factory=set)
    vector_cols: set[str] = field(default_factory=set)
    skipped_generated: list[str] = field(default_factory=list)
    target_only_cols: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def source_parse_cols(self) -> set[str]:
        """Text source columns landing in MySQL JSON: the expected value is the parsed text."""
        return self.target_json_cols - self.source_json_cols - self.array_cols


def plan_columns(
    table: str,
    pg_cols: Sequence[tuple[str, str, str, str]],
    mysql_cols: Sequence[tuple[str, str, str]],
) -> ColumnPlan:
    """Build the column plan from information_schema rows.

    pg_cols: (column_name, data_type, udt_name, is_generated); mysql_cols: (COLUMN_NAME, DATA_TYPE, EXTRA).
    """
    plan = ColumnPlan(table=table)
    my = {name: ((dtype or "").lower(), extra or "") for name, dtype, extra in mysql_cols}
    dropped = DROPPED_SOURCE_COLUMNS.get(table, {})
    for name, dtype, udt, generated in pg_cols:
        if (generated or "").upper() == "ALWAYS":
            plan.skipped_generated.append(name)
            continue
        if name in dropped:
            continue
        if name not in my:
            plan.problems.append(f"{table}.{name}: source column has no MySQL column (data would be dropped)")
            continue
        my_type, my_extra = my[name]
        if _GENERATED_EXTRA.search(my_extra):
            plan.problems.append(f"{table}.{name}: MySQL column is generated and cannot take the source value")
            continue
        if (udt or "").lower() == "vector":
            if (table, name) not in VECTOR_COLUMNS:
                plan.problems.append(f"{table}.{name}: vector column not registered in VECTOR_COLUMNS")
                continue
            plan.vector_cols.add(name)
        if (dtype or "").lower() in ("json", "jsonb"):
            plan.source_json_cols.add(name)
        if (dtype or "").upper() == "ARRAY":
            plan.array_cols.add(name)
        if my_type == "json":
            plan.target_json_cols.add(name)
        plan.insert_cols.append(name)
    pg_names = {c[0] for c in pg_cols}
    plan.target_only_cols = [
        n for n, (_, extra) in my.items() if n not in pg_names and not _GENERATED_EXTRA.search(extra)
    ]
    return plan


def _json_default(o: Any) -> Any:
    if isinstance(o, uuid.UUID):
        return str(o)
    if isinstance(o, decimal.Decimal):
        return str(o)
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


class CanonicalEncoder(json.JSONEncoder):
    """Deterministic JSON encoder for canonical SHA-256 row checksums."""

    def default(self, o: Any) -> Any:
        if isinstance(o, bytes):
            return o.hex()
        return _json_default(o)


def _utc_naive(val: datetime) -> datetime:
    """MySQL DATETIME has no zone and the audit chain reads naive values as UTC, so store UTC."""
    if val.tzinfo is None:
        return val
    return val.astimezone(UTC).replace(tzinfo=None)


def _decimal_str(val: decimal.Decimal) -> str:
    if not val.is_finite():
        return str(val)
    s = format(val, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return "0" if s in ("", "-0") else s


def vector_blob(val: Any) -> bytes:
    """Pack a pgvector value (text '[..]', list, numpy array or existing blob) into 4096 bytes."""
    if isinstance(val, (bytes, bytearray, memoryview)):
        validate_blob(val)
        return bytes(val)
    if hasattr(val, "tolist"):
        return to_blob(val.tolist())
    if isinstance(val, str):
        s = val.strip()
        if not (s.startswith("[") and s.endswith("]")):
            raise ValueError(f"unrecognised vector literal: {s[:40]!r}")
        return to_blob([float(x) for x in s[1:-1].split(",") if x.strip()])
    return to_blob(val)


def canonical_value(val: Any) -> Any:
    """Normalise one value so the same data hashes identically whether read from PostgreSQL or MySQL."""
    if val is None:
        return None
    if isinstance(val, bool):
        return 1 if val else 0
    if isinstance(val, uuid.UUID):
        return str(val)
    if isinstance(val, datetime):
        return _utc_naive(val).strftime("%Y-%m-%d %H:%M:%S.%f")
    if isinstance(val, date):
        return val.isoformat()
    if isinstance(val, decimal.Decimal):
        return _decimal_str(val)
    if isinstance(val, float):
        return repr(val)
    if isinstance(val, (bytes, bytearray, memoryview)):
        return bytes(val).hex()
    if isinstance(val, dict):
        return {str(k): canonical_value(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        return [canonical_value(v) for v in val]
    if hasattr(val, "tolist"):
        return canonical_value(val.tolist())
    return val


def canonical_row_hash(
    row: dict[str, Any],
    json_columns: Iterable[str] = (),
    vector_columns: Iterable[str] = (),
) -> str:
    """Compute deterministic SHA-256 hash of a database row dictionary.

    json_columns hold JSON text to parse before hashing; vector_columns are compared as packed float32 bytes.
    """
    json_cols, vec_cols = set(json_columns), set(vector_columns)
    normalized = {}
    for k, v in row.items():
        if v is not None and k in vec_cols:
            normalized[k] = vector_blob(v).hex()
            continue
        if k in json_cols and isinstance(v, (str, bytes, bytearray)):
            v = json.loads(v)
        normalized[k] = canonical_value(v)

    data = json.dumps(normalized, sort_keys=True, cls=CanonicalEncoder, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def combine_row_hashes(row_hashes: list[str]) -> str:
    """Order-independent table checksum: PostgreSQL and MySQL return unordered rows in different orders."""
    digest = hashlib.sha256()
    for h in sorted(row_hashes):
        digest.update(h.encode("utf-8"))
    return digest.hexdigest()


def transform_value(val: Any, col_name: str, table_name: str, source_is_json: bool = False) -> Any:
    """Transform a single extracted value to MySQL-compatible representation."""
    if val is None:
        return None

    # Vector column transformation
    if (table_name, col_name) in VECTOR_COLUMNS:
        return vector_blob(val)

    mapping = VALUE_MAPPINGS.get((table_name, col_name))
    if mapping is not None and isinstance(val, str):
        return mapping.get(val, val)

    # JSON / Array columns (jsonb scalars must be serialised too, or MySQL rejects them as invalid JSON)
    if source_is_json or isinstance(val, (dict, list)):
        return json.dumps(val, default=_json_default)

    # Boolean mapping for MySQL TINYINT(1)
    if isinstance(val, bool):
        return 1 if val else 0

    # Datetime: convert aware values to UTC before dropping the zone
    if isinstance(val, datetime):
        return _utc_naive(val).strftime("%Y-%m-%d %H:%M:%S.%f")

    # UUID objects to standard string
    if isinstance(val, uuid.UUID):
        return str(val)

    return val


def transform_row(row: dict[str, Any], table_name: str, json_columns: Iterable[str] = ()) -> dict[str, Any]:
    """Transform an entire row mapping for MySQL insertion."""
    clean_table = table_name.strip("`")
    json_cols = set(json_columns)
    return {k: transform_value(v, k, clean_table, k in json_cols) for k, v in row.items()}


def expected_source_row(row: dict[str, Any], table_name: str) -> dict[str, Any]:
    """Apply declared VALUE_MAPPINGS so the source checksum describes what MySQL should hold."""
    out = dict(row)
    for (tbl, col), mapping in VALUE_MAPPINGS.items():
        if tbl == table_name and isinstance(out.get(col), str):
            out[col] = mapping.get(out[col], out[col])
    return out


def build_orphan_queries(fk_rows: Sequence[tuple[str, str, str, str, str]]) -> list[tuple[str, str]]:
    """Turn KEY_COLUMN_USAGE rows (constraint, table, column, ref_table, ref_column), ordered by position,
    into one orphan-count query per foreign key. NULL child keys are not orphans (MATCH SIMPLE)."""
    grouped: dict[tuple[str, str, str], list[tuple[str, str]]] = {}
    for constraint, table, column, ref_table, ref_column in fk_rows:
        grouped.setdefault((table, constraint, ref_table), []).append((column, ref_column))
    queries = []
    for (table, constraint, ref_table), pairs in grouped.items():
        on = " AND ".join(f"c.`{c}` = p.`{r}`" for c, r in pairs)
        not_null = " AND ".join(f"c.`{c}` IS NOT NULL" for c, _ in pairs)
        sql = (
            f"SELECT COUNT(*) FROM `{table}` c LEFT JOIN `{ref_table}` p ON {on} "
            f"WHERE {not_null} AND p.`{pairs[0][1]}` IS NULL"
        )
        queries.append((f"{table}.{constraint} -> {ref_table}", sql))
    return queries


class PostgresToMySQLMigrator:
    """Orchestrates streaming ETL migration and reconciliation."""

    def __init__(
        self,
        pg_config: dict[str, Any],
        mysql_config: dict[str, Any],
        batch_size: int = 1000,
        dry_run: bool = False,
    ):
        self.pg_config = pg_config
        self.mysql_config = mysql_config
        self.batch_size = batch_size
        self.dry_run = dry_run
        self._verify_target_safety()

    def _verify_target_safety(self) -> None:
        """Enforce strict protection against unintended target modifications."""
        target_port = int(self.mysql_config.get("port", 3306))
        target_db = self.mysql_config.get("database", "")

        # Default MySQL production port 3306 check
        if target_port == 3306 and not os.environ.get("ALLOW_PROD_PORT_MIGRATION"):
            if not self.dry_run:
                raise MigrationError(
                    f"Safety Violation: Target port {target_port} is default production port 3306. "
                    "Refusing execution without explicit ALLOW_PROD_PORT_MIGRATION=1 override."
                )

        if "cortex_prod" in target_db.lower() and not self.dry_run:
            raise MigrationError(f"Safety Violation: Refusing automated migration directly into {target_db}.")

    def _column_plan(self, pg_conn: Any, mysql_conn: Any, table: str) -> ColumnPlan:
        """Read both information_schemas for one table and build its ColumnPlan."""
        with pg_conn.cursor() as cur:
            cur.execute(
                "SELECT column_name, data_type, udt_name, is_generated FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position",
                (table,),
            )
            pg_cols = cur.fetchall()

        with mysql_conn.cursor() as cur:
            cur.execute(
                "SELECT COLUMN_NAME, DATA_TYPE, EXTRA FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION",
                (table,),
            )
            mysql_cols = cur.fetchall()

        plan = plan_columns(table, pg_cols, mysql_cols)
        if not pg_cols:
            plan.problems.append(f"{table}: required source table missing")
        if not mysql_cols:
            plan.problems.append(f"{table}: required target table missing")
        if pg_cols and mysql_cols and not plan.insert_cols:
            plan.problems.append(f"{table}: no loadable columns")
        return plan

    def preflight(self, pg_conn: Any, mysql_conn: Any) -> list[str]:
        """Read-only checks that must all pass before anything is written to the target."""
        problems: list[str] = []
        with pg_conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
            )
            source_tables = {r[0] for r in cur.fetchall()}

        with mysql_conn.cursor() as cur:
            cur.execute(
                "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE'"
            )
            target_tables = {r[0] for r in cur.fetchall()}
            cur.execute("SELECT @@SESSION.sql_mode")
            sql_mode = (cur.fetchone()[0] or "").upper()

        # Without strict mode MySQL truncates oversize or invalid values with only a warning.
        if "STRICT_TRANS_TABLES" not in sql_mode and "STRICT_ALL_TABLES" not in sql_mode:
            problems.append(f"MySQL sql_mode is not strict ({sql_mode or 'empty'}); values could be silently truncated")

        problems += check_table_inventory(source_tables, target_tables)
        for tbl in migrated_tables():
            if tbl in source_tables and tbl in target_tables:
                problems += self._column_plan(pg_conn, mysql_conn, tbl).problems
        problems += self._target_population_problems(mysql_conn, target_tables)
        return problems

    def _target_population_problems(self, mysql_conn: Any, target_tables: set[str]) -> list[str]:
        """The target must be a freshly created schema: only SCHEMA_SEED_ROWS may be present."""
        problems = []
        with mysql_conn.cursor() as cur:
            for tbl in migrated_tables():
                if tbl not in target_tables:
                    continue
                seed = SCHEMA_SEED_ROWS.get(tbl)
                if seed:
                    key, values = seed
                    marks = ", ".join(["%s"] * len(values))
                    cur.execute(f"SELECT COUNT(*) FROM `{tbl}` WHERE `{key}` NOT IN ({marks})", values)
                else:
                    cur.execute(f"SELECT COUNT(*) FROM `{tbl}`")
                n = cur.fetchone()[0]
                if n:
                    problems.append(f"{tbl}: target already holds {n} row(s); load into an empty schema")
        return problems

    def _delete_seed_rows(self, mysql_conn: Any, table: str) -> None:
        key, values = SCHEMA_SEED_ROWS[table]
        marks = ", ".join(["%s"] * len(values))
        with mysql_conn.cursor() as cur:
            cur.execute(f"DELETE FROM `{table}` WHERE `{key}` IN ({marks})", values)
        mysql_conn.commit()

    def _target_checksum(self, mysql_conn: Any, table: str, plan: ColumnPlan) -> tuple[int, str]:
        """Read the loaded rows back from MySQL and checksum what was actually stored."""
        import pymysql.cursors

        cols = plan.insert_cols
        hashes: list[str] = []
        with mysql_conn.cursor(pymysql.cursors.SSCursor) as cur:
            cur.execute(f"SELECT {', '.join(f'`{c}`' for c in cols)} FROM `{table}`")
            while True:
                rows = cur.fetchmany(self.batch_size)
                if not rows:
                    break
                hashes.extend(
                    canonical_row_hash(dict(zip(cols, r, strict=True)), plan.target_json_cols, plan.vector_cols)
                    for r in rows
                )
        return len(hashes), combine_row_hashes(hashes)

    def migrate_table(
        self,
        pg_conn: Any,
        mysql_conn: Any,
        table: str,
    ) -> dict[str, Any]:
        """Migrate a single table in bounded batches."""
        clean_tbl = table.strip("`")
        quoted_mysql = f"`{clean_tbl}`"
        quoted_pg = f'"{clean_tbl}"'

        stats: dict[str, Any] = {
            "table": clean_tbl,
            "extracted": 0,
            "loaded": 0,
            "errors": 0,
            "source_checksum": None,
            "target_checksum": None,
            "problems": [],
        }

        plan = self._column_plan(pg_conn, mysql_conn, clean_tbl)
        if plan.problems:
            stats["problems"] = plan.problems
            for p in plan.problems:
                log.error("Table %s not migrated: %s", clean_tbl, p)
            return stats
        stats["skipped_generated_columns"] = plan.skipped_generated
        stats["target_only_columns"] = plan.target_only_cols

        cols = plan.insert_cols
        cols_clause = ", ".join(f"`{c}`" for c in cols)
        placeholders = ", ".join(["%s"] * len(cols))
        insert_sql = f"INSERT INTO {quoted_mysql} ({cols_clause}) VALUES ({placeholders})"
        select_cols_pg = ", ".join(f'"{c}"' for c in cols)
        select_sql = f"SELECT {select_cols_pg} FROM {quoted_pg}"

        parse_cols = plan.source_parse_cols()
        source_hashes: list[str] = []

        if not self.dry_run and clean_tbl in SCHEMA_SEED_ROWS:
            self._delete_seed_rows(mysql_conn, clean_tbl)

        # Fetch in batches from PostgreSQL
        with pg_conn.cursor(name=f"stream_{clean_tbl}") as stream_cur:
            stream_cur.itersize = self.batch_size
            stream_cur.execute(select_sql)

            while True:
                rows = stream_cur.fetchmany(self.batch_size)
                if not rows:
                    break

                batch_dicts = [dict(zip(cols, r, strict=True)) for r in rows]
                source_hashes.extend(
                    canonical_row_hash(expected_source_row(d, clean_tbl), parse_cols, plan.vector_cols)
                    for d in batch_dicts
                )
                stats["extracted"] += len(rows)

                if not self.dry_run:
                    transformed_rows = [transform_row(d, clean_tbl, plan.source_json_cols) for d in batch_dicts]
                    batch_tuples = [tuple(t[c] for c in cols) for t in transformed_rows]
                    with mysql_conn.cursor() as my_cur:
                        my_cur.executemany(insert_sql, batch_tuples)
                    mysql_conn.commit()
                    stats["loaded"] += len(batch_tuples)

        stats["source_checksum"] = combine_row_hashes(source_hashes) if stats["extracted"] > 0 else "EMPTY"
        if self.dry_run:
            stats["target_checksum"] = "DRY_RUN"
        else:
            read_back, target_checksum = self._target_checksum(mysql_conn, clean_tbl, plan)
            stats["target_rows_read"] = read_back
            stats["target_checksum"] = target_checksum if read_back > 0 else "EMPTY"

        log.info(
            "Table %s: Extracted=%d, Loaded=%d, ChecksumMatch=%s",
            clean_tbl,
            stats["extracted"],
            stats["loaded"],
            stats["source_checksum"] == stats["target_checksum"] if not self.dry_run else "DRY_RUN",
        )
        return stats

    def run_reconciliation(self, mysql_conn: Any, table_stats: list[dict[str, Any]]) -> dict[str, Any]:
        """Perform comprehensive post-migration reconciliation. Any unexplained gap fails the run."""
        log.info("Executing reconciliation and audit chain verification...")
        reconciliation: dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "total_tables": len(table_stats),
            "expected_tables": len(migrated_tables()),
            "table_results": [],
            "row_count_mismatches": 0,
            "checksum_mismatches": 0,
            "orphan_violations": [],
            "audit_lock_present": False,
            "audit_chain_valid": False,
            "problems": [],
            "overall_status": "FAILED",
        }
        problems: list[str] = reconciliation["problems"]

        # Coverage: a report that omits a required table must never pass.
        names = [s["table"] for s in table_stats]
        expected = migrated_tables()
        problems += [f"{t}: required table missing from migration results" for t in expected if t not in names]
        problems += [f"{t}: unexpected table in migration results" for t in sorted(set(names) - set(expected))]
        problems += [f"{t}: table reported more than once" for t in sorted({t for t in names if names.count(t) > 1})]

        for stat in table_stats:
            tbl = stat["table"]
            extracted = stat["extracted"]
            stat_problems = list(stat.get("problems") or [])
            problems += stat_problems

            if self.dry_run:
                actual_mysql_count = 0
                count_match = checksum_match = not stat_problems
            elif stat_problems:
                actual_mysql_count = None
                count_match = checksum_match = False
            else:
                with mysql_conn.cursor() as cur:
                    cur.execute(f"SELECT COUNT(*) FROM `{tbl}`")
                    actual_mysql_count = cur.fetchone()[0]
                count_match = extracted == actual_mysql_count == stat["loaded"]
                checksum_match = stat["source_checksum"] == stat["target_checksum"]

            if not count_match:
                reconciliation["row_count_mismatches"] += 1
            if not checksum_match and not self.dry_run:
                reconciliation["checksum_mismatches"] += 1

            reconciliation["table_results"].append(
                {
                    "table": tbl,
                    "source_rows": extracted,
                    "target_rows": actual_mysql_count,
                    "count_match": count_match,
                    "source_checksum": stat["source_checksum"],
                    "target_checksum": stat["target_checksum"],
                    "checksum_match": checksum_match,
                    "problems": stat_problems,
                }
            )

        if self.dry_run:
            # A dry run proves extraction and planning only; it can never report PASSED.
            reconciliation["audit_lock_present"] = None
            reconciliation["audit_chain_valid"] = None
            reconciliation["overall_status"] = "FAILED" if problems else "DRY_RUN"
            return reconciliation

        reconciliation["orphan_violations"] = self._orphan_violations(mysql_conn)
        reconciliation["audit_lock_present"] = self._audit_lock_present(mysql_conn)
        reconciliation["audit_chain_valid"] = self._verify_mysql_audit_chain(mysql_conn)

        problems += [f"{v['foreign_key']}: {v['orphans']} orphan row(s)" for v in reconciliation["orphan_violations"]]
        if not reconciliation["audit_lock_present"]:
            problems.append("audit_lock: mutex row id=1 missing; audit appends cannot serialise")
        if not reconciliation["audit_chain_valid"]:
            problems.append("audit_log: hash chain verification failed")

        if not problems and reconciliation["row_count_mismatches"] == 0 and reconciliation["checksum_mismatches"] == 0:
            reconciliation["overall_status"] = "PASSED"

        return reconciliation

    def _orphan_violations(self, mysql_conn: Any) -> list[dict[str, Any]]:
        """FOREIGN_KEY_CHECKS is off during load, so every foreign key is re-checked explicitly afterwards."""
        with mysql_conn.cursor() as cur:
            cur.execute(
                "SELECT CONSTRAINT_NAME, TABLE_NAME, COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME "
                "FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE "
                "WHERE TABLE_SCHEMA = DATABASE() AND REFERENCED_TABLE_NAME IS NOT NULL "
                "ORDER BY TABLE_NAME, CONSTRAINT_NAME, ORDINAL_POSITION"
            )
            fk_rows = cur.fetchall()
            violations = []
            for name, sql in build_orphan_queries(fk_rows):
                cur.execute(sql)
                n = cur.fetchone()[0]
                if n:
                    violations.append({"foreign_key": name, "orphans": n})
        return violations

    def _audit_lock_present(self, mysql_conn: Any) -> bool:
        with mysql_conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM audit_lock WHERE id = 1")
            return cur.fetchone()[0] == 1

    def _verify_mysql_audit_chain(self, mysql_conn: Any) -> bool:
        """Validate SHA-256 cryptographic hash chain in MySQL audit_log."""
        try:
            with mysql_conn.cursor() as cur:
                cur.execute(
                    "SELECT seq, org_id, actor, action, target, meta, ts, prev_hash, hash FROM audit_log ORDER BY seq"
                )
                rows = cur.fetchall()

            if not rows:
                log.info("Audit log is empty; chain is trivially valid.")
                return True

            records = []
            for r in rows:
                meta = r[5]
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except Exception:
                        meta = {}
                records.append(
                    AuditRecord(
                        seq=r[0],
                        org_id=str(r[1]),
                        actor=r[2],
                        action=r[3],
                        target=r[4],
                        meta=meta or {},
                        ts=r[6],
                        prev_hash=r[7].strip(),
                        hash=r[8].strip(),
                    )
                )

            result = verify_records(records, GENESIS_HASH, 1)
            if not result.ok:
                log.error("Audit chain broken at seq %s: %s", result.first_broken_seq, result.reason)
                return False

            log.info("Audit chain successfully verified across %d records.", result.checked)
            return True
        except Exception as e:
            log.error("Error verifying audit chain: %s", e)
            return False

    def execute(self) -> dict[str, Any]:
        """Execute the full end-to-end migration pipeline."""
        log.info("Starting PostgreSQL to MySQL migration (DryRun=%s)...", self.dry_run)
        start_time = time.time()
        validate_migration_registry()

        import psycopg
        import pymysql

        pg_conn = psycopg.connect(**self.pg_config)
        # Read every table from one consistent, read-only snapshot, with timestamptz values in UTC.
        pg_conn.read_only = True
        pg_conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        mysql_conn = pymysql.connect(**{"charset": "utf8mb4", **self.mysql_config})

        table_stats: list[dict[str, Any]] = []

        try:
            with pg_conn.cursor() as cur:
                cur.execute("SET TIME ZONE 'UTC'")

            problems = self.preflight(pg_conn, mysql_conn)
            if problems:
                raise MigrationError(
                    "Preflight failed; nothing was written to the target:\n  - " + "\n  - ".join(problems)
                )

            # Foreign key checks are off during batch ingestion; run_reconciliation re-checks every FK.
            # UNIQUE_CHECKS stays on so duplicate keys are rejected rather than silently admitted.
            if not self.dry_run:
                with mysql_conn.cursor() as cur:
                    cur.execute("SET FOREIGN_KEY_CHECKS = 0")
                mysql_conn.commit()

            try:
                for tbl in TABLE_MIGRATION_ORDER:
                    stat = self.migrate_table(pg_conn, mysql_conn, tbl)
                    table_stats.append(stat)
            finally:
                # ALWAYS restore foreign key checks
                if not self.dry_run:
                    try:
                        with mysql_conn.cursor() as cur:
                            cur.execute("SET FOREIGN_KEY_CHECKS = 1")
                        mysql_conn.commit()
                    except Exception as e:
                        log.error("Failed to restore foreign key checks: %s", e)

            reconciliation = self.run_reconciliation(mysql_conn, table_stats)
        finally:
            pg_conn.close()
            mysql_conn.close()

        elapsed = time.time() - start_time
        reconciliation["elapsed_seconds"] = round(elapsed, 2)
        log.info(
            "Migration completed in %.2fs. Overall Status: %s",
            elapsed,
            reconciliation["overall_status"],
        )
        return reconciliation


PG_PASSWORD_ENVS = ("MIGRATION_PG_PASSWORD", "POSTGRES_PASSWORD")
MYSQL_PASSWORD_ENVS = ("MIGRATION_MYSQL_PASSWORD", "MYSQL_TEST_PASSWORD")


class _RejectSecretArgument(argparse.Action):
    """Passwords on the command line end up in shell history and process listings; refuse them."""

    def __call__(self, parser: argparse.ArgumentParser, namespace: Any, values: Any, option_string: Any = None) -> None:
        env_names = PG_PASSWORD_ENVS if "pg" in str(option_string) else MYSQL_PASSWORD_ENVS
        parser.error(
            f"{option_string} is not accepted (it would leak into shell history); set {env_names[0]}, "
            f"{env_names[0]}_FILE or pass {option_string}-file"
        )


def build_parser(env: Any = None) -> argparse.ArgumentParser:
    env = os.environ if env is None else env
    parser = argparse.ArgumentParser(description="Cortex PostgreSQL to MySQL ETL Tool")
    parser.add_argument("--dry-run", action="store_true", help="Perform extraction without modifying target")
    parser.add_argument("--batch-size", type=int, default=1000, help="Batch extraction/insertion size")
    parser.add_argument("--report", type=str, default="", help="Path to write JSON reconciliation report")
    parser.add_argument("--pg-port", type=int, default=int(env.get("PG_PORT", 55432)))
    parser.add_argument("--pg-host", type=str, default=env.get("PG_HOST", "127.0.0.1"))
    parser.add_argument("--pg-db", type=str, default=env.get("PG_DATABASE", "cortex"))
    parser.add_argument("--pg-user", type=str, default=env.get("PG_USER", "cortex"))
    parser.add_argument("--pg-password", action=_RejectSecretArgument, help=argparse.SUPPRESS)
    parser.add_argument("--pg-password-file", default=None, help="file holding the source password")
    parser.add_argument(
        "--pg-sslmode",
        default=env.get("PG_SSLMODE"),
        choices=secure_connect.PG_SSL_MODES,
        help="default: libpq default on loopback, verify-full otherwise",
    )
    parser.add_argument(
        "--pg-sslrootcert",
        default=env.get("PG_SSLROOTCERT"),
        help="CA bundle for verify-ca/verify-full ('system' = OS trust store)",
    )
    parser.add_argument("--mysql-port", type=int, default=int(env.get("MYSQL_TEST_PORT", 53306)))
    parser.add_argument("--mysql-host", type=str, default=env.get("MYSQL_TEST_HOST", "127.0.0.1"))
    parser.add_argument("--mysql-db", type=str, default=env.get("MYSQL_TEST_DATABASE", "cortex_integration"))
    parser.add_argument("--mysql-user", type=str, default=env.get("MYSQL_TEST_USER", "cortex"))
    parser.add_argument("--mysql-password", action=_RejectSecretArgument, help=argparse.SUPPRESS)
    parser.add_argument("--mysql-password-file", default=None, help="file holding the target password")
    parser.add_argument(
        "--mysql-ssl-mode",
        default=env.get("MYSQL_SSL_MODE"),
        type=str.upper,
        choices=secure_connect.MYSQL_SSL_MODES,
        help="default: DISABLED on loopback, VERIFY_IDENTITY otherwise",
    )
    parser.add_argument(
        "--mysql-ssl-ca", default=env.get("MYSQL_SSL_CA"), help="CA bundle (default: system trust store)"
    )
    parser.add_argument("--mysql-ssl-cert", default=env.get("MYSQL_SSL_CERT"), help="client certificate (mutual TLS)")
    parser.add_argument("--mysql-ssl-key", default=env.get("MYSQL_SSL_KEY"), help="client key (mutual TLS)")
    return parser


def build_connection_configs(args: argparse.Namespace, env: Any = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """Source and target connection settings. Dev passwords apply to loopback hosts only; remote hosts need TLS."""
    pg_config: dict[str, Any] = {
        "host": args.pg_host,
        "port": args.pg_port,
        "dbname": args.pg_db,
        "user": args.pg_user,
        "password": secure_connect.resolve_password(
            PG_PASSWORD_ENVS, args.pg_host, password_file=args.pg_password_file, local_default=None, env=env
        ),
        **secure_connect.pg_ssl_options(args.pg_host, args.pg_sslmode, sslrootcert=args.pg_sslrootcert, env=env),
    }
    mysql_config: dict[str, Any] = {
        "host": args.mysql_host,
        "port": args.mysql_port,
        "database": args.mysql_db,
        "user": args.mysql_user,
        "password": secure_connect.resolve_password(
            MYSQL_PASSWORD_ENVS,
            args.mysql_host,
            password_file=args.mysql_password_file,
            local_default=None,
            env=env,
        ),
    }
    ctx = secure_connect.mysql_ssl_context(
        args.mysql_host,
        args.mysql_ssl_mode,
        ca=args.mysql_ssl_ca,
        cert=args.mysql_ssl_cert,
        key=args.mysql_ssl_key,
        env=env,
    )
    if ctx is not None:
        mysql_config["ssl"] = ctx
    return pg_config, mysql_config


def main() -> None:
    args = build_parser().parse_args()
    try:
        pg_config, mysql_config = build_connection_configs(args)
    except (ValueError, OSError) as e:
        log.error("%s", e)
        sys.exit(2)
    log.info(
        "Source %s:%s/%s (%s) -> target %s:%s/%s (%s)",
        args.pg_host,
        args.pg_port,
        args.pg_db,
        secure_connect.describe_tls(pg_config),
        args.mysql_host,
        args.mysql_port,
        args.mysql_db,
        secure_connect.describe_tls(mysql_config),
    )

    migrator = PostgresToMySQLMigrator(pg_config, mysql_config, batch_size=args.batch_size, dry_run=args.dry_run)
    try:
        result = migrator.execute()
    except MigrationError as e:
        log.error("%s", e)
        result = {"timestamp": datetime.now().isoformat(), "overall_status": "FAILED", "problems": [str(e)]}

    if args.report:
        report_path = Path(args.report)
        report_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        log.info("Wrote reconciliation report to %s", report_path)

    expected = "DRY_RUN" if args.dry_run else "PASSED"
    if result["overall_status"] != expected:
        sys.exit(1)


if __name__ == "__main__":
    main()
