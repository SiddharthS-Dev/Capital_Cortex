# Capital Cortex — developer entrypoints. On Windows without GNU make: `./make.ps1 <target>`.
# Compose would look for .env next to the compose file; use the repo-root .env when present.
# MySQL 8.4 is the default stack. PostgreSQL is reachable only through the *-postgres targets (rollback window).
DEV_OVERLAY := $(if $(filter prod,$(CORTEX_PROFILE)),,-f infra/docker-compose.dev.yml)
COMPOSE := docker compose -f infra/docker-compose.yml -f infra/docker-compose.mysql.yml $(DEV_OVERLAY) $(if $(wildcard .env),--env-file .env)
PG_COMPOSE := docker compose --profile postgres-rollback -f infra/docker-compose.yml $(DEV_OVERLAY) $(if $(wildcard .env),--env-file .env)
ifeq ($(OS),Windows_NT)
  PY ?= .venv/Scripts/python
else
  PY ?= .venv/bin/python
endif
WEB := apps/web
PG_IMAGE := capital-cortex/postgres:16-age1.5.0-pgvector0.8.0

.PHONY: help venv up down clean ps logs build migrate seed purge-demo test test-unit test-integration contract-live \
        test-contract test-e2e test-web opa-test eval load lint fmt typecheck openapi traceability smoke realm ci \
        backup restore-drill mysql-backup mysql-backup-verify mysql-backup-prune scan \
        up-postgres down-postgres migrate-postgres backup-postgres restore-drill-postgres load-postgres

help:  ## list targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

venv:  ## create .venv and install backend + dev deps
	python -m venv .venv && $(PY) -m pip install -U pip && $(PY) -m pip install -e ".[dev]"
	cd $(WEB) && npm ci

up:  ## build and start the full MySQL 8.4 stack (waits for health)
	$(COMPOSE) up -d --build --wait mysql redis minio keycloak opa vault otel-collector tempo loki prometheus grafana
	$(COMPOSE) up -d --build mailpit minio-init migrate api worker web
	$(PY) scripts/bootstrap_admin.py
	@echo "UI http://localhost:3300 · API http://localhost:8300/v1/docs · Keycloak http://localhost:8380 · Grafana http://localhost:3301 · Mailpit http://localhost:8383"

down:  ## stop the stack (keeps volumes)
	$(COMPOSE) down

clean:  ## stop the stack and DELETE its volumes, including the MySQL data (requires CONFIRM=yes)
	@test "$(CONFIRM)" = "yes" || { echo "clean deletes the database volumes; re-run with CONFIRM=yes"; exit 1; }
	$(COMPOSE) down -v

ps:
	$(COMPOSE) ps -a

logs:  ## follow app logs
	$(COMPOSE) logs -f api worker

build:  ## build all images
	$(COMPOSE) build

migrate:  ## apply the MySQL migration history in the stack (alembic upgrade head)
	$(COMPOSE) run --rm migrate

realm:  ## regenerate the dev Keycloak realm export
	$(PY) infra/keycloak/generate_realm.py

seed:  ## load the synthetic demo dataset (is_demo, fictional names; shows the DEMO ribbon)
	$(COMPOSE) run --rm migrate python -m seed.generate

purge-demo:  ## remove every is_demo row and demo graph vertex
	$(COMPOSE) run --rm migrate python -m seed.purge

test: test-unit opa-test test-web  ## unit + policy + web unit tests (no Docker needed except for OPA)

test-unit:
	$(PY) -m pytest -q

test-integration:  ## schema/invariant tests on MySQL 8.4
	$(PY) -m pytest -q -m integration tests/integration

contract-live:  ## schemathesis, read-only (GET), against the running stack with a real token
	$(PY) scripts/contract_live.py

test-contract:  ## schemathesis against the OpenAPI contract
	$(PY) -m pytest -q -m contract tests/contract

test-web:
	cd $(WEB) && npx vitest run

test-e2e:  ## Playwright against the running stack (make up first)
	cd $(WEB) && npx playwright test

opa-test:  ## Rego unit tests
	docker run --rm -v "$(CURDIR)/config/policies:/policies:ro" openpolicyagent/opa:0.70.0 test /policies -v

eval:  ## eval gates (fails on any gate enforceable in the current phase)
	$(PY) evals/run.py

load:  ## not available on MySQL yet: use scripts/benchmark_mysql_slos.py
	@echo "The k6 load test seeds PostgreSQL only. For MySQL use scripts/benchmark_mysql_slos.py; for the old stack: make load-postgres"; exit 1

load-postgres:  ## ROLLBACK STACK: k6 load test on PostgreSQL (tests/load)
	PYTHONUTF8=1 $(PY) scripts/load_test.py

backup: mysql-backup  ## encrypted MySQL backup (same as mysql-backup)

backup-postgres:  ## ROLLBACK STACK: PostgreSQL base backup + logical dumps to MinIO (RUNBOOK section 8)
	$(PG_COMPOSE) up -d --no-deps wal-shipper
	PYTHONUTF8=1 $(PY) scripts/backup.py

restore-drill:  ## show the MySQL restore-drill command
	@echo "scripts/backup_mysql.py restore --id <id> --database cortex --target-db cortex_restore_drill --strict"

restore-drill-postgres:  ## ROLLBACK STACK: restore the latest PostgreSQL backup into a scratch server
	PYTHONUTF8=1 $(PY) scripts/restore_drill.py

# ---- PostgreSQL database only (the source for the ETL). The current application is MySQL-only: a rollback checks out the
# pinned release f2c447a and uses that release's own `make up` (docs/CORTEX_MYSQL_ROLLBACK_RUNBOOK.md).
up-postgres:  ## start only the PostgreSQL database (ETL source)
	$(PG_COMPOSE) up -d --build --wait postgres

down-postgres:  ## ROLLBACK STACK: stop it (keeps volumes)
	$(PG_COMPOSE) down

migrate-postgres:  ## ROLLBACK STACK: apply the PostgreSQL migration history
	$(PG_COMPOSE) run --rm migrate

mysql-backup:  ## MySQL 8.4: encrypted mysqldump (cortex, keycloak) to MYSQL_BACKUP_DEST, manifest last, verified
	PYTHONUTF8=1 $(PY) scripts/backup_mysql.py backup

mysql-backup-verify:  ## re-read the newest MySQL backup: ciphertext + plaintext sha256, every GCM frame
	PYTHONUTF8=1 $(PY) scripts/backup_mysql.py verify

mysql-backup-prune:  ## retention DRY RUN (MYSQL_BACKUP_KEEP); delete only with: scripts/backup_mysql.py prune --confirm
	PYTHONUTF8=1 $(PY) scripts/backup_mysql.py prune

scan:  ## trivy (images + dependencies) + ZAP baseline (UI) + ZAP API scan (safe mode); docs/SECURITY_SCAN.md
	PYTHONUTF8=1 $(PY) scripts/scan.py

lint:  ## ruff + import-linter + mypy + eslint + tsc
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .
	.venv/$(if $(filter Windows_NT,$(OS)),Scripts,bin)/lint-imports
	$(PY) -m mypy
	cd $(WEB) && npx eslint . && npx tsc -b --noEmit

fmt:
	$(PY) -m ruff format . && $(PY) -m ruff check --fix .

openapi:  ## regenerate docs/openapi.json
	$(PY) scripts/export_openapi.py

traceability:  ## check + render docs/traceability.md
	$(PY) scripts/check_traceability.py --write-md

smoke:  ## end-to-end smoke against the running stack (MFA login, audit verify, bus, traces)
	$(PY) scripts/smoke.py

ci: lint test test-contract test-integration eval  ## everything CI runs before build/scan
