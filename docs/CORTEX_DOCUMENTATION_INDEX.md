# Capital Cortex: Documentation Index and Checklist

Maps each documentation area to the document that covers the implemented MySQL 8.4 behaviour, and the commit that
carries it. A document marked historical records its date and is not updated.

| Area | Document | Commit | State |
|---|---|---|---|
| README and setup | `README.md` | 58 | Current |
| Architecture and decisions | `README.md`, `docs/DECISIONS.md` (D-100), `docs/CORTEX_ARCHITECTURE_DECISION_REGISTER.md` | 58, 59 | Current |
| Database design and schema | `docs/CORTEX_MYSQL_DATABASE_DESIGN.md`, `scripts/schema_mysql.sql` | 58, 05 | Current |
| Migration | `CORTEX_MYSQL_CUTOVER_RUNBOOK.md`, `docs/CORTEX_MYSQL_PRODUCTION_MIGRATION_RUNBOOK.md`, `docs/CORTEX_MYSQL_MIGRATION_SAFETY_VERIFICATION.md` | 58, 59 | Current, not executed in production |
| Rollback | `docs/CORTEX_MYSQL_ROLLBACK_RUNBOOK.md` | 58 | Current |
| Version compatibility | `docs/CORTEX_MYSQL_VERSION_COMPATIBILITY.md`, `docs/CORTEX_MYSQL_COMPATIBILITY_AUDIT.md`, `docs/CORTEX_POSTGRESQL_DEPENDENCY_CLOSURE.md` | 58, 59 | Current |
| API | `docs/API.md`, `docs/openapi.json` | 58, 37 | Current |
| Security and credentials | `.env.example`, `docs/SECURITY_CREDENTIAL_ROTATION_RUNBOOK.md`, `docs/CORTEX_MYSQL_SECURITY_READINESS.md` | 39, 60 | Current |
| Docker and deployment | `docs/RUNBOOK.md` section 1, `infra/docker-compose.mysql.yml`, `Makefile` | 58, 39, 53 | Current |
| Testing | `docs/CORTEX_MYSQL_TEST_EVIDENCE.md`, `docs/CORTEX_MYSQL_TECHNICAL_PROOF_REPORT.md` | 59 | Current |
| Performance | `docs/CORTEX_MYSQL_PERFORMANCE_REPORT.md`, `docs/CORTEX_PERFORMANCE_AUDIT.md` | 59 | PERF-1 still open |
| Operations | `docs/RUNBOOK.md` | 58 | Current. Section 8.0 is the MySQL backup procedure |
| Migration history | `docs/CORTEX_MYSQL_MIGRATION_HISTORY.md`, `docs/archive/migration-history/README.md` | follow-up | Current summary; the archived reports are historical |
| Production migration plan for DevOps | `docs/CORTEX_PRODUCTION_MIGRATION_ACTION_PLAN.md` | follow-up | Current; B1 to B3 open |
| Test evidence index | `docs/CORTEX_MYSQL_EVIDENCE_INDEX.md` | follow-up | Index of the raw local logs, which are kept out of Git |
| Open items and readiness | `docs/CORTEX_MYSQL_BLOCKER_REGISTER.md`, `docs/CORTEX_PRODUCTION_READINESS_CHECKLIST.md` | 60 | Current |

## Historical documents (PostgreSQL era, unchanged)

`docs/PHASE_0.md` to `PHASE_3.md`, `docs/DEMO_0.md` to `DEMO_3.md`, `docs/LOAD_TEST.md`, `docs/SECURITY_SCAN.md`,
`docs/traceability.md`, `tests/load/README.md`, `CapitalCortex_Master_Build_Prompt.md`. Mentions of PostgreSQL, Apache
AGE or pgvector in them describe the system at that date. Decision D-100 records what replaced them.

Dated working reports from the migration are kept in `docs/archive/migration-history/`, marked as historical, with
machine-specific paths replaced. Raw test logs stay out of the repository because they contain machine-specific
paths; `docs/CORTEX_MYSQL_EVIDENCE_INDEX.md` lists what each one recorded.
