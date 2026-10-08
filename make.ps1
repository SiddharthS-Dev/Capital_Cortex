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

$Compose = @("compose", "-f", "infra/docker-compose.yml")
if ($env:CORTEX_PROFILE -ne "prod") { $Compose += @("-f", "infra/docker-compose.dev.yml") }  # mount source for dev
if (Test-Path ".env") { $Compose += @("--env-file", ".env") }  # repo-root .env (Compose defaults to infra/.env)
$Py = ".venv/Scripts/python.exe"
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
    "test-contract test-web test-e2e opa-test eval load backup restore-drill scan lint fmt openapi traceability smoke ci"
  }
  "venv" {
    Run "python" @("-m", "venv", ".venv"); Run $Py @("-m", "pip", "install", "-U", "pip")
    Run $Py @("-m", "pip", "install", "-e", ".[dev]"); Push-Location apps/web; Run "npm" @("ci"); Pop-Location
  }
  "up" {
    Run $Py @("scripts/check_env.py")
    Run "docker" ($Compose + @("up", "-d", "--build", "--wait", "postgres", "redis", "minio", "keycloak", "opa", "vault",
        "otel-collector", "tempo", "loki", "prometheus", "grafana"))
    Run "docker" ($Compose + @("up", "-d", "--build", "mailpit", "minio-init", "migrate", "api", "worker", "web"))
    Run $Py @("scripts/bootstrap_admin.py")
    "UI http://localhost:3300 | API http://localhost:8300/v1/docs | Keycloak http://localhost:8380 | Grafana http://localhost:3301"
  }
  "down" { Run "docker" ($Compose + @("down")) }
  "clean" { Run "docker" ($Compose + @("down", "-v")) }
  "ps" { Run "docker" ($Compose + @("ps", "-a")) }
  "logs" { Run "docker" ($Compose + @("logs", "-f", "api", "worker")) }
  "build" { Run "docker" ($Compose + @("build")) }
  "migrate" { Run "docker" ($Compose + @("run", "--rm", "migrate")) }
  "realm" { Run $Py @("infra/keycloak/generate_realm.py") }
  "seed" { Run "docker" ($Compose + @("run", "--rm", "migrate", "python", "-m", "seed.generate")) }
  "purge-demo" { Run "docker" ($Compose + @("run", "--rm", "migrate", "python", "-m", "seed.purge")) }
  "test-unit" { Run $Py @("-m", "pytest", "-q") }
  "test-integration" {
    Run "docker" @("build", "-q", "-t", $PgImage, "infra/postgres")
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
  "load" { $env:PYTHONUTF8 = "1"; Run $Py @("scripts/load_test.py") }  # 1M-node seed + k6 (tests/load/README.md)
  "backup" {
    Run "docker" ($Compose + @("up", "-d", "--no-deps", "wal-shipper"))
    $env:PYTHONUTF8 = "1"; Run $Py @("scripts/backup.py")
  }
  "restore-drill" { $env:PYTHONUTF8 = "1"; Run $Py @("scripts/restore_drill.py") }
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
