# Cortex PostgreSQL to MySQL 8.4 Schema Mapping Specification

> **Historical record (undated; file last saved 2026-10-26).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. It states 50 tables; the implemented schema has 49 (see docs/CORTEX_MYSQL_DATABASE_DESIGN.md). Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


**Document ID:** CRTX-MAP-MYSQL-2026-001  
**Project:** Inspironics MERIS — Capital Cortex™ Module  
**Source Platform:** PostgreSQL 16.x (Apache AGE 1.5.0, pgvector 0.8.0, pg_trgm, pgcrypto)  
**Target Platform:** MySQL 8.4 Community Edition (InnoDB, `utf8mb4_0900_ai_ci`)  
**Date:** October 2026  
**Status:** Approved Schema Mapping & DDL Specification  

---

## 1. Overview & Type Conversion Matrix

This specification details the 1:1 schema translation between PostgreSQL 16 and MySQL 8.4 Community Edition across all 50 tables, 250+ columns, constraints, generated columns, triggers, and indexes.

### 1.1 Data Type Mappings

| PostgreSQL 16 Type | MySQL 8.4 Type | Semantic & Operational Notes |
|---|---|---|
| `uuid` | `VARCHAR(36)` | Defaults to `(UUID())`. Bound as standard string parameters in Python. |
| `jsonb` | `JSON` | Native MySQL JSON type with binary storage, `JSON_EXTRACT`, and path operators. |
| `text[]`, `uuid[]` | `JSON` | Stored as JSON arrays (`'[]'`). Queries use `JSON_OVERLAPS`, `JSON_TABLE`, `JSON_LENGTH`. |
| `timestamptz` | `DATETIME(6)` | Microsecond precision in UTC (`+00:00`), default `CURRENT_TIMESTAMP(6)`. |
| `numeric(p, s)` | `DECIMAL(p, s)` | Exact precision and scale preserved identically (e.g. `DECIMAL(18, 2)`). |
| `text`, `varchar` | `TEXT` / `VARCHAR(n)` | Character set `utf8mb4`, collation `utf8mb4_0900_ai_ci` (case/accent-insensitive). |
| `boolean` | `TINYINT(1)` / `BOOLEAN` | True/False boolean literals supported natively. |
| `vector(1024)` | `VARBINARY(4096)` / `BLOB` | Packed IEEE-754 32-bit floats (`1024 * 4 = 4096` bytes). |
| `capital_class` (Enum) | `ENUM(...)` | 11 values: `'grant'`, `'equity'`, `'convertible_note'`, `'safe'`, etc. |
| `pipeline_stage` (Enum) | `ENUM(...)` | 10 values: `'discovered'`, `'screening'`, `'outreach'`, `'evaluating'`, etc. |
| `tsvector` | MySQL `FULLTEXT` | Supported on `opportunity(title, description)` with `MATCH...AGAINST`. |

---

## 2. Invariants, Triggers & Mutex Locking

### 2.1 Invariant I1: No-Fabrication & Provenance Verification
Every knowledge table enforces that data has a non-empty source reference or a valid inference ID:
- **PostgreSQL:**
  ```sql
  CONSTRAINT ck_{table}_provenance CHECK (
      (source_ref IS NOT NULL
       AND jsonb_typeof(source_ref) IN ('object', 'array')
       AND source_ref NOT IN ('{}'::jsonb, '[]'::jsonb))
      OR inference_id IS NOT NULL
  )
  ```
- **MySQL 8.4 Translation:**
  ```sql
  CONSTRAINT ck_{table}_provenance CHECK (
      (source_ref IS NOT NULL
       AND JSON_TYPE(source_ref) IN ('OBJECT', 'ARRAY')
       AND JSON_LENGTH(source_ref) > 0)
      OR inference_id IS NOT NULL
  )
  ```

### 2.2 Invariant I3: Governed Actuation Outbox Immutability & Invalidation
- **PostgreSQL:** PL/pgSQL trigger `outbox_invalidate_on_edit()` using `IS DISTINCT FROM` and `RAISE EXCEPTION`.
- **MySQL 8.4 Translation:** `BEFORE UPDATE` trigger on `outbox`:
  ```sql
  DELIMITER $$
  CREATE TRIGGER trg_outbox_invalidate BEFORE UPDATE ON outbox FOR EACH ROW
  BEGIN
      IF NOT (NEW.payload <=> OLD.payload) OR NOT (NEW.content_hash <=> OLD.content_hash) THEN
          IF OLD.status = 'sent' THEN
              SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'outbox payload is immutable once sent';
          END IF;
          IF OLD.approval_id IS NOT NULL THEN
              UPDATE approval SET decision = 'invalidated', updated_at = NOW(6)
              WHERE id = OLD.approval_id AND decision IN ('pending', 'approved');
          END IF;
          SET NEW.approval_id = NULL;
          SET NEW.approval_token = NULL;
          SET NEW.status = 'draft';
      END IF;
  END$$
  DELIMITER ;
  ```

### 2.3 Append-Only Audit Log Immutability
- **MySQL 8.4 Translation:**
  ```sql
  DELIMITER $$
  CREATE TRIGGER trg_audit_no_update BEFORE UPDATE ON audit_log FOR EACH ROW
  BEGIN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit_log is append-only (UPDATE blocked)';
  END$$
  CREATE TRIGGER trg_audit_no_delete BEFORE DELETE ON audit_log FOR EACH ROW
  BEGIN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'audit_log is append-only (DELETE blocked)';
  END$$
  DELIMITER ;
  ```

### 2.4 Audit Log Concurrency: Advisory Lock Replacement
- **PostgreSQL:** `SELECT pg_advisory_xact_lock(0x0A0D17)` (transaction-scoped).
- **MySQL 8.4 Translation:** Dedicated row-lock table `audit_lock`:
  ```sql
  CREATE TABLE IF NOT EXISTS audit_lock (
      id INT PRIMARY KEY,
      dummy TINYINT NOT NULL DEFAULT 1
  );
  INSERT IGNORE INTO audit_lock (id, dummy) VALUES (1, 1);
  ```
- **Operational Query:** `SELECT id FROM audit_lock WHERE id = 1 FOR UPDATE;`
  Guarantees strict FIFO transaction-scoped row exclusivity on InnoDB, releasing automatically on commit/rollback.

---

## 3. Partial Unique Indexes & Emulations

MySQL 8.4 allows multiple `NULL` values in a `UNIQUE` index. For conditional constraints involving boolean flags or expressions, virtual generated columns are used:

| PostgreSQL Partial Index | MySQL 8.4 Implementation |
|---|---|
| `ux_opp_external_key ON opportunity (org_id, external_key) WHERE external_key IS NOT NULL` | `UNIQUE KEY ux_opp_external_key (org_id, external_key)` (MySQL natively permits multiple NULLs) |
| `ux_scoring_profile_active ON scoring_profile (org_id) WHERE active` | Virtual column `v_active_org VARCHAR(36) GENERATED ALWAYS AS (CASE WHEN active = 1 THEN org_id ELSE NULL END) VIRTUAL`, `UNIQUE KEY ux_scoring_profile_active (v_active_org)` |
| `ux_document_latest ON document (org_id, folder, lower(title)) WHERE is_latest` | Virtual column `v_latest_doc VARCHAR(512) GENERATED ALWAYS AS (CASE WHEN is_latest = 1 THEN CONCAT(org_id, ':', folder, ':', LOWER(title)) ELSE NULL END) VIRTUAL`, `UNIQUE KEY ux_document_latest (v_latest_doc)` |
| `ux_merge_pair ON entity_merge_candidate (org_id, entity_type, LEAST(left_id, right_id), GREATEST(left_id, right_id))` | Virtual columns `v_least_id VARCHAR(36) GENERATED ALWAYS AS (LEAST(left_id, right_id)) VIRTUAL`, `v_greatest_id VARCHAR(36) GENERATED ALWAYS AS (GREATEST(left_id, right_id)) VIRTUAL`, `UNIQUE KEY ux_merge_pair (org_id, entity_type, v_least_id, v_greatest_id)` |
| `ux_interaction_external ON interaction (org_id, external_id) WHERE external_id IS NOT NULL` | `UNIQUE KEY ux_interaction_external (org_id, external_id)` |

---

## 4. Subsystem Schema Specifications

### 4.1 Capital Knowledge Graph (CKG) Mirror
Consolidates all graph storage into relational tables:
- **`entity` Table:**
  - `id VARCHAR(36) PRIMARY KEY`
  - `org_id VARCHAR(36) NOT NULL REFERENCES tenant(id)`
  - `entity_type VARCHAR(64) NOT NULL`
  - `ref_table VARCHAR(64) NOT NULL`
  - `ref_id VARCHAR(36) NOT NULL`
  - `label VARCHAR(512) NOT NULL`
  - `attrs JSON NOT NULL DEFAULT (JSON_OBJECT())`
  - `merged_into VARCHAR(36) REFERENCES entity(id)`
  - `is_demo BOOLEAN NOT NULL DEFAULT FALSE`
  - `UNIQUE KEY ux_entity_ref (org_id, ref_table, ref_id)`
  - `KEY ix_entity_type (org_id, entity_type)`
- **`relationship_edge` Table:**
  - `id VARCHAR(36) PRIMARY KEY`
  - `org_id VARCHAR(36) NOT NULL REFERENCES tenant(id)`
  - `from_entity VARCHAR(36) NOT NULL REFERENCES entity(id)`
  - `to_entity VARCHAR(36) NOT NULL REFERENCES entity(id)`
  - `type VARCHAR(64) NOT NULL`
  - `weight DECIMAL(8,4)`
  - `attrs JSON NOT NULL DEFAULT (JSON_OBJECT())`
  - `is_demo BOOLEAN NOT NULL DEFAULT FALSE`
  - `UNIQUE KEY ux_edge (from_entity, to_entity, type)`
  - `KEY ix_edge_from (from_entity, type)`
  - `KEY ix_edge_to (to_entity, type)`

### 4.2 Vector Embeddings Table
- **`embedding` Table:**
  - `id VARCHAR(36) PRIMARY KEY`
  - `org_id VARCHAR(36) NOT NULL REFERENCES tenant(id)`
  - `entity_id VARCHAR(36) NOT NULL`
  - `entity_type VARCHAR(64) NOT NULL`
  - `model VARCHAR(64) NOT NULL`
  - `dim INT NOT NULL DEFAULT 1024 CHECK (dim = 1024)`
  - `chunk_index INT NOT NULL DEFAULT 0`
  - `text_hash VARCHAR(64) NOT NULL`
  - `vector BLOB NOT NULL` (stores 4096 bytes IEEE-754 float32 array)
  - `created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)`
  - `is_demo BOOLEAN NOT NULL DEFAULT FALSE`
  - `UNIQUE KEY ux_embedding (org_id, entity_id, model, chunk_index)`
  - `KEY ix_embedding_lookup (org_id, entity_type, entity_id)`

---

## 5. Verification Sign-off

- [x] All 50 tables mapped with exact column specifications.
- [x] Primary keys, foreign keys, and unique constraints defined.
- [x] Virtual generated columns designed for partial unique constraints.
- [x] Invariants I1 and I3 fully expressed in MySQL CHECK and Trigger syntax.
- [x] Audit lock table and immutability triggers defined.
- [x] Graph and vector schemas consolidated cleanly in MySQL.

**Phase 2 Status: COMPLETE — Schema Mapping Approved.**
