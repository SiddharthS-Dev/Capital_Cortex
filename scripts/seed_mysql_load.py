"""MySQL 8.4 Bulk Load Generator for Scale & SLO Benchmarking (Phase 11).

Generates synthetic seed datasets (up to 1,000,000 entities and 1,000,000 edges)
into a disposable MySQL database using high-throughput multi-row bounded batches.

Features:
- Deterministic pseudo-random generation with fixed seeds
- Preserves 100% referential integrity and schema constraints
- Vector generation with 1024-dim packed IEEE-754 binary BLOBs (VARBINARY(4096))
- Relational knowledge graph generation (entity and relationship_edge)
- Strict safety guard against production databases
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pymysql

from platform_core import embeddings
from platform_core.audit.chain import GENESIS_HASH, AuditRecord, compute_hash
from platform_core.db.vector import EMBEDDING_DIM, to_blob

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] [%(levelname)s] %(message)s")
log = logging.getLogger("mysql_load_seed")

ORG_ID = "00000000-0000-0000-0000-000000000001"
SRC_REF = json.dumps({"kind": "synthetic_seed", "generator": "scripts/seed_mysql_load.py"})

SYLLABLES = [
    "Vel",
    "Quor",
    "Ard",
    "Lum",
    "Pyr",
    "Ost",
    "Kel",
    "Mar",
    "Zen",
    "Tor",
    "Bri",
    "Cal",
    "Dra",
    "Eno",
    "Fal",
    "Gri",
    "Hal",
    "Ivo",
    "Jor",
    "Kav",
    "Nor",
    "Oph",
    "Sel",
    "Tav",
    "Ul",
    "Vy",
    "Wren",
    "Xan",
    "Yor",
    "Zyl",
]
SUFFIXES = [
    "taris",
    "vane",
    "entis",
    "ora",
    "exa",
    "ine",
    "ova",
    "ium",
    "ara",
    "eth",
    "anth",
    "ioc",
    "ument",
    "yss",
]
PREFIXES = [
    "Climate",
    "Frontier",
    "Horizon",
    "Catalyst",
    "Meridian",
    "Summit",
    "Harbor",
    "Beacon",
    "Keystone",
    "Aurora",
]
ORG_TYPES = [
    "Capital",
    "Ventures",
    "Partners",
    "Foundation",
    "Agency",
    "Labs",
    "Holdings",
    "Institute",
]
COUNTRIES = [
    "US",
    "GB",
    "DE",
    "FR",
    "NL",
    "SE",
    "IE",
    "ES",
    "IT",
    "PL",
    "IN",
    "SG",
    "JP",
    "KR",
    "AU",
    "CA",
    "BR",
    "MX",
    "ZA",
    "KE",
    "NG",
    "AE",
    "IL",
    "CH",
    "DK",
]
SECTORS = [
    "clean energy storage",
    "machine learning for logistics",
    "digital health diagnostics",
    "advanced manufacturing robotics",
    "regenerative agriculture",
    "cybersecurity for SMEs",
    "water treatment technology",
    "fintech for payments",
    "edtech and workforce training",
    "electric mobility",
]
CAPITAL_CLASSES = [
    "venture_equity",
    "private_equity",
    "strategic_corporate",
    "grant",
    "government_program",
    "university_program",
    "foundation_esg",
    "debt_facility",
    "convertible",
    "equipment_finance",
    "revenue_based_financing",
]
PIPELINE_STAGES = [
    "discovered",
    "qualified",
    "engaged",
    "submitted",
    "diligence",
    "term_sheet",
    "committed",
    "closed",
    "lost",
]


def gen_uuid(prefix: str, n: int) -> str:
    """Generate deterministic UUID from prefix and integer id."""
    raw = hashlib.md5(f"{prefix}:{n}".encode(), usedforsecurity=False).hexdigest()
    return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"


def gen_org_name(n: int) -> str:
    syl = SYLLABLES[n % len(SYLLABLES)] + SUFFIXES[(n // len(SYLLABLES)) % len(SUFFIXES)]
    pref = PREFIXES[(n // 420) % len(PREFIXES)]
    typ = ORG_TYPES[(n // 4200) % len(ORG_TYPES)]
    return f"{syl} {pref} {typ} {n}"


class MySQLLoadGenerator:
    """High-throughput generator for MySQL 8.4 load databases."""

    def __init__(
        self,
        db_config: dict[str, Any],
        scale: float = 1.0,
        batch_size: int = 5000,
    ):
        self.db_config = db_config
        self.scale = max(0.001, scale)
        self.batch_size = batch_size
        self._verify_safety()

        # Scaled entity counts
        self.n_org = max(10, int(150000 * self.scale))
        self.n_inv = max(5, int(30000 * self.scale))
        self.n_fund = max(5, int(20000 * self.scale))
        self.n_gp = max(5, int(10000 * self.scale))
        self.n_opp = max(10, int(200000 * self.scale))
        self.n_sig = max(10, int(390000 * self.scale))
        self.n_con = max(10, int(200000 * self.scale))
        self.n_audit = max(10, int(50000 * self.scale))

    def _verify_safety(self) -> None:
        port = int(self.db_config.get("port", 3306))
        db = self.db_config.get("database", "")
        if port == 3306 and not os.environ.get("ALLOW_PROD_PORT_LOAD"):
            raise RuntimeError(
                f"Safety Abort: Target port {port} matches production default. Set MYSQL_TEST_PORT=53306."
            )
        if "prod" in db.lower():
            raise RuntimeError(f"Safety Abort: Target database '{db}' contains 'prod'. Aborting.")

    def run(self) -> dict[str, int]:
        log.info(
            "Starting MySQL bulk load generator: Scale=%.4f (Organizations=%d, Opportunities=%d)",
            self.scale,
            self.n_org,
            self.n_opp,
        )
        conn = pymysql.connect(**self.db_config)
        t0 = time.time()
        counts: dict[str, int] = {}

        try:
            with conn.cursor() as cur:
                cur.execute("SET FOREIGN_KEY_CHECKS = 0")
                cur.execute("SET UNIQUE_CHECKS = 0")
            conn.commit()

            counts["tenant"] = self._seed_tenant(conn)
            counts["source"] = self._seed_sources(conn)
            counts["organization"] = self._seed_organizations(conn)
            counts["opportunity"] = self._seed_opportunities(conn)
            counts["embedding"] = self._seed_embeddings(conn)
            counts["entity"] = self._seed_graph_entities(conn)
            counts["relationship_edge"] = self._seed_graph_edges(conn)
            counts["audit_log"] = self._seed_audit(conn)

        finally:
            with conn.cursor() as cur:
                cur.execute("SET FOREIGN_KEY_CHECKS = 1")
                cur.execute("SET UNIQUE_CHECKS = 1")
            conn.commit()
            conn.close()

        elapsed = time.time() - t0
        log.info("Bulk load generation completed in %.2fs. Summary: %s", elapsed, counts)
        return counts

    def _execute_chunks(self, conn: Any, sql: str, rows: list[tuple]) -> int:
        total = 0
        with conn.cursor() as cur:
            for i in range(0, len(rows), self.batch_size):
                chunk = rows[i : i + self.batch_size]
                cur.executemany(sql, chunk)
                conn.commit()
                total += len(chunk)
        return total

    def _seed_tenant(self, conn: Any) -> int:
        sql = "INSERT INTO tenant (id, name) VALUES (%s, %s) ON DUPLICATE KEY UPDATE name=VALUES(name)"
        with conn.cursor() as cur:
            cur.execute(sql, (ORG_ID, "Inspironics Load Test"))
        conn.commit()
        return 1

    def _seed_sources(self, conn: Any) -> int:
        sql = (
            "INSERT INTO source (id, org_id, name, kind, adapter_key, adapter, terms_note, enabled, health, is_demo) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE name=VALUES(name)"
        )
        sid = gen_uuid("source", 1)
        row = (sid, ORG_ID, "Synthetic load seed", "internal", "load_seed", "manual", "R3 synthetic data", 1, "ok", 1)
        with conn.cursor() as cur:
            cur.execute(sql, row)
        conn.commit()
        return 1

    def _seed_organizations(self, conn: Any) -> int:
        log.info("Generating %d organizations...", self.n_org)
        sql = (
            "INSERT INTO organization (id, org_id, name, normalized_name, kind, country, sectors, profile, source_ref, is_demo) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE name=VALUES(name)"
        )
        rows = []
        for g in range(1, self.n_org + 1):
            oid = gen_uuid("org", g)
            name = "Loadtest Self Organisation" if g == 1 else gen_org_name(g)
            norm = name.lower()
            kind = "self" if g == 1 else ("agency" if g % 10 == 0 else "counterparty")
            country = COUNTRIES[g % len(COUNTRIES)]
            sec = json.dumps([SECTORS[g % len(SECTORS)]])
            prof = json.dumps({"origin": "load_test", "tier": g % 5})
            rows.append((oid, ORG_ID, name, norm, kind, country, sec, prof, SRC_REF, 1))
        return self._execute_chunks(conn, sql, rows)

    def _seed_opportunities(self, conn: Any) -> int:
        log.info("Generating %d opportunities...", self.n_opp)
        sql = (
            "INSERT INTO opportunity (id, org_id, title, description, class, status, pipeline_stage, score, "
            "score_band, factors, completeness, counterparty_id, amount_min, amount_max, currency, source_ref, is_demo) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON DUPLICATE KEY UPDATE title=VALUES(title)"
        )
        rows = []
        factors_json = json.dumps({"fit": 0.82, "urgency": 0.75, "risk": 0.20})
        for g in range(1, self.n_opp + 1):
            opp_id = gen_uuid("opp", g)
            cp_idx = 1 if g == 1 else (2 + (g % (self.n_org - 1)))
            cp_id = gen_uuid("org", cp_idx)
            cls = CAPITAL_CLASSES[g % len(CAPITAL_CLASSES)]
            stage = PIPELINE_STAGES[g % len(PIPELINE_STAGES)]
            status = (
                "active" if stage in ("qualified", "engaged", "diligence", "term_sheet", "committed") else "watchlist"
            )
            score = round(0.40 + (g % 55) * 0.01, 3)
            band = "high" if score >= 0.75 else "watchlist"
            completeness = 0.85
            title, desc = self._opp_text(g)
            amt_min = 50000 + (g % 100) * 10000
            amt_max = amt_min * 2
            rows.append(
                (
                    opp_id,
                    ORG_ID,
                    title,
                    desc,
                    cls,
                    status,
                    stage,
                    score,
                    band,
                    factors_json,
                    completeness,
                    cp_id,
                    amt_min,
                    amt_max,
                    "USD",
                    SRC_REF,
                    1,
                )
            )
        return self._execute_chunks(conn, sql, rows)

    @staticmethod
    def _opp_text(g: int) -> tuple[str, str]:
        """Deterministic title/description for opportunity g (shared by the rows and their embeddings)."""
        cls = CAPITAL_CLASSES[g % len(CAPITAL_CLASSES)]
        title = f"{cls.replace('_', ' ').title()} Opportunity {g}"
        desc = f"Synthetic {cls} opportunity targeting {SECTORS[g % len(SECTORS)]} in region."
        return title, desc

    def _seed_embeddings(self, conn: Any) -> int:
        """One real embedding per opportunity, from the application's own embedder and model name, so the
        app's vector search (which ranks everything in the tenant) sees realistic, distinct vectors."""
        log.info("Generating %d opportunity embeddings with %s...", self.n_opp, embeddings.MODEL)
        sql = (
            "INSERT INTO embedding (id, entity_id, entity_type, model, dim, text_hash, vector, org_id) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE text_hash=VALUES(text_hash)"
        )
        written = 0
        rows = []
        for g in range(1, self.n_opp + 1):
            text = " ".join(self._opp_text(g))
            rows.append(
                (
                    gen_uuid("emb", g),
                    gen_uuid("opp", g),
                    "opportunity",
                    embeddings.MODEL,
                    EMBEDDING_DIM,
                    hashlib.sha256(text.encode()).hexdigest(),
                    to_blob(embeddings.embed(text)),
                    ORG_ID,
                )
            )
            if len(rows) >= self.batch_size:  # stream: 200k x 4 KB would otherwise sit in memory at once
                written += self._execute_chunks(conn, sql, rows)
                rows = []
        return written + (self._execute_chunks(conn, sql, rows) if rows else 0)

    def _seed_audit(self, conn: Any) -> int:
        """A valid SHA-256 hash chain (same canonical payload as platform_core.audit.chain), so audit
        verification and audit queries are benchmarked against real chained records."""
        log.info("Generating %d hash-chained audit records...", self.n_audit)
        sql = (
            "INSERT INTO audit_log (seq, org_id, actor, action, target, meta, ts, prev_hash, hash) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
        )
        start = datetime(2026, 10, 1, tzinfo=UTC)
        prev, rows = GENESIS_HASH, []
        for seq in range(1, self.n_audit + 1):
            rec = AuditRecord(
                seq,
                ORG_ID,
                f"loadtest-{seq % 25}",
                ("opportunity.update", "approval.decide", "export.create")[seq % 3],
                f"opportunity:{gen_uuid('opp', 1 + seq % self.n_opp)}",
                {"n": seq % 7},
                start + timedelta(seconds=seq),
                prev,
            )
            rec.hash = compute_hash(prev, rec.payload())
            rows.append(
                (
                    seq,
                    ORG_ID,
                    rec.actor,
                    rec.action,
                    rec.target,
                    json.dumps(rec.meta),
                    rec.ts.replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S.%f"),
                    prev,
                    rec.hash,
                )
            )
            prev = rec.hash
        return self._execute_chunks(conn, sql, rows)

    def _seed_graph_entities(self, conn: Any) -> int:
        log.info("Generating relational graph entity nodes...")
        sql = (
            "INSERT INTO entity (id, org_id, entity_type, ref_table, ref_id, label, attrs, source_ref, is_demo) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE label=VALUES(label)"
        )
        rows = []
        # Organization entities
        for g in range(1, self.n_org + 1):
            ent_id = gen_uuid("ent_org", g)
            ref_id = gen_uuid("org", g)
            attrs = json.dumps({"name": f"Org {g}"})
            rows.append((ent_id, ORG_ID, "organization", "organization", ref_id, "Organization", attrs, SRC_REF, 1))

        # Opportunity entities
        for g in range(1, self.n_opp + 1):
            ent_id = gen_uuid("ent_opp", g)
            ref_id = gen_uuid("opp", g)
            attrs = json.dumps({"title": f"Opp {g}"})
            rows.append((ent_id, ORG_ID, "opportunity", "opportunity", ref_id, "Opportunity", attrs, SRC_REF, 1))

        return self._execute_chunks(conn, sql, rows)

    def _seed_graph_edges(self, conn: Any) -> int:
        log.info("Generating relational graph edges (OFFERS)...")
        sql = (
            "INSERT INTO relationship_edge (id, org_id, from_entity, to_entity, type, weight, attrs, source_ref, is_demo) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) ON DUPLICATE KEY UPDATE weight=VALUES(weight)"
        )
        rows = []
        for g in range(1, self.n_opp + 1):
            edge_id = gen_uuid("edge_offers", g)
            from_ent = gen_uuid("ent_org", 1 if g == 1 else (2 + (g % (self.n_org - 1))))
            to_ent = gen_uuid("ent_opp", g)
            rows.append((edge_id, ORG_ID, from_ent, to_ent, "OFFERS", 1.0, json.dumps({}), SRC_REF, 1))
        return self._execute_chunks(conn, sql, rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="MySQL 8.4 Scale Load Generator")
    parser.add_argument("--scale", type=float, default=0.01, help="Scale factor (1.0 = 1,000,000 nodes, 0.01 = 10,000)")
    parser.add_argument("--batch-size", type=int, default=5000, help="Insert batch size")
    parser.add_argument("--host", type=str, default=os.environ.get("MYSQL_TEST_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("MYSQL_TEST_PORT", 53306)))
    parser.add_argument("--db", type=str, default=os.environ.get("MYSQL_TEST_DATABASE", "cortex_integration"))
    parser.add_argument("--user", type=str, default=os.environ.get("MYSQL_TEST_USER", "cortex"))
    parser.add_argument("--password", type=str, default=os.environ.get("MYSQL_TEST_PASSWORD"))

    args = parser.parse_args()

    cfg = {
        "host": args.host,
        "port": args.port,
        "database": args.db,
        "user": args.user,
        "password": args.password,
    }

    gen = MySQLLoadGenerator(cfg, scale=args.scale, batch_size=args.batch_size)
    gen.run()


if __name__ == "__main__":
    main()
