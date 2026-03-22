# =============================================================================
#  FinanceTracker - Single Script Launcher (Windows PowerShell)
#  Usage: .\run.ps1 [start|stop|restart|status|logs]
# =============================================================================

param(
    [ValidateSet("start", "stop", "restart", "status", "logs")]
    [string]$Action = "start"
)

$ErrorActionPreference = "Continue"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$BackendDir = Join-Path $ProjectRoot "backend"
$LogsDir = Join-Path $ProjectRoot "logs"

# -- Helpers ------------------------------------------------------------------

function Write-Info  { param($msg) Write-Host "[INFO] $msg" -ForegroundColor Blue }
function Write-Ok    { param($msg) Write-Host "[OK]   $msg" -ForegroundColor Green }
function Write-Warn  { param($msg) Write-Host "[WARN] $msg" -ForegroundColor Yellow }
function Write-Err   { param($msg) Write-Host "[ERROR] $msg" -ForegroundColor Red }
function Write-Step  { param($msg) Write-Host "`n> $msg" -ForegroundColor Cyan }

function Stop-PortProcess {
    param([int]$Port)
    $conns = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    if ($conns) {
        $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($pid in $pids) {
            if ($pid -ne 0) {
                Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
            }
        }
        return $true
    }
    return $false
}

# -- STOP ---------------------------------------------------------------------

function Do-Stop {
    Write-Host "Stopping FinanceTracker..." -ForegroundColor Yellow

    # Kill by PID files
    $backendPid = Join-Path $LogsDir "backend.pid"
    if (Test-Path $backendPid) {
        $pid = Get-Content $backendPid
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        Write-Ok "Backend stopped (PID: $pid)"
        Remove-Item $backendPid -Force
    }

    $frontendPid = Join-Path $LogsDir "frontend.pid"
    if (Test-Path $frontendPid) {
        $pid = Get-Content $frontendPid
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        Write-Ok "Frontend stopped (PID: $pid)"
        Remove-Item $frontendPid -Force
    }

    # Kill by port as fallback
    if (Stop-PortProcess 8000) { Write-Ok "Killed process on port 8000" }
    if (Stop-PortProcess 3000) { Write-Ok "Killed process on port 3000" }

    # Kill uvicorn by name as last resort
    Get-Process -Name "uvicorn" -ErrorAction SilentlyContinue | Stop-Process -Force

    Write-Host "FinanceTracker stopped." -ForegroundColor Green
}

# -- STATUS -------------------------------------------------------------------

function Do-Status {
    Write-Host "FinanceTracker Status" -ForegroundColor Cyan
    Write-Host ""

    $port8000 = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    if ($port8000) {
        $pid = ($port8000 | Select-Object -First 1).OwningProcess
        Write-Host "  Backend:  " -NoNewline; Write-Host "Running" -ForegroundColor Green -NoNewline; Write-Host " (PID: $pid) - http://localhost:8000"
    } else {
        Write-Host "  Backend:  " -NoNewline; Write-Host "Stopped" -ForegroundColor Red
    }

    $port3000 = Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue
    if ($port3000) {
        $pid = ($port3000 | Select-Object -First 1).OwningProcess
        Write-Host "  Frontend: " -NoNewline; Write-Host "Running" -ForegroundColor Green -NoNewline; Write-Host " (PID: $pid) - http://localhost:3000"
    } else {
        Write-Host "  Frontend: " -NoNewline; Write-Host "Stopped" -ForegroundColor Red
    }
    Write-Host ""
}

# -- LOGS ---------------------------------------------------------------------

function Do-Logs {
    if (-not (Test-Path $LogsDir)) {
        Write-Err "No logs directory found. Start the app first."
        exit 1
    }
    Write-Host "Following logs (Ctrl+C to exit)..." -ForegroundColor Blue
    $backendLog = Join-Path $LogsDir "backend.log"
    $frontendLog = Join-Path $LogsDir "frontend.log"
    Get-Content $backendLog, $frontendLog -Wait -ErrorAction SilentlyContinue
}

# -- START --------------------------------------------------------------------

function Do-Start {
    Clear-Host
    Write-Host ""
    Write-Host "+========================================+" -ForegroundColor Green
    Write-Host "|   FinanceTracker - One Click Launch    |" -ForegroundColor Green
    Write-Host "+========================================+" -ForegroundColor Green
    Write-Host ""

    # -- Step 1: Prerequisites ------------------------------------------------
    Write-Step "Step 1/6: Checking & installing prerequisites..."

    # Node.js
    try {
        $nodeVer = (node --version 2>&1).ToString().TrimStart("v")
        $nodeMajor = [int]($nodeVer.Split(".")[0])
        if ($nodeMajor -lt 20) { throw "too old" }
        Write-Ok "Node.js v$nodeVer"
    } catch {
        Write-Err "Node.js 20+ required. Download: https://nodejs.org"
        exit 1
    }

    # pnpm
    try {
        $pnpmVer = pnpm --version 2>&1
        Write-Ok "pnpm $pnpmVer"
    } catch {
        Write-Warn "pnpm not found. Installing..."
        npm install -g pnpm
    }

    # Python
    $pythonCmd = $null
    foreach ($cmd in @("python3", "python")) {
        try {
            $ver = & $cmd -c "import sys; print(sys.version_info.minor)" 2>&1
            if ([int]$ver -ge 12) {
                $pythonCmd = $cmd
                break
            }
        } catch {}
    }
    if (-not $pythonCmd) {
        Write-Err "Python 3.12+ required. Download: https://python.org"
        exit 1
    }
    $pyFullVer = & $pythonCmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
    Write-Ok "Python $pyFullVer"

    # uv
    try {
        $uvVer = uv --version 2>&1
        Write-Ok "$uvVer"
    } catch {
        Write-Warn "uv not found. Installing..."
        powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    }

    # -- Step 2: Stop existing processes --------------------------------------
    Write-Step "Step 2/6: Stopping existing processes..."

    Stop-PortProcess 8000 | Out-Null
    Stop-PortProcess 3000 | Out-Null
    Get-Process -Name "uvicorn" -ErrorAction SilentlyContinue | Stop-Process -Force
    Write-Ok "Ports 8000 and 3000 are free"

    # -- Step 3: Install dependencies -----------------------------------------
    Write-Step "Step 3/6: Installing dependencies..."

    Push-Location $BackendDir
    Write-Info "Backend packages..."
    uv sync --quiet 2>$null
    if ($LASTEXITCODE -ne 0) { uv sync }
    Write-Ok "Backend ready"
    Pop-Location

    Write-Info "Frontend packages..."
    Push-Location $ProjectRoot
    pnpm install --silent 2>$null
    if ($LASTEXITCODE -ne 0) { pnpm install }
    Write-Ok "Frontend ready"
    Pop-Location

    # -- Step 4: Setup environment & database ---------------------------------
    Write-Step "Step 4/6: Setting up environment..."

    Push-Location $BackendDir
    $envFile = Join-Path $BackendDir ".env"
    $envExample = Join-Path $BackendDir ".env.example"

    if ((-not (Test-Path $envFile)) -and (Test-Path $envExample)) {
        Copy-Item $envExample $envFile
        # Generate a secret key
        $secretKey = try { (python3 -c "import secrets; print(secrets.token_hex(32))" 2>$null) } catch { $null }
        if (-not $secretKey) { $secretKey = -join ((1..32) | ForEach-Object { "{0:x2}" -f (Get-Random -Maximum 256) }) }
        (Get-Content $envFile) -replace "^SECRET_KEY=.*", "SECRET_KEY=$secretKey" | Set-Content $envFile
        Write-Ok ".env created with secure secret key"
    } elseif (Test-Path $envFile) {
        Write-Ok ".env exists"
    } else {
        $secretKey = try { (python3 -c "import secrets; print(secrets.token_hex(32))" 2>$null) } catch { $null }
        if (-not $secretKey) { $secretKey = -join ((1..32) | ForEach-Object { "{0:x2}" -f (Get-Random -Maximum 256) }) }
        @"
DATABASE_URL=sqlite+aiosqlite:///./finance_tracker.db
SECRET_KEY=$secretKey
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
ENVIRONMENT=development
"@ | Set-Content $envFile
        Write-Ok ".env created"
    }

    Write-Info "Running database migrations..."
    uv run alembic upgrade head 2>&1 | Select-Object -Last 3
    Write-Ok "Database ready"
    Pop-Location

    # -- Step 5: Start services -----------------------------------------------
    Write-Step "Step 5/6: Starting services..."

    if (-not (Test-Path $LogsDir)) { New-Item -ItemType Directory -Path $LogsDir -Force | Out-Null }

    # Backend
    Push-Location $BackendDir
    Write-Info "Starting backend..."
    $backendLog = Join-Path $LogsDir "backend.log"
    $backendProc = Start-Process -NoNewWindow -PassThru -FilePath "uv" `
        -ArgumentList "run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000" `
        -RedirectStandardOutput $backendLog -RedirectStandardError (Join-Path $LogsDir "backend-err.log")
    $backendProc.Id | Set-Content (Join-Path $LogsDir "backend.pid")
    Pop-Location

    # Wait for backend
    for ($i = 1; $i -le 20; $i++) {
        try {
            $resp = Invoke-WebRequest -Uri "http://localhost:8000/health" -TimeoutSec 1 -ErrorAction Stop
            Write-Ok "Backend running (PID: $($backendProc.Id))"
            break
        } catch {
            if ($i -eq 20) { Write-Warn "Backend still starting..." }
            Start-Sleep -Milliseconds 500
        }
    }

    # Frontend
    Push-Location $ProjectRoot
    Write-Info "Starting frontend..."
    $frontendLog = Join-Path $LogsDir "frontend.log"
    $frontendProc = Start-Process -NoNewWindow -PassThru -FilePath "pnpm" `
        -ArgumentList "--filter @finance-tracker/web dev" `
        -RedirectStandardOutput $frontendLog -RedirectStandardError (Join-Path $LogsDir "frontend-err.log")
    $frontendProc.Id | Set-Content (Join-Path $LogsDir "frontend.pid")
    Pop-Location

    # Wait for frontend
    for ($i = 1; $i -le 20; $i++) {
        try {
            Invoke-WebRequest -Uri "http://localhost:3000" -TimeoutSec 1 -ErrorAction Stop | Out-Null
            Write-Ok "Frontend running (PID: $($frontendProc.Id))"
            break
        } catch {
            if ($i -eq 20) { Write-Warn "Frontend still starting..." }
            Start-Sleep -Milliseconds 500
        }
    }

    # -- Step 6: Done! --------------------------------------------------------
    Write-Step "Step 6/6: Ready!"

    Start-Sleep -Seconds 1

    # Open browser
    Start-Process "http://localhost:3000"

    Write-Host ""
    Write-Host "+========================================+" -ForegroundColor Green
    Write-Host "|     FinanceTracker is now running!     |" -ForegroundColor Green
    Write-Host "+========================================+" -ForegroundColor Green
    Write-Host ""
    Write-Host "  App:      http://localhost:3000" -ForegroundColor White
    Write-Host "  API:      http://localhost:8000" -ForegroundColor White
    Write-Host "  Docs:     http://localhost:8000/docs" -ForegroundColor White
    Write-Host ""
    Write-Host "  Commands:" -ForegroundColor Yellow
    Write-Host "     .\run.ps1 stop     Stop all services"
    Write-Host "     .\run.ps1 status   Check service status"
    Write-Host "     .\run.ps1 logs     Follow logs"
    Write-Host "     .\run.ps1 restart  Restart everything"
    Write-Host ""
}

# -- Main dispatch ------------------------------------------------------------

switch ($Action) {
    "start"   { Do-Start }
    "stop"    { Do-Stop }
    "restart" { Do-Stop; Start-Sleep -Seconds 2; Do-Start }
    "status"  { Do-Status }
    "logs"    { Do-Logs }
}
