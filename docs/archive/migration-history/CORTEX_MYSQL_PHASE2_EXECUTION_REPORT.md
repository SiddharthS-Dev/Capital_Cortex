# Cortex PostgreSQL-to-MySQL Migration — Phase 2 Execution Report: Isolated Test Environment Setup

> **Historical record (undated; file last saved 2026-11-03).** Preserved for reference and superseded by the current documents in `docs/CORTEX_DOCUMENTATION_INDEX.md`. Its status, counts and blockers describe that date only. Machine-specific paths were replaced with placeholders such as `<repo>`; nothing else was changed.


**Document ID:** CRTX-EXEC-MYSQL-2026-002  
**Project:** Inspironics MERIS — Capital Cortex™ Module  
**Source Platform:** PostgreSQL 16.x (Apache AGE 1.5.0, pgvector 0.8.0, pg_trgm, pgcrypto)  
**Target Platform:** MySQL 8.4 Community Edition (InnoDB, `utf8mb4_0900_ai_ci`)  
**Execution Date:** October 26, 2026  
**Status:** **PHASE 2 COMPLETED & VERIFIED (GATE PASSED)**  
**Reference Documents:**
- `CORTEX_MYSQL_MIGRATION_FEASIBILITY_REPORT.md` (CRTX-MIG-MYSQL-2026-001)
- `CORTEX_MYSQL_MIGRATION_VERIFICATION_REPORT.md` (CRTX-VERIF-MYSQL-2026-002)
- `CORTEX_MYSQL_MIGRATION_IMPLEMENTATION_PLAN.md` (CRTX-PLAN-MYSQL-2026-001)

---

## 1. Executive Summary

Phase 2 of the Cortex PostgreSQL-to-MySQL migration has been successfully executed under strict safety protocols. An independent, isolated **MySQL 8.4 Community Edition** test environment has been stood up, configured, and verified. 

Key outcomes:
1. **Zero Disruption to Existing Services:** The production/development PostgreSQL cluster, shared `infra/docker-compose.yml`, application `.env` database URLs, and volume `capital-cortex_pgdata` remain 100% untouched and intact.
2. **Complete Project & Network Isolation:** The new test stack operates under a dedicated Docker Compose project name (`capital-cortex-mysql-test`), host port (`53306` bound to `127.0.0.1`), and dedicated volume (`capital-cortex_mysql_test_data`).
3. **No Container Interference:** All 9 active external project containers running on the host remained online with continuous uptime and healthy status.
4. **Verified Health & Connectivity:** MySQL Community Server `8.4.13` is running and reporting healthy via internal socket checks and external TCP connectivity tests on host port `53306`.
5. **Git Safety & Working Tree Preservation:** All pre-existing user modifications (including the 7 baseline modified files and subsequent working tree edits) have been strictly preserved with zero git commits, resets, or file deletions.

---

## 2. Infrastructure & Files Created

| File / Resource | Type | Purpose | Isolation & Safety Details |
|---|---|---|---|
| [`infra/docker-compose.mysql-test.yml`](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/infra/docker-compose.mysql-test.yml) | Compose Spec | Defines isolated MySQL 8.4 test service | Standalone file; project name `capital-cortex-mysql-test`. Leaves [`infra/docker-compose.yml`](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/infra/docker-compose.yml) untouched. |
| [`.env`](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/.env) (Local config) | Environment File | Provides test credentials & port configuration | Ignored by `.gitignore`. Uses environment variable overrides (`MYSQL_TEST_PORT=53306`). Real secrets not hardcoded into tracked files. |
| `capital-cortex_mysql_test_data` | Docker Volume | Persistent storage for MySQL test data | Independent volume; zero collision with `capital-cortex_pgdata`. |
| `capital-cortex-mysql-test` | Docker Container | Runs MySQL 8.4 Community Server | Bound strictly to `127.0.0.1:53306->3306`. `restart: "no"`. |

### Compose Configuration Specification
```yaml
name: capital-cortex-mysql-test

services:
  mysql-test:
    image: mysql:8.4
    container_name: capital-cortex-mysql-test
    restart: "no"
    command:
      - --character-set-server=utf8mb4
      - --collation-server=utf8mb4_0900_ai_ci
      - --innodb-buffer-pool-size=512M
      - --max-connections=100
      - --default-time-zone=+00:00
    environment:
      MYSQL_ROOT_PASSWORD: ${MYSQL_TEST_ROOT_PASSWORD:-[REDACTED]}
      MYSQL_DATABASE: ${MYSQL_TEST_DATABASE:-cortex}
      MYSQL_USER: ${MYSQL_TEST_USER:-cortex}
      MYSQL_PASSWORD: ${MYSQL_TEST_PASSWORD:-[REDACTED]}
    ports:
      - "127.0.0.1:${MYSQL_TEST_PORT:-53306}:3306"
    volumes:
      - capital-cortex_mysql_test_data:/var/lib/mysql
    healthcheck:
      test: ["CMD-SHELL", "mysqladmin ping -h 127.0.0.1 -u root -p$$MYSQL_ROOT_PASSWORD"]
      interval: 5s
      timeout: 5s
      retries: 30
      start_period: 15s

volumes:
  capital-cortex_mysql_test_data:
    name: capital-cortex_mysql_test_data
```

---

## 3. Environment Validation & Health Evidence

### 3.1 Container Runtime & Health Status
- **Image:** `mysql:8.4` (resolving to MySQL Community Server `8.4.13-1.el9`)
- **Container Name:** `capital-cortex-mysql-test`
- **State:** `Up (healthy)`
- **Port Mapping:** `127.0.0.1:53306->3306/tcp`

Verification Command:
```powershell
docker ps --filter "name=capital-cortex-mysql-test"
```
Observed Output:
```text
CONTAINER ID   IMAGE       COMMAND                  CREATED       STATUS                   PORTS                       NAMES
67ab1469645a   mysql:8.4   "docker-entrypoint.s…"   2 hours ago   Up 2 minutes (healthy)   127.0.0.1:53306->3306/tcp   capital-cortex-mysql-test
```

### 3.2 Host Port Availability & Connectivity
- **Host Port:** `53306` (verified available prior to starting container)
- **TCP Connection Test:** Succeeded (`TcpTestSucceeded : True`)
- **Protocol Handshake:** Successfully received MySQL server handshake banner (`8.4.13`) on host port `53306`.

Verification Command:
```powershell
Test-NetConnection -ComputerName 127.0.0.1 -Port 53306
```
Observed Output:
```text
ComputerName     : 127.0.0.1
RemoteAddress    : 127.0.0.1
RemotePort       : 53306
InterfaceAlias   : Loopback Pseudo-Interface 1
SourceAddress    : 127.0.0.1
TcpTestSucceeded : True
```

Python Host Socket Verification:
```powershell
.venv\Scripts\python -c "import socket; s = socket.socket(); s.connect(('127.0.0.1', 53306)); banner = s.recv(100); print(banner[:40]); s.close()"
```
Observed Output:
```text
b"J\x00\x00\x00\n8.4.13\x00\x1e\x00\x00\x00ro\x7fT4%G'\x00\xff\xff\xff\x02\x00\xff\xdf\x15\x00\x00\x00\x00\x00\x00\x00"
```

### 3.3 Database Existence & Authentication
The test database `cortex` was verified to exist inside the MySQL instance, accessible using the configured test user credentials:
```powershell
docker exec -e MYSQL_PWD=[REDACTED] capital-cortex-mysql-test mysql -u cortex -e "SHOW DATABASES; SELECT VERSION();" cortex
```
Observed Output:
```text
Database
cortex
information_schema
performance_schema
VERSION()
8.4.13
```

---

## 4. Safety & Isolation Verification

### 4.1 PostgreSQL Data & Configuration Preservation
1. **Volume Preservation:** Verified that `capital-cortex_pgdata` exists on host and has not been altered or accessed.
   - Volume Name: `capital-cortex_pgdata`
   - Created At: `2026-10-23T06:35:42Z`
   - Project: `capital-cortex`
   - Status: **Intact & Unchanged**
2. **Configuration Preservation:** [`infra/docker-compose.yml`](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/infra/docker-compose.yml) was **not edited**.
3. **Extensions Preservation:** Apache AGE (`01-extensions.sql`) and pgvector configurations remain intact.
4. **Application Wiring:** Active application configuration in [`.env`](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/.env) retains PostgreSQL as its primary database URL.

### 4.2 External Projects Container Preservation
All 9 external project containers on the host were audited before and after Phase 2 execution. Zero external containers were stopped, restarted, or interrupted:

| Container Name | Image | Port | Status | Preservation Check |
|---|---|---|---|---|
| `apm-platform-backend-1` | `apm-platform-backend` | `8001:8000` | Up (healthy) | **Preserved** |
| `apm-platform-mqtt-consumer-1` | `apm-platform-mqtt-consumer` | `8000` | Up (healthy) | **Preserved** |
| `apm-platform-frontend-1` | `apm-platform-frontend` | `8080:8080` | Up (healthy) | **Preserved** |
| `apm-platform-simulator-1` | `apm-platform-simulator` | - | Up | **Preserved** |
| `apm-platform-mosquitto-1` | `eclipse-mosquitto:2` | `1883, 9001` | Up (healthy) | **Preserved** |
| `apm-platform-postgres-1` | `postgres:16-alpine` | `5435:5432` | Up (healthy) | **Preserved** |
| `apm-platform-ml-service-1` | `apm-platform-ml-service` | `8100:8100` | Up (healthy) | **Preserved** |
| `apm-platform-redis-1` | `redis:7-alpine` | `6379` | Up (healthy) | **Preserved** |
| `caleido-wellness-pg2` | `postgres:16-alpine` | `5433:5432` | Up | **Preserved** |

### 4.3 Git Working Tree & Modifications Audit
- Current Branch: `feature/changes-login`
- No commits were created; no changes were staged or pushed.
- All original 7 user modifications identified in Phase 1 remain strictly preserved:
  - [`apps/web/nginx/15-cortex-config.envsh`](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/apps/web/nginx/15-cortex-config.envsh)
  - [`apps/web/src/components/domain.tsx`](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/apps/web/src/components/domain.tsx)
  - [`infra/keycloak/generate_realm.py`](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/infra/keycloak/generate_realm.py)
  - [`infra/keycloak/realm-cortex.json`](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/infra/keycloak/realm-cortex.json)
  - [`infra/minio-init/init.sh`](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/infra/minio-init/init.sh)
  - [`infra/postgres/archive-wal.sh`](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/infra/postgres/archive-wal.sh)
  - [`make.ps1`](file:///<home>/OneDrive%20-%20Inspironics%20India/Insp%20Total%20Work/cortex/Capital_Cortex/make.ps1)
- Additional working-tree user edits in `platform_core` and `cortex` were left untouched.

---

## 5. Summary Checklist & Phase 2 Gate Verdict

| Verification Item | Requirement | Observed Result | Status |
|---|---|---|---|
| Independent Compose File | Create `infra/docker-compose.mysql-test.yml` | Created with project isolation `capital-cortex-mysql-test` | **PASS** |
| MySQL Image Tag | Pinned MySQL 8.4 Community | `mysql:8.4` (`8.4.13`) | **PASS** |
| Host Port Isolation | Port `53306` mapped to `3306` | Bound to `127.0.0.1:53306` (No conflict with active 5432-5435, 8000-8100) | **PASS** |
| Dedicated Volume | Named `capital-cortex_mysql_test_data` | Created independently; zero overlap with `capital-cortex_pgdata` | **PASS** |
| Credentials Safety | Excluded from tracked git files | Managed via local `.env` (in `.gitignore`) | **PASS** |
| Health Check | Automated ping readiness | `mysqladmin ping` reports container healthy | **PASS** |
| Port Connectivity | Host port `53306` accessible | `Test-NetConnection` and socket handshake pass | **PASS** |
| Test DB Exists | Database `cortex` initialized | Verified via SQL `SHOW DATABASES` | **PASS** |
| PostgreSQL Unmodified | `capital-cortex_pgdata` volume untouched | Verified via `docker volume inspect` | **PASS** |
| Other Containers Safe | External containers unaffected | All 9 host containers kept running with continuous uptime | **PASS** |
| Git Safety | Working tree preserved, no commits | Uncommitted user files intact | **PASS** |

### Phase 2 Gate Verdict
**`PHASE 2 PASSED — ISOLATED TEST ENVIRONMENT OPERATIONAL`**

*Per the completion gate rules, execution has stopped. No application-code changes, driver upgrades, Keycloak modifications, or production migrations will be executed without explicit user authorization for Phase 3.*
