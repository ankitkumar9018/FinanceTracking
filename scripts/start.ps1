# =============================================================================
# FinanceTracker — Start Script (Windows PowerShell)
# Checks prerequisites, installs dependencies, stops existing services, starts all
# =============================================================================

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BackendDir = Join-Path $ProjectDir "backend"
$WebDir = Join-Path $ProjectDir "apps\web"
$LogsDir = Join-Path $ProjectDir "logs"

Write-Host "======================================================" -ForegroundColor Blue
Write-Host "  FinanceTracker - Setup & Launch" -ForegroundColor Blue
Write-Host "======================================================" -ForegroundColor Blue
Write-Host ""

# ── Step 1: Check Prerequisites ──────────────────────────────────────────────

Write-Host "[1/6] Checking prerequisites..." -ForegroundColor Yellow

# Python
try {
    $pyVer = python --version 2>&1
    Write-Host "  [OK] $pyVer" -ForegroundColor Green
} catch {
    Write-Host "  [FAIL] Python 3.12+ not found" -ForegroundColor Red
    Write-Host "  Download from https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
}

# uv
try {
    $uvVer = uv --version 2>&1
    Write-Host "  [OK] $uvVer" -ForegroundColor Green
} catch {
    Write-Host "  Installing uv..." -ForegroundColor Yellow
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
}

# Node.js
try {
    $nodeVer = node --version 2>&1
    Write-Host "  [OK] Node.js $nodeVer" -ForegroundColor Green
} catch {
    Write-Host "  [FAIL] Node.js 20+ not found" -ForegroundColor Red
    exit 1
}

# pnpm
try {
    $pnpmVer = pnpm --version 2>&1
    Write-Host "  [OK] pnpm $pnpmVer" -ForegroundColor Green
} catch {
    Write-Host "  Installing pnpm..." -ForegroundColor Yellow
    npm install -g pnpm
}

# Redis (optional)
$hasRedis = $false
try {
    $redisPing = redis-cli ping 2>&1
    if ($redisPing -eq "PONG") {
        $hasRedis = $true
        Write-Host "  [OK] Redis available" -ForegroundColor Green
    } else { throw "no redis" }
} catch {
    Write-Host "  [WARN] Redis not found (using in-memory fallback)" -ForegroundColor Yellow
}

# Ollama (optional)
$hasOllama = $false
try {
    Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -TimeoutSec 2 -ErrorAction Stop | Out-Null
    $hasOllama = $true
    Write-Host "  [OK] Ollama available" -ForegroundColor Green
} catch {
    Write-Host "  [WARN] Ollama not found (AI features disabled)" -ForegroundColor Yellow
}

# ── Step 2: Install Dependencies ─────────────────────────────────────────────

Write-Host ""
Write-Host "[2/6] Installing dependencies..." -ForegroundColor Yellow

Push-Location $BackendDir
uv sync 2>&1 | Select-Object -Last 1
Write-Host "  [OK] Backend dependencies installed" -ForegroundColor Green
Pop-Location

Push-Location $ProjectDir
if (Test-Path "pnpm-workspace.yaml") {
    pnpm install 2>&1 | Select-Object -Last 1
    Write-Host "  [OK] Frontend dependencies installed" -ForegroundColor Green
}
Pop-Location

# ── Step 3: Setup Database ───────────────────────────────────────────────────

Write-Host ""
Write-Host "[3/6] Setting up database..." -ForegroundColor Yellow

Push-Location $BackendDir
if ((-not (Test-Path ".env")) -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    # Generate a secret key
    $secretKey = -join ((1..32) | ForEach-Object { "{0:x2}" -f (Get-Random -Maximum 256) })
    (Get-Content ".env") -replace "^SECRET_KEY=.*", "SECRET_KEY=$secretKey" | Set-Content ".env"
    Write-Host "  [OK] Created .env from template" -ForegroundColor Green
}

if (Test-Path "alembic.ini") {
    uv run alembic upgrade head 2>&1 | Select-Object -Last 1
    Write-Host "  [OK] Database migrations applied" -ForegroundColor Green
}
Pop-Location

# ── Step 4: Stop Existing Services ───────────────────────────────────────────

Write-Host ""
Write-Host "[4/6] Stopping existing services..." -ForegroundColor Yellow

# Stop only OUR own previous run (via PID files) — never kill by port or by
# process name, so co-running apps (on 8000, 3000, other uvicorns, ...) are safe.
foreach ($svc in @("uvicorn", "celery", "nextjs", "backend", "frontend")) {
    $pf = Join-Path $LogsDir "$svc.pid"
    if (Test-Path $pf) {
        Stop-Process -Id (Get-Content $pf) -Force -ErrorAction SilentlyContinue
        Remove-Item $pf -Force -ErrorAction SilentlyContinue
    }
}
Write-Host "  [OK] Previous FinanceTracker instance stopped (other apps untouched)" -ForegroundColor Green

# Pick a free TCP port: try each preferred port, else an OS-assigned ephemeral one.
function Find-FreePort {
    param([int[]]$Preferred)
    foreach ($p in $Preferred) {
        try {
            $l = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $p)
            $l.Start(); $l.Stop(); return $p
        } catch { }
    }
    $l = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, 0)
    $l.Start(); $port = $l.LocalEndpoint.Port; $l.Stop(); return $port
}
$BackendPort  = Find-FreePort @(8420,8421,8422,8423,8424,8425,8426,8427,8428,8429)
$FrontendPort = Find-FreePort @(3000,3001,3002,3003,3004,3005)

# ── Step 5: Start Services ───────────────────────────────────────────────────

Write-Host ""
Write-Host "[5/6] Starting services..." -ForegroundColor Yellow

if (-not (Test-Path $LogsDir)) { New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null }
"$BackendPort"  | Set-Content (Join-Path $LogsDir "backend.port")
"$FrontendPort" | Set-Content (Join-Path $LogsDir "frontend.port")

# Backend — on the chosen port; CORS allows the chosen frontend origin
Push-Location $BackendDir
$env:CORS_ORIGINS = "http://localhost:$FrontendPort,http://localhost:3000,http://localhost:1420,https://tauri.localhost"
$backendProc = Start-Process -NoNewWindow -PassThru -FilePath "uv" `
    -ArgumentList "run uvicorn app.main:app --reload --host 127.0.0.1 --port $BackendPort" `
    -RedirectStandardOutput (Join-Path $LogsDir "backend.log") `
    -RedirectStandardError (Join-Path $LogsDir "backend-err.log")
$backendProc.Id | Set-Content (Join-Path $LogsDir "backend.pid")
Write-Host "  [OK] Backend starting on port $BackendPort (PID: $($backendProc.Id))..." -ForegroundColor Green
Pop-Location

# Celery (optional, if Redis available)
if ($hasRedis) {
    Push-Location $BackendDir
    $celeryProc = Start-Process -NoNewWindow -PassThru -FilePath "uv" `
        -ArgumentList "run celery -A app.tasks.celery_app worker --beat --loglevel=info" `
        -RedirectStandardOutput (Join-Path $LogsDir "celery.log") `
        -RedirectStandardError (Join-Path $LogsDir "celery-err.log")
    $celeryProc.Id | Set-Content (Join-Path $LogsDir "celery.pid")
    Write-Host "  [OK] Celery worker starting (PID: $($celeryProc.Id))..." -ForegroundColor Green
    Pop-Location
}

# Frontend — on the chosen port; pointed at the backend we just started
Push-Location $ProjectDir
if (Test-Path (Join-Path $WebDir "package.json")) {
    $env:PORT = "$FrontendPort"
    $env:NEXT_PUBLIC_API_URL = "http://localhost:$BackendPort/api/v1"
    $env:NEXT_PUBLIC_WS_URL  = "ws://localhost:$BackendPort"
    $frontendProc = Start-Process -NoNewWindow -PassThru -FilePath "pnpm" `
        -ArgumentList "--filter @finance-tracker/web dev" `
        -RedirectStandardOutput (Join-Path $LogsDir "frontend.log") `
        -RedirectStandardError (Join-Path $LogsDir "frontend-err.log")
    $frontendProc.Id | Set-Content (Join-Path $LogsDir "frontend.pid")
    Write-Host "  [OK] Web App starting on port $FrontendPort (PID: $($frontendProc.Id))..." -ForegroundColor Green
}
Pop-Location

# ── Step 6: Health Check Loop ────────────────────────────────────────────────

Write-Host ""
Write-Host "[6/6] Waiting for services..." -ForegroundColor Yellow

# Wait for backend
$backendReady = $false
for ($i = 1; $i -le 20; $i++) {
    try {
        Invoke-WebRequest -Uri "http://localhost:$BackendPort/health" -TimeoutSec 1 -ErrorAction Stop | Out-Null
        Write-Host "  [OK] Backend: http://localhost:$BackendPort" -ForegroundColor Green
        $backendReady = $true
        break
    } catch {
        Start-Sleep -Milliseconds 500
    }
}
if (-not $backendReady) { Write-Host "  [WARN] Backend still starting (check logs\backend.log)" -ForegroundColor Yellow }

# Wait for frontend
$frontendReady = $false
for ($i = 1; $i -le 20; $i++) {
    try {
        Invoke-WebRequest -Uri "http://localhost:$FrontendPort" -TimeoutSec 1 -ErrorAction Stop | Out-Null
        Write-Host "  [OK] Web App: http://localhost:$FrontendPort" -ForegroundColor Green
        $frontendReady = $true
        break
    } catch {
        Start-Sleep -Milliseconds 500
    }
}
if (-not $frontendReady) { Write-Host "  [WARN] Frontend still starting (check logs\frontend.log)" -ForegroundColor Yellow }

Write-Host ""
Write-Host "======================================================" -ForegroundColor Blue
Write-Host "  FinanceTracker is running!" -ForegroundColor Green
Write-Host "  Web:     http://localhost:$FrontendPort" -ForegroundColor White
Write-Host "  API:     http://localhost:$BackendPort" -ForegroundColor White
Write-Host "  Docs:    http://localhost:$BackendPort/docs" -ForegroundColor White
Write-Host "======================================================" -ForegroundColor Blue
Write-Host ""
Write-Host "  To stop:  .\scripts\stop.ps1" -ForegroundColor White
