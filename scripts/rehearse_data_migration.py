"""Capital Cortex — Phase 14: Data Migration Rehearsal and Reconciliation Script.

Executes a live end-to-end rehearsal from an isolated PostgreSQL 16 source into an
isolated MySQL 8.4 target.

Key features:
1. Seeds representative synthetic data across major domain tables in PostgreSQL.
2. Migrates all tables to MySQL via PostgresToMySQLMigrator (real data transfer).
3. Validates row counts, SHA-256 canonical row checksums, and audit hash chains.
4. Validates packed IEEE-754 vector embedding precision (1024-dim).
5. Validates recursive CTE relational graph traversal on MySQL.
6. Exercises idempotency and batch processing.
"""

from __future__ import annotations

import decimal
import hashlib
import json
import logging
import os
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import psycopg
import pymysql

from platform_core.audit.chain import GENESIS_HASH, AuditRecord, compute_hash
from platform_core.db.vector import EMBEDDING_DIM, from_blob
from scripts.migrate_pg_to_mysql import PostgresToMySQLMigrator

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
log = logging.getLogger("phase14_rehearsal")

TENANT_ID = "00000000-0000-0000-0000-000000000001"
SRC_REF = json.dumps({"kind": "synthetic_seed", "phase": "phase14_rehearsal"})


def _secret(*names: str) -> str:
    """First non-empty environment variable among names (or NAME_FILE); refuse to run without one."""
    for n in names:
        if os.environ.get(n):
            return os.environ[n]
        if os.environ.get(f"{n}_FILE"):
            return Path(os.environ[f"{n}_FILE"]).read_text(encoding="utf-8").strip()
    raise SystemExit(f"set one of {', '.join(names)} (or <NAME>_FILE) in the environment")


def seed_synthetic_postgres(pg_conn: psycopg.Connection) -> dict[str, int]:
    """Seed synthetic relational dataset into PostgreSQL source."""
    log.info("Seeding synthetic dataset into isolated PostgreSQL database...")
    counts: dict[str, int] = {}

    with pg_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM signal")
        if cur.fetchone()[0] > 0:
            log.info("Synthetic dataset already present in PostgreSQL source; skipping duplicate seeding.")
            for tbl in [
                "tenant",
                "source",
                "source_run",
                "signal",
                "organization",
                "entity",
                "relationship_edge",
                "opportunity",
                "embedding",
                "contact",
                "meeting",
                "interaction",
                "audit_log",
            ]:
                cur.execute(f'SELECT COUNT(*) FROM "{tbl}"')
                counts[tbl] = cur.fetchone()[0]
            return counts

    batch_run_suffix = uuid.uuid4().hex[:8]

    with pg_conn.cursor() as cur:
        # 1. Tenant
        cur.execute(
            "INSERT INTO tenant (id, name) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING",
            (TENANT_ID, "Phase 14 Rehearsal Org"),
        )
        counts["tenant"] = 1

        # 2. Source & SourceRun & Signal
        src_id = str(uuid.uuid4())
        adapter_key = f"rehearsal_adapter_{batch_run_suffix}"
        cur.execute(
            "INSERT INTO source (id, org_id, name, kind, adapter_key, config) VALUES (%s, %s, %s, %s, %s, %s)",
            (src_id, TENANT_ID, "Rehearsal Feed", "api", adapter_key, json.dumps({"url": "https://rehearsal.local"})),
        )
        counts["source"] = 1

        run_id = str(uuid.uuid4())
        cur.execute(
            'INSERT INTO source_run (id, source_id, "trigger", status) VALUES (%s, %s, %s, %s)',
            (run_id, src_id, "manual", "succeeded"),
        )
        counts["source_run"] = 1

        signals = []
        for i in range(5):
            sig_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO signal (id, org_id, source_id, external_id, content_hash, raw, normalized, source_ref) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    sig_id,
                    TENANT_ID,
                    src_id,
                    f"ext_{batch_run_suffix}_{i}",
                    hashlib.sha256(f"sig_{batch_run_suffix}_{i}".encode()).hexdigest(),
                    json.dumps({"raw_data": i}),
                    json.dumps({"title": f"Signal {i}"}),
                    SRC_REF,
                ),
            )
            signals.append(sig_id)
        counts["signal"] = len(signals)

        # 3. Organizations
        org_ids = []
        for i in range(5):
            oid = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO organization (id, org_id, name, kind, source_ref) VALUES (%s, %s, %s, %s, %s)",
                (oid, TENANT_ID, f"Synthetic Enterprise {i}", "counterparty", SRC_REF),
            )
            org_ids.append(oid)
        counts["organization"] = len(org_ids)

        # 4. Entities & Relationship Edges (Graph)
        entity_ids = []
        for i in range(5):
            eid = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO entity (id, org_id, entity_type, ref_table, ref_id, label, source_ref) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (eid, TENANT_ID, "organization", "organization", org_ids[i], f"Graph Node {i}", SRC_REF),
            )
            entity_ids.append(eid)
        counts["entity"] = len(entity_ids)

        edge_types = ["OFFERS", "PARTNER_OF", "INVESTS_IN", "ACQUIRED"]
        edges_count = 0
        for i in range(4):
            cur.execute(
                "INSERT INTO relationship_edge (id, org_id, from_entity, to_entity, type, weight, source_ref) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    str(uuid.uuid4()),
                    TENANT_ID,
                    entity_ids[i],
                    entity_ids[i + 1],
                    edge_types[i],
                    0.8 + 0.05 * i,
                    SRC_REF,
                ),
            )
            edges_count += 1
        counts["relationship_edge"] = edges_count

        # 5. Opportunities
        opp_ids = []
        for i in range(5):
            opp_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO opportunity (id, org_id, title, class, pipeline_stage, amount_min, amount_max, sectors, source_ref, score, score_band, completeness, factors) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    opp_id,
                    TENANT_ID,
                    f"Rehearsal Grant Program {i}",
                    "grant",
                    "discovered",
                    decimal.Decimal(f"{100000 + i * 25000}.00"),
                    decimal.Decimal(f"{200000 + i * 25000}.00"),
                    ["energy", "sustainability"],
                    SRC_REF,
                    0.85 + 0.02 * i,
                    "high",
                    0.95,
                    json.dumps({"team": 0.9, "market": 0.8}),
                ),
            )
            opp_ids.append(opp_id)
        counts["opportunity"] = len(opp_ids)

        # 6. Embeddings (1024-dim IEEE-754 float vectors in pgvector format)
        for i in range(5):
            floats = [float(0.01 * ((j + i) % 50)) for j in range(EMBEDDING_DIM)]
            str_vec = "[" + ", ".join(f"{x:.4f}" for x in floats) + "]"
            emb_id = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO embedding (id, org_id, entity_type, entity_id, model, dim, text_hash, vector) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    emb_id,
                    TENANT_ID,
                    "opportunity",
                    opp_ids[i],
                    "text-embedding-3-small",
                    EMBEDDING_DIM,
                    hashlib.sha256(f"emb_{i}".encode()).hexdigest(),
                    str_vec,
                ),
            )
        counts["embedding"] = 5

        # 7. Contacts, Meetings, Interactions
        for i in range(5):
            cid = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO contact (id, org_id, name, emails, consent_basis, organization_id, source_ref) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (
                    cid,
                    TENANT_ID,
                    f"Contact {i}",
                    [f"user{i}@rehearsal.test"],
                    "legitimate_interest",
                    org_ids[i],
                    SRC_REF,
                ),
            )
            mid = str(uuid.uuid4())
            cur.execute(
                "INSERT INTO meeting (id, org_id, summary, occurred_at, source_ref) VALUES (%s, %s, %s, %s, %s)",
                (mid, TENANT_ID, f"Strategy Session {i}", datetime.now(UTC), SRC_REF),
            )
            cur.execute(
                "INSERT INTO interaction (id, org_id, contact_id, kind, summary, occurred_at, weight, recorded_by, source_ref) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    str(uuid.uuid4()),
                    TENANT_ID,
                    cid,
                    "email_sent",
                    f"Quarterly update {i}",
                    datetime.now(UTC),
                    decimal.Decimal("1.0"),
                    "system",
                    SRC_REF,
                ),
            )
        counts["contact"] = 5
        counts["meeting"] = 5
        counts["interaction"] = 5

        # 8. Audit Chain
        cur.execute("SELECT COUNT(*) FROM audit_log")
        existing_audit_count = cur.fetchone()[0]
        if existing_audit_count > 0:
            counts["audit_log"] = existing_audit_count
        else:
            prev_hash = GENESIS_HASH
            for seq in range(1, 6):
                now = datetime.now(UTC)
                meta = {"rehearsal_batch": 1, "seq": seq}
                rec = AuditRecord(
                    seq=seq,
                    org_id=TENANT_ID,
                    actor="rehearsal_seeder",
                    action=f"audit.event.{seq}",
                    target=f"opportunity:{opp_ids[seq - 1]}",
                    meta=meta,
                    ts=now,
                    prev_hash=prev_hash,
                )
                curr_hash = compute_hash(prev_hash, rec.payload())
                rec.hash = curr_hash

                cur.execute(
                    "INSERT INTO audit_log (seq, org_id, actor, action, target, meta, ts, prev_hash, hash) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                    (
                        rec.seq,
                        rec.org_id,
                        rec.actor,
                        rec.action,
                        rec.target,
                        json.dumps(rec.meta),
                        rec.ts,
                        rec.prev_hash,
                        rec.hash,
                    ),
                )
                prev_hash = curr_hash
            counts["audit_log"] = 5

    pg_conn.commit()
    log.info("Synthetic dataset seeded successfully: %s", counts)
    return counts


def run_rehearsal():
    """Execute live data migration rehearsal and full reconciliation."""
    print("=" * 75)
    print("Capital Cortex — Phase 14: Data Migration Rehearsal & Reconciliation")
    print("=" * 75)

    # Credentials from the environment (same names as scripts/migrate_pg_to_mysql.py); none are committed.
    pg_config = {
        "host": "127.0.0.1",
        "port": 55433,
        "dbname": "cortex",
        "user": "cortex",
        "password": _secret("MIGRATION_PG_PASSWORD", "POSTGRES_PASSWORD"),
    }

    mysql_config = {
        "host": "127.0.0.1",
        "port": int(os.environ.get("MYSQL_TEST_PORT", "53306")),
        "database": "cortex_rehearsal",
        "user": os.environ.get("MYSQL_TEST_USER", "cortex"),
        "password": _secret("MIGRATION_MYSQL_PASSWORD", "MYSQL_TEST_PASSWORD"),
    }

    # 1. Connect and Seed PostgreSQL
    pg_conn = psycopg.connect(**pg_config)
    seed_synthetic_postgres(pg_conn)
    pg_conn.close()

    # 2. Reset target MySQL database for clean rehearsal run
    log.info("Resetting rehearsal target MySQL tables in 'cortex_rehearsal'...")
    from scripts.migrate_pg_to_mysql import TABLE_MIGRATION_ORDER

    with pymysql.connect(**mysql_config) as reset_conn:
        with reset_conn.cursor() as rcur:
            rcur.execute("SET FOREIGN_KEY_CHECKS = 0")
            for tbl in TABLE_MIGRATION_ORDER:
                clean = tbl.replace("`", "")
                rcur.execute(f"TRUNCATE TABLE `{clean}`")
            # audit_lock is target-only and never truncated; restore its mutex row in case an earlier run removed it
            rcur.execute("INSERT IGNORE INTO audit_lock (id, dummy) VALUES (1, 1)")
            rcur.execute("SET FOREIGN_KEY_CHECKS = 1")
        reset_conn.commit()

    # 3. Execute ETL Migration into MySQL
    log.info("Initiating PostgresToMySQLMigrator to target MySQL database 'cortex_rehearsal'...")
    migrator = PostgresToMySQLMigrator(
        pg_config=pg_config,
        mysql_config=mysql_config,
        batch_size=500,
        dry_run=False,
    )
    result = migrator.execute()

    # 4. Detailed Verification on Target MySQL
    my_conn = pymysql.connect(**mysql_config)

    print("\n--- TABLE-BY-TABLE RECONCILIATION SUMMARY ---")
    print(f"{'Table':<25} | {'Source Rows':<12} | {'Target Rows':<12} | {'Counts Match':<14} | {'Checksum Match':<15}")
    print("-" * 88)
    empty_tables = []
    for res in result["table_results"]:
        if res["source_rows"] == 0:
            empty_tables.append(res["table"])
        print(
            f"{res['table']:<25} | {res['source_rows']:<12} | {res['target_rows']!s:<12} | "
            f"{res['count_match']!s:<14} | {res['checksum_match']!s:<15}"
        )
    # Synthetic seed data covers only some tables; say so rather than letting empty tables read as verified.
    print(
        f"\n[WARN] {len(empty_tables)} of {len(result['table_results'])} tables had no source rows "
        f"and were not exercised: {', '.join(empty_tables)}"
    )
    for problem in result.get("problems", []):
        print(f"[FAIL] {problem}")

    # 4. Vector Verification
    log.info("Verifying packed IEEE-754 vector embedding storage and retrieval on MySQL...")
    with my_conn.cursor() as cur:
        cur.execute("SELECT id, vector FROM embedding LIMIT 1")
        row = cur.fetchone()
        assert row is not None, "No embedding record found in MySQL"
        blob = row[1]
        assert len(blob) == EMBEDDING_DIM * 4, f"Expected {EMBEDDING_DIM * 4} bytes, got {len(blob)}"
        unpacked = from_blob(blob)
        assert len(unpacked) == EMBEDDING_DIM
        # Verify first 10 values match expected floating point seed
        for idx in range(10):
            expected = float(0.01 * (idx % 50))
            assert abs(unpacked[idx] - expected) < 1e-4, f"Mismatch at {idx}: {unpacked[idx]} vs {expected}"
    print("[OK] Vector Integrity: Unpacked 1024-dim float32 vector, verified precision < 1e-4")

    # 5. Graph Traversal Verification via Recursive CTE
    log.info("Verifying graph traversal on migrated MySQL relationship_edge table...")
    with my_conn.cursor() as cur:
        # Find root node of the seeded chain (the from_entity that does not appear in to_entity)
        cur.execute("""
            SELECT from_entity FROM relationship_edge
            WHERE from_entity NOT IN (SELECT to_entity FROM relationship_edge)
            LIMIT 1
        """)
        root_node = cur.fetchone()[0]

        cur.execute(
            """
            WITH RECURSIVE graph_cte AS (
                SELECT from_entity, to_entity, type, 1 AS depth
                FROM relationship_edge
                WHERE from_entity = %s
                UNION ALL
                SELECT e.from_entity, e.to_entity, e.type, g.depth + 1
                FROM relationship_edge e
                JOIN graph_cte g ON e.from_entity = g.to_entity
                WHERE g.depth < 10
            )
            SELECT COUNT(*), MAX(depth) FROM graph_cte
        """,
            (root_node,),
        )
        g_count, g_max_depth = cur.fetchone()
        assert g_count >= 4, f"Expected at least 4 edges traversed, got {g_count}"
        assert g_max_depth >= 4, f"Expected graph depth >= 4, got {g_max_depth}"
    print(f"[OK] Graph Traversal: Recursive CTE traversed {g_count} edges reaching depth {g_max_depth}")

    # 6. Audit Chain Integrity Verification
    audit_valid = result["audit_chain_valid"]
    assert audit_valid is True, "Audit chain verification failed on MySQL"
    print("[OK] Audit Chain Integrity: Cryptographic hash chain verified valid across all records")

    # 7. Write Report File
    content = json.dumps(result, indent=2)
    report_file_scripts = ROOT / "scripts" / "rehearsal_reconciliation_report.json"
    report_file_root = ROOT / "rehearsal_reconciliation_report.json"
    report_file_scripts.write_text(content, encoding="utf-8")
    report_file_root.write_text(content, encoding="utf-8")
    print(f"[OK] Reconciliation Report saved to {report_file_scripts} and {report_file_root}")

    my_conn.close()

    print("\n" + "=" * 75)
    print(f"REHEARSAL COMPLETED: Overall Status = {result['overall_status']}")
    print(f"Elapsed Time: {result['elapsed_seconds']}s | Tables Evaluated: {result['total_tables']}")
    print("=" * 75)
    return result


if __name__ == "__main__":
    res = run_rehearsal()
    if res["overall_status"] != "PASSED":
        sys.exit(1)
