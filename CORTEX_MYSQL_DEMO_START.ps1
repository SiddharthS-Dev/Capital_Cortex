<#
.SYNOPSIS
  Start the Capital Cortex MySQL 8.4 demo: isolated MySQL + Keycloak + OPA + Redis in Docker, and the API,
  worker and web app natively from this repo.

.DESCRIPTION
  Safe to run repeatedly. It never deletes containers, volumes, databases or rows:
    - starts docker-compose.mysql-test.yml (mysql-test only) and docker-compose.mysql-demo.yml
    - creates database cortex_demo only if it does not exist, applies `alembic -n mysql upgrade head`
      (idempotent), and seeds synthetic demo data only when the opportunity table is empty
    - starts the API (8300), worker and web (5373) only if they are not already running
  Production PostgreSQL and its volumes are never used.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\CORTEX_MYSQL_DEMO_START.ps1
  powershell -ExecutionPolicy Bypass -File .\CORTEX_MYSQL_DEMO_START.ps1 -Verify
#>
param(
  [int]$SeedOpportunities = 200,
  [switch]$Verify,   # run scripts/smoke.py at the end (its last step needs Grafana/Tempo, which this demo does not run)
  [switch]$NoWeb,
  [switch]$NoWorker,
  [switch]$AllowLowDisk   # continue (with a warning) when C: has less than 1 GB free
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$LogDir = Join-Path $env:TEMP "capital-cortex-demo"
New-Item -ItemType Directory -Force $LogDir | Out-Null

function Step([string]$m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Ok([string]$m) { Write-Host "    [ok]   $m" -ForegroundColor Green }
function Warn([string]$m) { Write-Host "    [warn] $m" -ForegroundColor Yellow }
function Die([string]$m) { Write-Host "    [FAIL] $m" -ForegroundColor Red; exit 1 }

# Runs a native command, echoing its output to the console, and returns ONLY its exit code.
# (Native tools write progress to stderr; PowerShell 5.1 must not treat that as a terminating error.)
function Native([string]$exe, [string[]]$argv) {
  $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
  try { & $exe @argv 2>&1 | ForEach-Object { Write-Host "      $_" } } finally { $ErrorActionPreference = $prev }
  return $LASTEXITCODE
}

function PortOpen([int]$port) {
  $c = New-Object System.Net.Sockets.TcpClient
  try { $ar = $c.BeginConnect("127.0.0.1", $port, $null, $null); return ($ar.AsyncWaitHandle.WaitOne(800) -and $c.Connected) }
  catch { return $false } finally { $c.Close() }
}

function WaitHttp([string]$url, [int]$seconds) {
  $deadline = (Get-Date).AddSeconds($seconds)
  while ((Get-Date) -lt $deadline) {
    try { $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5; if ($r.StatusCode -lt 500) { return $true } } catch {}
    Start-Sleep -Seconds 2
  }
  return $false
}

# ---------------------------------------------------------------------------------------------- prerequisites
Step "Checking prerequisites"
if (-not (Test-Path $Py)) { Die "Python venv not found at $Py (create it: .\make.ps1 venv)" }
if (-not (Test-Path (Join-Path $Root ".env"))) { Die ".env not found (copy .env.example to .env)" }
if (-not $NoWeb -and -not (Test-Path (Join-Path $Root "apps\web\node_modules"))) { Die "apps\web\node_modules missing (cd apps\web; npm ci)" }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Die "docker CLI not found" }
if ((Native "docker" @("info", "--format", "{{.ServerVersion}}")) -ne 0) { Die "Docker daemon not reachable - start Docker Desktop and wait until it is running" }
Ok "Docker daemon reachable"
$free = [math]::Round((Get-PSDrive C).Free / 1GB, 1)
if ($free -lt 1 -and -not $AllowLowDisk) { Die "Only $free GB free on C: - MySQL/Keycloak may crash. Free space, or rerun with -AllowLowDisk to accept the risk." }
elseif ($free -lt 1) { Warn "Only $free GB free on C: - continuing because -AllowLowDisk was given; Docker Desktop may stop if its disk must grow" }
elseif ($free -lt 3) { Warn "Only $free GB free on C: (Docker Desktop stopped containers earlier when the disk was full)" }
else { Ok "$free GB free on C:" }

# .env values (never printed)
$EnvVals = @{}
Get-Content (Join-Path $Root ".env") | Where-Object { $_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$' } | ForEach-Object {
  $EnvVals[$Matches[1]] = $Matches[2].Trim('"')
}
function EnvOr([string]$k, [string]$d) { if ($EnvVals.ContainsKey($k) -and $EnvVals[$k]) { return $EnvVals[$k] } return $d }
$MyPort = EnvOr "MYSQL_TEST_PORT" "53306"
$MyUser = EnvOr "MYSQL_TEST_USER" "cortex"
$MyPw = EnvOr "MYSQL_TEST_PASSWORD" ""
$MyRootPw = EnvOr "MYSQL_TEST_ROOT_PASSWORD" ""
if (-not $MyPw -or -not $MyRootPw) { Die "Set MYSQL_TEST_PASSWORD and MYSQL_TEST_ROOT_PASSWORD in .env (no committed defaults)" }
$Mfa = EnvOr "CORTEX_MFA_REQUIRED" "true"

# ---------------------------------------------------------------------------------------------- containers
Step "Starting isolated MySQL 8.4 (capital-cortex-mysql-test, 127.0.0.1:$MyPort)"
if ((Native "docker" @("compose", "--env-file", ".env", "-f", "infra/docker-compose.mysql-test.yml", "up", "-d", "--wait", "mysql-test")) -ne 0) {
  Die "MySQL did not start: docker logs capital-cortex-mysql-test"
}
Ok "MySQL healthy"

$kcTest = (& docker ps --filter "name=^capital-cortex-keycloak-test$" --format "{{.Names}}" 2>$null)
if ($kcTest) { Warn "capital-cortex-keycloak-test is running and shares the keycloak database; stop it: docker stop capital-cortex-keycloak-test" }

Step "Starting Keycloak (8380), OPA (8381), Redis (56379)"
if ((Native "docker" @("compose", "--env-file", ".env", "-f", "infra/docker-compose.mysql-demo.yml", "up", "-d", "--wait")) -ne 0) {
  Die "Demo services did not become healthy: docker compose -f infra/docker-compose.mysql-demo.yml ps"
}
Ok "Keycloak, OPA and Redis healthy"

# ---------------------------------------------------------------------------------------------- database
Step "Preparing database cortex_demo"
$env:CORTEX_DEMO_MY_PORT = $MyPort; $env:CORTEX_DEMO_MY_USER = $MyUser
$env:CORTEX_DEMO_MY_PW = $MyPw; $env:CORTEX_DEMO_MY_ROOTPW = $MyRootPw
$dbPrep = @'
import os, pymysql
port, user = int(os.environ["CORTEX_DEMO_MY_PORT"]), os.environ["CORTEX_DEMO_MY_USER"]
root = pymysql.connect(host="127.0.0.1", port=port, user="root", password=os.environ["CORTEX_DEMO_MY_ROOTPW"])
with root.cursor() as cur:
    cur.execute("CREATE DATABASE IF NOT EXISTS cortex_demo CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci")
    cur.execute(f"GRANT ALL PRIVILEGES ON cortex_demo.* TO '{user}'@'%'")
print("cortex_demo present")
'@
$dbPrep | & $Py -
if ($LASTEXITCODE -ne 0) { Die "Could not reach MySQL as root on port $MyPort" }
Remove-Item Env:CORTEX_DEMO_MY_ROOTPW

$enc = [uri]::EscapeDataString($MyPw)
$env:DATABASE_URL = "mysql+asyncmy://${MyUser}:$enc@127.0.0.1:$MyPort/cortex_demo"
$env:REDIS_URL = "redis://localhost:56379/0"
$env:OPA_URL = "http://localhost:8381"
$env:OIDC_ISSUER = "http://localhost:8380/realms/cortex"
$env:OIDC_JWKS_URL = "http://localhost:8380/realms/cortex/protocol/openid-connect/certs"
$env:OIDC_TOKEN_URL = "http://localhost:8380/realms/cortex/protocol/openid-connect/token"
$env:KEYCLOAK_ADMIN_URL = "http://localhost:8380"
$env:OIDC_ENFORCE_MFA = $Mfa            # mirrors CORTEX_MFA_REQUIRED from .env (OPA reads the same value)
$env:DEMO_MODE = "true"                 # show the synthetic, is_demo-flagged dataset
$env:LLM_ROUTER = "@$Root\config\llm_router.json"
$env:FEATURE_BUDGETS = "@$Root\config\feature_budgets.json"
$env:PYTHONUTF8 = "1"

if ((Native $Py @("-m", "alembic", "-n", "mysql", "upgrade", "head")) -ne 0) { Die "MySQL schema migration failed" }
Ok "Schema at MySQL history head (alembic -n mysql)"

$countPy = @'
import os, pymysql
c = pymysql.connect(host="127.0.0.1", port=int(os.environ["CORTEX_DEMO_MY_PORT"]), user=os.environ["CORTEX_DEMO_MY_USER"],
                    password=os.environ["CORTEX_DEMO_MY_PW"], database="cortex_demo")
with c.cursor() as cur:
    cur.execute("SELECT COUNT(*) FROM opportunity")
    print(cur.fetchone()[0])
'@
$count = ($countPy | & $Py -)
if ($LASTEXITCODE -ne 0) { Die "Could not query cortex_demo" }
Remove-Item Env:CORTEX_DEMO_MY_PW
if ([int]$count -eq 0) {
  Step "Seeding synthetic demo data ($SeedOpportunities opportunities, seed 7; takes ~4-5 min)"
  if ((Native $Py @("-m", "seed.generate", "--opportunities", "$SeedOpportunities", "--seed", "7")) -ne 0) { Die "Seeding failed" }
  Ok "Demo data seeded"
} else { Ok "Demo data already present ($count opportunities) - not reseeding" }

# ---------------------------------------------------------------------------------------------- app processes
function StartProc([string]$name, [string]$exe, [string]$argList, [string]$cwd) {
  $out = Join-Path $LogDir "$name.log"; $err = Join-Path $LogDir "$name.err.log"
  $p = Start-Process -FilePath $exe -ArgumentList $argList -WorkingDirectory $cwd -RedirectStandardOutput $out `
       -RedirectStandardError $err -WindowStyle Hidden -PassThru
  Set-Content -Path (Join-Path $LogDir "$name.pid") -Value $p.Id
}

Step "API (http://localhost:8300)"
if (PortOpen 8300) { Ok "already running on 8300" }
else {
  StartProc "api" $Py "-m uvicorn cortex.l8_actuation.api.app:app --host 127.0.0.1 --port 8300" $Root
  if (-not (WaitHttp "http://127.0.0.1:8300/readyz" 90)) { Die "API not ready - see $LogDir\api.err.log" }
  Ok "started"
}
$ready = Invoke-WebRequest -Uri "http://127.0.0.1:8300/readyz" -UseBasicParsing -TimeoutSec 10
Ok "/readyz -> $($ready.StatusCode) $($ready.Content)"

if (-not $NoWorker) {
  Step "Worker (bus consumer + scheduler)"
  if (PortOpen 9465) { Ok "already running (metrics port 9465)" }
  else {
    $env:METRICS_PORT = "9465"
    StartProc "worker" $Py "-m cortex.worker" $Root
    Remove-Item Env:METRICS_PORT
    # The worker opens its metrics port only after connecting to Redis and MySQL; allow for a cold start.
    $deadline = (Get-Date).AddSeconds(45)
    while (-not (PortOpen 9465) -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 2 }
    if (PortOpen 9465) { Ok "started" } else { Warn "worker not confirmed after 45 s - see $LogDir\worker.err.log" }
  }
}

if (-not $NoWeb) {
  Step "Web app (http://localhost:5373)"
  if (PortOpen 5373) { Ok "already running on 5373" }
  else {
    StartProc "web" "npx.cmd" "vite --port 5373 --strictPort --host 127.0.0.1" (Join-Path $Root "apps\web")
    if (-not (WaitHttp "http://127.0.0.1:5373/" 90)) { Die "web not up - see $LogDir\web.err.log" }
    Ok "started"
  }
}

if ($Verify) {
  Step "Smoke test (scripts/smoke.py)"
  $prev = $ErrorActionPreference; $ErrorActionPreference = "Continue"
  try {
    & $Py "scripts/smoke.py" 2>&1 | ForEach-Object { "$_" } | Where-Object { $_ -match '\[(PASS|FAIL)\]|SMOKE OK' } |
      ForEach-Object { Write-Host "      $_" }
  } finally { $ErrorActionPreference = $prev }
  Warn "The smoke script's last step (Grafana/Tempo traces) cannot run here: observability is not part of this demo"
}

# ---------------------------------------------------------------------------------------------- summary
Write-Host ""
Write-Host "Capital Cortex MySQL demo is up." -ForegroundColor Green
Write-Host "  Web app        http://localhost:5373"
Write-Host "  API docs       http://localhost:8300/v1/docs   (health: /healthz, /readyz)"
Write-Host "  Keycloak       http://localhost:8380   (realm cortex; dev users in docs/RUNBOOK.md section 2)"
Write-Host "  OPA            http://localhost:8381"
Write-Host "  MySQL          127.0.0.1:$MyPort  database cortex_demo"
Write-Host "  Logs           $LogDir"
Write-Host ""
Write-Host "Troubleshooting:" -ForegroundColor Cyan
Write-Host "  API errors      Get-Content $LogDir\api.err.log -Tail 50"
Write-Host "  Containers      docker compose -f infra/docker-compose.mysql-demo.yml ps"
Write-Host "  Login loop      Keycloak must be on 8380; stop capital-cortex-keycloak-test if it is running"
Write-Host "  Stop (no data loss)  Stop-Process -Id (Get-Content $LogDir\api.pid),(Get-Content $LogDir\worker.pid)"
Write-Host "                       docker compose -f infra/docker-compose.mysql-demo.yml stop"
