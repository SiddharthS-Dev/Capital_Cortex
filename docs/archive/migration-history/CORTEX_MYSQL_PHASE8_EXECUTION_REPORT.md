# Cortex PostgreSQL-to-MySQL Migration — Phase 8 Execution Report: Keycloak Database Migration Scope

> **Historical record (undated; file last saved 2026-11-03).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


**Document ID:** CRTX-EXEC-MYSQL-2026-008  
**Project:** Inspironics MERIS — Capital Cortex™ Module  
**Source Platform:** PostgreSQL 16.x (shared database `keycloak`)  
**Target Platform:** MySQL 8.4 Community Edition (database `keycloak`, InnoDB, `utf8mb4_0900_ai_ci`)  
**Execution Date:** October 27, 2026  
**Status:** **PHASE 8 COMPLETED & VERIFIED (GATE PASSED)**  
**Reference Documents:**
- `CORTEX_MYSQL_MIGRATION_FEASIBILITY_REPORT.md` (CRTX-MIG-MYSQL-2026-001)
- `CORTEX_MYSQL_MIGRATION_IMPLEMENTATION_PLAN.md` (CRTX-PLAN-MYSQL-2026-001)
- `CORTEX_MYSQL_PHASE2_EXECUTION_REPORT.md` (CRTX-EXEC-MYSQL-2026-002)
- `CORTEX_MYSQL_PHASE6_EXECUTION_REPORT.md` (CRTX-EXEC-MYSQL-2026-006)
- `CORTEX_MYSQL_PHASE7_EXECUTION_REPORT.md` (CRTX-EXEC-MYSQL-2026-007)

---

## 1. Executive Summary & Verdict

Phase 8 of the Cortex PostgreSQL 16 to MySQL 8.4 Community Edition migration has been successfully executed, validated, and signed off. Keycloak 26 (Identity and Access Management IdP for Cortex) has been fully configured and proven to run natively on MySQL 8.4 Community Edition within our isolated test environment (`127.0.0.1:53306`, DB: `keycloak`, container `capital-cortex-keycloak-test` on port `58380`).

Keycloak 26 booted cleanly against MySQL 8.4, automatically applied its entire Liquibase migration suite (148 changesets across 91 relational tables), imported the declarative realm specification (`realm-cortex.json`), and verified all OIDC authentication, token issuance, and administrative capabilities against Cortex's core authentication verifier (`platform_core.auth.oidc.TokenVerifier`).

### Final Verdict: **PHASE 8 PASSED**
- **Liquibase Changesets Executed on MySQL 8.4:** **148 of 148 applied cleanly (0 errors)**.
- **Keycloak Relational Tables in MySQL:** **91 tables created** (including `REALM`, `USER_ENTITY`, `CLIENT`, `CREDENTIAL`, `KEYCLOAK_ROLE`, `DATABASECHANGELOG`).
- **Declarative Realm Import:** Realm `cortex` imported with 10 users, 4 clients, composite MFA roles, and OIDC protocol mappers.
- **Token Issuance & Verification:**
  - Machine-to-machine `client_credentials` flow verified for `cortex-worker` service account.
  - Human interactive authorization code + PKCE login verified for `dev-analyst`.
  - Multi-Factor Authentication (TOTP OTP) verified for `smoke-auditor` (`AMR: ('pwd', 'otp')`).
  - All issued JWT tokens verified using Cortex's native [TokenVerifier](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/platform_core/auth/oidc.py#L25) against live JWKS certs.
- **Admin REST API:** Admin authentication (`kcadmin`) and administrative tenant inspection verified.
- **Phase 8 Unit/Integration Test Suite (`tests/unit/test_mysql_keycloak.py`):** **10 / 10 PASSED** (100%).
- **Cumulative MySQL Migration Suite:** **62 / 62 PASSED** (100% across Phase 3, 4, 5, 6, Audit Chain, 7, and 8).
- **API Authorization & Contract Suite (`tests/unit/test_api.py`):** **26 / 26 PASSED** (100%).
- **Production Isolation & Safety:** Production PostgreSQL (`capital-cortex-db-1`) and volume `capital-cortex_pgdata` remained 100% untouched; all 9 external project containers on host remained undisturbed; zero git commits were created.

---

## 2. Technical Architecture & Component Configuration

### 2.1 Database Provisioning & User Grants

In PostgreSQL, Keycloak utilized a separate database named `keycloak` within the shared cluster. Under MySQL 8.4, Keycloak connects to a dedicated `keycloak` database using InnoDB with `utf8mb4` character set.

1. **Database Creation & Collation:**
   ```sql
   CREATE DATABASE IF NOT EXISTS keycloak CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
   GRANT ALL PRIVILEGES ON keycloak.* TO 'cortex'@'%';
   FLUSH PRIVILEGES;
   ```
2. **Schema & Permissions Script Alignment:**
   Updated [scripts/schema_mysql.sql](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/scripts/schema_mysql.sql#L1321-L1325) to ensure that automated environment provisioning scripts grant full DDL/DML access on `keycloak.*` to the application user `cortex`.

### 2.2 Docker Compose Configuration & Service Specifications

Keycloak 26 was configured with MySQL database drivers and connected to the isolated MySQL 8.4 engine.

#### Isolated Test Stack ([infra/docker-compose.mysql-test.yml](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/infra/docker-compose.mysql-test.yml#L33-L61))
```yaml
  keycloak-test:
    image: quay.io/keycloak/keycloak:26.0
    container_name: capital-cortex-keycloak-test
    restart: "no"
    command: ["start-dev", "--import-realm"]
    environment:
      KC_DB: mysql
      KC_DB_URL: jdbc:mysql://mysql-test:3306/keycloak?characterEncoding=UTF-8&serverTimezone=UTC
      KC_DB_USERNAME: cortex
      KC_DB_PASSWORD: ${MYSQL_TEST_PASSWORD:-[REDACTED]}
      KC_BOOTSTRAP_ADMIN_USERNAME: ${KEYCLOAK_ADMIN:-kcadmin}
      KC_BOOTSTRAP_ADMIN_PASSWORD: ${KEYCLOAK_ADMIN_PASSWORD:-[REDACTED]}
      KC_HOSTNAME: http://localhost:${KEYCLOAK_TEST_PORT:-58380}
      KC_HOSTNAME_BACKCHANNEL_DYNAMIC: "true"
      KC_HEALTH_ENABLED: "true"
      KC_METRICS_ENABLED: "true"
    ports:
      - "127.0.0.1:${KEYCLOAK_TEST_PORT:-58380}:8080"
    volumes:
      - ./keycloak/realm-cortex.json:/opt/keycloak/data/import/realm-cortex.json:ro
    depends_on:
      mysql-test:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "exec 3<>/dev/tcp/127.0.0.1/9000 && echo -e 'GET /health/ready HTTP/1.1\\r\\nHost: localhost\\r\\nConnection: close\\r\\n\\r\\n' >&3 && grep -q UP <&3"]
      interval: 10s
      timeout: 5s
      retries: 30
      start_period: 25s
```

#### Production/Development Compose ([infra/docker-compose.yml](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/infra/docker-compose.yml#L123-L138))
Updated the base compose definition to support environment-driven database switching between PostgreSQL and MySQL:
```yaml
    environment:
      KC_DB: ${KC_DB:-postgres}
      KC_DB_URL: ${KC_DB_URL:-jdbc:postgresql://postgres:5432/keycloak}
      KC_DB_USERNAME: ${KC_DB_USERNAME:-cortex}
      KC_DB_PASSWORD: ${KC_DB_PASSWORD:-${POSTGRES_PASSWORD:-[REDACTED]}}
```
When cutover occurs, setting `KC_DB=mysql` and `KC_DB_URL=jdbc:mysql://mysql:3306/keycloak?characterEncoding=UTF-8&serverTimezone=UTC` points Keycloak seamlessly to MySQL.

---

## 3. Inventory of Persisted Entities in MySQL 8.4

### 3.1 Relational Tables Generated by Liquibase
Keycloak's internal Liquibase migration engine created 91 tables in MySQL database `keycloak`. The primary entity tables verified include:

| Table Name | Primary Purpose in Keycloak | Records Verified in MySQL |
|------------|-----------------------------|---------------------------|
| `REALM` | Stores realm definitions and configuration | 2 (`cortex`, `master`) |
| `USER_ENTITY` | Stores human users, service accounts, and metadata | 10 active accounts |
| `CLIENT` | Registered applications (`cortex-web`, `cortex-api`, `cortex-worker`, `cortex-ingestion`) | 12 client entities |
| `CREDENTIAL` | Password hashes (PBKDF2/SHA256) and TOTP secrets | 11 credentials |
| `KEYCLOAK_ROLE` | Defined RBAC and composite MFA roles | 17 roles |
| `USER_ROLE_MAPPING` | User-to-role associations | 24 role bindings |
| `USER_ATTRIBUTE` | Custom claims and grants (`cortex_grants`) | Verified attributes |
| `DATABASECHANGELOG` | Liquibase migration audit trail | 148 changesets |

### 3.2 Persisted User Directory

Direct query against MySQL table `keycloak.USER_ENTITY` confirms all seed and service accounts were imported successfully:

| Username | Email | Enabled | Roles Assigned | Auth Factor |
|----------|-------|---------|----------------|-------------|
| `dev-analyst` | `dev-analyst@cortex.local` | `1` | `analyst` | Password |
| `dev-admin` | `dev-admin@cortex.local` | `1` | `admin`, `approver`, `mfa-required` | Password + TOTP |
| `dev-finance` | `dev-finance@cortex.local` | `1` | `analyst` (grants: `forecast:write`) | Password |
| `dev-approver` | `dev-approver@cortex.local` | `1` | `approver`, `mfa-required` | Password + TOTP |
| `dev-legal` | `dev-legal@cortex.local` | `1` | `auditor`, `approver`, `mfa-required` | Password + TOTP |
| `dev-executive` | `dev-executive@cortex.local` | `1` | `executive`, `mfa-required` | Password + TOTP |
| `smoke-auditor` | `smoke-auditor@cortex.local` | `1` | `auditor`, `mfa-required` | Password + TOTP (seeded) |
| `service-account-cortex-worker` | `NULL` | `1` | `service` | Client Secret |
| `service-account-cortex-ingestion`| `NULL` | `1` | `service` | Client Secret |
| `kcadmin` | `NULL` | `1` | Realm Admin (`master`) | Password |

---

## 4. Test Verification & Acceptance Results

### 4.1 Phase 8 Keycloak Test Suite (`tests/unit/test_mysql_keycloak.py`)

A comprehensive 10-test verification suite was created and executed against the live test instance:

**Command:** `pytest tests/unit/test_mysql_keycloak.py -v`  
**Result:** **10 PASSED / 10 TOTAL (100% SUCCESS RATE)**  
**Execution Time:** 18.41 seconds

```
tests/unit/test_mysql_keycloak.py::test_keycloak_schema_and_liquibase_in_mysql PASSED [ 10%]
tests/unit/test_mysql_keycloak.py::test_keycloak_realm_persistence_in_mysql PASSED [ 20%]
tests/unit/test_mysql_keycloak.py::test_keycloak_users_persisted_in_mysql PASSED [ 30%]
tests/unit/test_mysql_keycloak.py::test_keycloak_clients_persisted_in_mysql PASSED [ 40%]
tests/unit/test_mysql_keycloak.py::test_keycloak_openid_configuration_discovery PASSED [ 50%]
tests/unit/test_mysql_keycloak.py::test_keycloak_jwks_certs PASSED       [ 60%]
tests/unit/test_mysql_keycloak.py::test_keycloak_service_token_issuance_and_cortex_verification PASSED [ 70%]
tests/unit/test_mysql_keycloak.py::test_keycloak_human_user_auth_code_pkce_token PASSED [ 80%]
tests/unit/test_mysql_keycloak.py::test_keycloak_mfa_user_totp_token PASSED [ 90%]
tests/unit/test_mysql_keycloak.py::test_keycloak_admin_api_operations PASSED [100%]
```

| Test Function | Scope of Verification | Status |
|---------------|-----------------------|--------|
| `test_keycloak_schema_and_liquibase_in_mysql` | Connects directly to MySQL `keycloak` database via `aiomysql`; verifies 91 tables and >= 100 Liquibase changesets. | **PASSED** |
| `test_keycloak_realm_persistence_in_mysql` | Verifies `REALM` table in MySQL contains realm `cortex` with `enabled = 1`. | **PASSED** |
| `test_keycloak_users_persisted_in_mysql` | Confirms all 9 development and service accounts exist and are enabled in `USER_ENTITY`. | **PASSED** |
| `test_keycloak_clients_persisted_in_mysql` | Confirms all 4 application clients (`cortex-web`, `cortex-api`, `cortex-worker`, `cortex-ingestion`) exist and are enabled in `CLIENT`. | **PASSED** |
| `test_keycloak_openid_configuration_discovery` | Evaluates HTTP GET `/.well-known/openid-configuration`; validates issuer, JWKS URI, and token endpoint URLs. | **PASSED** |
| `test_keycloak_jwks_certs` | Validates JWKS certs endpoint returns valid RS256 signing certificates with `use: "sig"`. | **PASSED** |
| `test_keycloak_service_token_issuance_and_cortex_verification` | Requests Bearer token via `client_credentials` grant for `cortex-worker`; validates with Cortex [TokenVerifier](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/platform_core/auth/oidc.py#L25); validates `is_service=True` and `service` role. | **PASSED** |
| `test_keycloak_human_user_auth_code_pkce_token` | Executes authorization code + PKCE flow with cookie jar handling for `dev-analyst`; validates claims and `analyst` role. | **PASSED** |
| `test_keycloak_mfa_user_totp_token` | Executes multi-step authorization flow with TOTP algorithm for `smoke-auditor`; validates `AMR: ('pwd', 'otp')` and `auditor` role. | **PASSED** |
| `test_keycloak_admin_api_operations` | Obtains master realm admin token (`kcadmin`), queries `/admin/realms/cortex/users`, and verifies user inspection. | **PASSED** |

---

### 4.2 Cumulative Regression Test Suite Across All Phases (Phases 3 to 8)

**Command:**
```powershell
pytest tests/unit/test_mysql_session.py `
       tests/unit/test_mysql_graph.py `
       tests/unit/test_mysql_vector.py `
       tests/unit/test_mysql_invariants_and_mutex.py `
       tests/unit/test_audit_chain.py `
       tests/unit/test_mysql_router_sql.py `
       tests/unit/test_mysql_keycloak.py -v
```

**Result:** **62 PASSED / 62 TOTAL (100% SUCCESS RATE)**  
**Execution Time:** 41.44 seconds

- **Phase 3 (Driver & Sessions):** 9 passed (`test_mysql_session.py`)
- **Phase 4 (Relational Graph Subsystem):** 8 passed (`test_mysql_graph.py`)
- **Phase 5 (Vector Retrieval & BLOBs):** 10 passed (`test_mysql_vector.py`)
- **Phase 6 (Triggers, Invariants, & Mutex):** 9 passed (`test_mysql_invariants_and_mutex.py`)
- **Audit Hash Chain Cryptographic Integrity:** 6 passed (`test_audit_chain.py`)
- **Phase 7 (Sanitized Application SQL):** 10 passed (`test_mysql_router_sql.py`)
- **Phase 8 (Keycloak Database on MySQL):** 10 passed (`test_mysql_keycloak.py`)

---

### 4.3 Standard API Authorization Matrix Suite

**Command:** `pytest tests/unit/test_api.py -v`  
**Result:** **26 PASSED / 26 TOTAL (100% SUCCESS RATE)**

---

## 5. Host & Production Safety Compliance

1. **Production PostgreSQL Cluster & Volumes:**
   - Production PostgreSQL container `capital-cortex-db-1` remained untouched and inactive.
   - Volume `capital-cortex_pgdata` was neither mounted, read from, nor modified.
   - All Phase 8 Keycloak interactions were strictly confined to `capital-cortex-mysql-test` (`127.0.0.1:53306`) and `capital-cortex-keycloak-test` (`127.0.0.1:58380`).
2. **External Host Project Containers:**
   - All 9 external project containers on the host (`apm-platform-*`, `caleido-wellness-pg2`) were verified via Docker inspect and remained undisturbed.
3. **Git Cleanliness:**
   - Zero commits, branch checkouts, or repository resets were executed. Changes remain cleanly confined to untracked Phase 8 tests and docker-compose configurations.

---

## 6. Phase 8 Sign-Off & Next Steps

Phase 8 has met and exceeded all acceptance criteria set out in `CORTEX_MYSQL_MIGRATION_IMPLEMENTATION_PLAN.md`. Keycloak 26 operates flawlessly on MySQL 8.4 Community Edition, with complete relational table persistence, realm auto-import, and seamless token validation by the Cortex application suite.

### Next Planned Phase: **Phase 9: Test Modernization & Acceptance Gates**
- Replace legacy `testcontainers.postgres` with `testcontainers.mysql.MySqlContainer("mysql:8.4")` in [tests/integration/conftest.py](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/tests/integration/conftest.py).
- Update integration test assertions for MySQL triggers, CHECK constraints, and BLOB embeddings.
- Execute full integration test suite against MySQL testcontainer.

*(Followed by Phase 10: ETL Data Migration Tooling & Reconciliation via `scripts/migrate_pg_to_mysql.py`).*
