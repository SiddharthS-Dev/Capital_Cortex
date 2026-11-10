# B1 — Production PostgreSQL Backup Readiness

> **Historical record (dated 2026-11-02).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


**Date:** 2026-11-02 · **Blocker status: OPEN.** No production backup evidence exists.
Nothing was created, downloaded, overwritten or deleted in any backup location. The two volumes were mounted read-only.

## Answers to the B1 questions

| # | Question | Answer | Status | Evidence |
|---|---|---|---|---|
| 1 | Is a production PG backup procedure implemented? | **Yes, as tooling for the Compose stack.** It covers continuous WAL archiving plus nightly `pg_basebackup` and `pg_dump -Fc` of `cortex` and `keycloak`, with `pg_dumpall --globals-only` and a sha256 manifest uploaded last. Retention keeps 7 bases. | VERIFIED (code + docs) | `scripts/backup.py`, `infra/postgres/archive-wal.sh`, `docs/RUNBOOK.md` §8 (lines 91-125), `make.ps1:69` |
| 2 | Is there evidence of a *production* backup? | **No.** | NOT_FOUND | No production host exists in the repo (B2). No backup ID, log or ticket references production. |
| 3 | Is an actual artifact in approved project storage? | **No.** `cortex-backups` (MinIO volume `capital-cortex_miniodata`) is empty. No dump or archive files exist in the project tree. | VERIFIED (absent) | Read-only `find /data/cortex-backups` → empty, 4 KB |
| 4 | Timestamp / size / checksum | n/a, no artifact | NOT_FOUND | — |
| 5 | Is the backup encrypted? | **The tooling does not encrypt.** Uploads go to MinIO with no SSE or KMS option and no client-side encryption. `docs/RUNBOOK.md:116-121` itself says production must replicate off-host and restrict the bucket (`globals.sql` holds role hashes; `keycloak.dump` holds TOTP secrets). | VERIFIED (gap) | `scripts/backup.py:198-217`, no `encrypt`/`sse`/`kms` anywhere in `scripts/` |
| 6 | Is a restore procedure documented? | **Yes, for PostgreSQL** (drill + real incident: `docs/RUNBOOK.md` §8.2-8.3; `infra/docker-compose.restore.yml`). **For MySQL**, only an un-run `mysqldump` line existed (`CORTEX_MYSQL_CUTOVER_RUNBOOK.md:95-98`). This audit verified that procedure on a test server (below). | VERIFIED | paths given |
| 7 | Has a backup been restored and verified? | **Development only, and historical.** `docs/RUNBOOK.md:187-190` records PASS drills on 2026-09-30 against an earlier 45 MB dev cluster. Those backups no longer exist: the bucket is empty, and the MinIO and PG volumes were recreated on 2026-10-23. No production restore is on record. | PARTIALLY_VERIFIED (dev, docs only) | — |
| 8 | Is the available data only dev/test? | **Yes.** The only Capital Cortex PG data (`capital-cortex_pgdata`) is synthetic demo data. The WAL archive volume `capital-cortex_pgwal` holds 19 segments (19.2 MB), all from 2026-10-23 06:36–10:33. Archiving stopped when that stack stopped. | VERIFIED | `CORTEX_MYSQL_BLOCKER_CLOSURE_REPORT.md:7`; read-only listing of `capital-cortex_pgwal` |

## MySQL-side backup/restore (target side, verified on isolated databases)

This audit ran it on the test server only (`capital-cortex-mysql-test`, MySQL 8.4.13), reading `cortex_pgcopy_rehearsal` and writing a new database.

```
mysqldump --single-transaction --routines --triggers --events --set-gtid-purged=OFF --hex-blob cortex_pgcopy_rehearsal
  → 22,739,039 bytes, sha256 bc918c1de321ff4d…, 38 s
restore into NEW database cortex_restore_drill_20261102 → 85 s
50/50 tables · 11,362 rows · CHECKSUM TABLE EXTENDED mismatches = 0 · triggers 4/4 · audit_lock row present
```

Notes for production MySQL:
- `--hex-blob` is required. The 4096-byte float32 vector BLOBs must round-trip byte-exact.
- `--routines --triggers` is required. The audit append-only triggers are part of the tamper-evidence design.
- `infra/docker-compose.mysql.yml` ships binlogs (`mysql-binlog-shipper`) to the **same-host** MinIO. No scheduled MySQL
  base backup exists yet, and nothing encrypts it. Point-in-time restore from binlogs has not been rehearsed.
- The scratch DB `cortex_restore_drill_20261102` was left in place as evidence. Dropping it is safe but was not done (no deletes without approval).

## What DevOps must provide to close B1

1. A **full, consistent backup of the production PostgreSQL** covering the `cortex` and `keycloak` databases and the globals. Either:
   - `pg_dump -Fc` of each DB plus `pg_dumpall --globals-only` (role hashes may be excluded/sanitised), or
   - the project format (`scripts/backup.py` output: base + dumps + `manifest.json`).
2. With it: the backup timestamp (UTC), source host identifier, PostgreSQL version, `SELECT version_num FROM alembic_version`,
   installed extensions (`age`, `vector`), file sizes and **sha256 of every file**.
3. The **encryption method** used at rest and in transit, and where the decryption key is held (not the key itself).
4. A **storage location approved for production data** that the migration engineer may read from. A personal OneDrive
   folder is not suitable for production PII or TOTP secrets.
5. Confirmation of whether the dump may be used as-is or must be **sanitised** for rehearsal (PII, TOTP secrets).
6. The production backup **retention policy** and the latest **restore-test** date, if any.

## Close criteria

B1 closes only when all of the following hold:
- (a) an artifact from the production source exists in approved storage;
- (b) its checksums match what DevOps stated;
- (c) it has been restored into an isolated PostgreSQL 16 + AGE + pgvector container (never production);
- (d) the restored row counts match DevOps's figures.

**Owner:** DevOps (artifact, encryption, storage) · DBA (restore verification) · Developer (rehearsal ETL on the restore).
