<#
.SYNOPSIS
  Windows equivalent of the Makefile (for machines without GNU make).
.EXAMPLE
  ./make.ps1 up
  ./make.ps1 test
#>
param([Parameter(Position = 0)][string]$Target = "help")
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# MySQL 8.4 is the default stack. Needs MYSQL_ROOT_PASSWORD / MYSQL_PASSWORD / MINIO_* in .env (no defaults).
# PostgreSQL is reachable only through the *-postgres targets (rollback window, pinned release f2c447a).
$Compose = @("compose", "-f", "infra/docker-compose.yml", "-f", "infra/docker-compose.mysql.yml")
$PgCompose = @("compose", "--profile", "postgres-rollback", "-f", "infra/docker-compose.yml")
if ($env:CORTEX_PROFILE -ne "prod") { $Compose += @("-f", "infra/docker-compose.dev.yml"); $PgCompose += @("-f", "infra/docker-compose.dev.yml") }  # mount source for dev
if (Test-Path ".env") { $Compose += @("--env-file", ".env"); $PgCompose += @("--env-file", ".env") }  # repo-root .env (Compose defaults to infra/.env)
$Py = if (Test-Path ".venv/Scripts/python.exe") { ".venv/Scripts/python.exe" } else { "python" }
$PgImage = "capital-cortex/postgres:16-age1.5.0-pgvector0.8.0"

function Run([string]$exe, [string[]]$argv) {
  # Native tools (docker, npm) write progress to stderr; in Windows PowerShell 5.1 that becomes an error
  # record under "Stop", so rely on the exit code instead.
  $prev = $ErrorActionPreference
  $ErrorActionPreference = "Continue"
  try { & $exe @argv 2>&1 | ForEach-Object { "$_" } } finally { $ErrorActionPreference = $prev }
  if ($LASTEXITCODE -ne 0) { throw "$exe $($argv -join ' ') failed with exit code $LASTEXITCODE" }
}
function Web([string[]]$argv) { Push-Location apps/web; try { Run "npx" $argv } finally { Pop-Location } }

switch ($Target) {
  "help" {
    "Targets: venv up down clean ps logs build migrate realm seed purge-demo test test-unit test-integration " +
    "test-contract test-web test-e2e opa-test eval load backup restore-drill mysql-backup mysql-backup-verify " +
    "mysql-backup-prune up-mysql down-mysql ps-mysql migrate-mysql up-postgres down-postgres migrate-postgres " +
    "backup-postgres restore-drill-postgres load-postgres scan lint fmt openapi traceability smoke ci"
  }
  "venv" {
    Run "python" @("-m", "venv", ".venv"); Run $Py @("-m", "pip", "install", "-U", "pip")
    Run $Py @("-m", "pip", "install", "-e", ".[dev]"); Push-Location apps/web; Run "npm" @("ci"); Pop-Location
  }
  "up" {
    Run "docker" ($Compose + @("up", "-d", "--build", "--wait", "mysql", "redis", "minio", "keycloak", "opa", "vault",
        "otel-collector", "tempo", "loki", "prometheus", "grafana"))
    Run "docker" ($Compose + @("up", "-d", "--build", "mailpit", "minio-init", "migrate", "api", "worker", "web"))
    Run $Py @("scripts/bootstrap_admin.py")
    "UI http://localhost:3300 | API http://localhost:8300/v1/docs | Keycloak http://localhost:8380 | Grafana http://localhost:3301"
  }
  "down" { Run "docker" ($Compose + @("down")) }
  # Older names for the default stack, kept so existing notes keep working.
  "up-mysql" { & $PSCommandPath up }
  "down-mysql" { Run "docker" ($Compose + @("down")) }  # never -v: mysqldata holds the database
  "ps-mysql" { Run "docker" ($Compose + @("ps", "-a")) }
  "migrate-mysql" { Run "docker" ($Compose + @("run", "--rm", "migrate")) }
  # PostgreSQL database only (the ETL source). The current application is MySQL-only: a rollback checks out the pinned
  # release f2c447a and uses that release's own `up` (docs/CORTEX_MYSQL_ROLLBACK_RUNBOOK.md).
  "up-postgres" { Run "docker" ($PgCompose + @("up", "-d", "--build", "--wait", "postgres")) }
  "down-postgres" { Run "docker" ($PgCompose + @("down")) }
  "migrate-postgres" { Run "docker" ($PgCompose + @("run", "--rm", "migrate")) }
  "clean" {
    if ($env:CONFIRM -ne "yes") { throw "clean deletes the database volumes; set CONFIRM=yes to proceed" }
    Run "docker" ($Compose + @("down", "-v"))
  }
  "ps" { Run "docker" ($Compose + @("ps", "-a")) }
  "logs" { Run "docker" ($Compose + @("logs", "-f", "api", "worker")) }
  "build" { Run "docker" ($Compose + @("build")) }
  "migrate" { Run "docker" ($Compose + @("run", "--rm", "migrate")) }
  "realm" { Run $Py @("infra/keycloak/generate_realm.py") }
  "seed" { Run "docker" ($Compose + @("run", "--rm", "migrate", "python", "-m", "seed.generate")) }
  "purge-demo" { Run "docker" ($Compose + @("run", "--rm", "migrate", "python", "-m", "seed.purge")) }
  "test-unit" { Run $Py @("-m", "pytest", "-q") }
  "test-integration" {
    Run $Py @("-m", "pytest", "-q", "-m", "integration", "tests/integration")
  }
  "test-contract" { Run $Py @("-m", "pytest", "-q", "-m", "contract", "tests/contract") }
  "contract-live" { Run $Py @("scripts/contract_live.py") }
  "test-web" { Web @("vitest", "run") }
  "test-e2e" { Web @("playwright", "test") }
  "opa-test" {
    $pol = (Resolve-Path "config/policies").Path
    Run "docker" @("run", "--rm", "-v", "${pol}:/policies:ro", "openpolicyagent/opa:0.70.0", "test", "/policies", "-v")
  }
  "test" { & $PSCommandPath test-unit; & $PSCommandPath opa-test; & $PSCommandPath test-web }
  "eval" { Run $Py @("evals/run.py") }
  "load" { throw "The k6 load test seeds PostgreSQL only. For MySQL use scripts/benchmark_mysql_slos.py; old stack: load-postgres" }
  "load-postgres" { $env:PYTHONUTF8 = "1"; Run $Py @("scripts/load_test.py") }  # 1M-node seed + k6 (tests/load/README.md)
  "backup" { & $PSCommandPath mysql-backup }
  "backup-postgres" {
    Run "docker" ($PgCompose + @("up", "-d", "--no-deps", "wal-shipper"))
    $env:PYTHONUTF8 = "1"; Run $Py @("scripts/backup.py")
  }
  "restore-drill" { "scripts/backup_mysql.py restore --id <id> --database cortex --target-db cortex_restore_drill --strict" }
  "restore-drill-postgres" { $env:PYTHONUTF8 = "1"; Run $Py @("scripts/restore_drill.py") }
  # MySQL 8.4: encrypted logical backup to MYSQL_BACKUP_DEST (see .env.example, CORTEX_MYSQL_CUTOVER_RUNBOOK.md).
  # Schedule nightly, e.g. schtasks /Create /SC DAILY /ST 02:30 /TN "Capital Cortex MySQL backup" /TR "powershell
  # -NoProfile -ExecutionPolicy Bypass -File <repo>\make.ps1 mysql-backup"; Linux cron: 30 2 * * * make mysql-backup.
  "mysql-backup" { $env:PYTHONUTF8 = "1"; Run $Py @("scripts/backup_mysql.py", "backup") }
  "mysql-backup-verify" { $env:PYTHONUTF8 = "1"; Run $Py @("scripts/backup_mysql.py", "verify") }
  # Retention is a dry run here; deleting needs an explicit: python scripts/backup_mysql.py prune --confirm
  "mysql-backup-prune" { $env:PYTHONUTF8 = "1"; Run $Py @("scripts/backup_mysql.py", "prune") }
  "scan" { $env:PYTHONUTF8 = "1"; Run $Py @("scripts/scan.py") }
  "lint" {
    Run $Py @("-m", "ruff", "check", "."); Run $Py @("-m", "ruff", "format", "--check", ".")
    Run ".venv/Scripts/lint-imports.exe" @(); Run $Py @("-m", "mypy")
    Web @("eslint", "."); Web @("tsc", "-b", "--noEmit")
  }
  "fmt" { Run $Py @("-m", "ruff", "format", "."); Run $Py @("-m", "ruff", "check", "--fix", ".") }
  "openapi" { Run $Py @("scripts/export_openapi.py") }
  "traceability" { Run $Py @("scripts/check_traceability.py", "--write-md") }
  "smoke" { Run $Py @("scripts/smoke.py") }
  "ci" { foreach ($t in "lint", "test", "test-contract", "test-integration", "eval") { & $PSCommandPath $t } }
  default { throw "unknown target '$Target' (./make.ps1 help)" }
}
