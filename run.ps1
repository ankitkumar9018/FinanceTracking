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

# Pick a free TCP port: try each preferred port in order, else an OS-assigned
# ephemeral one. Never grabs a port another app is already listening on.
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

    # We only ever stop our OWN processes (via the PID files above) — we never
    # kill by port or by process name, so co-running apps are never touched.
    Remove-Item (Join-Path $LogsDir "backend.port")  -Force -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $LogsDir "frontend.port") -Force -ErrorAction SilentlyContinue

    Write-Host "FinanceTracker stopped." -ForegroundColor Green
}

# -- STATUS -------------------------------------------------------------------

function Do-Status {
    Write-Host "FinanceTracker Status" -ForegroundColor Cyan
    Write-Host ""

    $bPidFile = Join-Path $LogsDir "backend.pid"
    $bPortFile = Join-Path $LogsDir "backend.port"
    $bPort = if (Test-Path $bPortFile) { Get-Content $bPortFile } else { "8420" }
    if ((Test-Path $bPidFile) -and (Get-Process -Id (Get-Content $bPidFile) -ErrorAction SilentlyContinue)) {
        Write-Host "  Backend:  " -NoNewline; Write-Host "Running" -ForegroundColor Green -NoNewline; Write-Host " - http://localhost:$bPort"
    } else {
        Write-Host "  Backend:  " -NoNewline; Write-Host "Stopped" -ForegroundColor Red
    }

    $fPidFile = Join-Path $LogsDir "frontend.pid"
    $fPortFile = Join-Path $LogsDir "frontend.port"
    $fPort = if (Test-Path $fPortFile) { Get-Content $fPortFile } else { "3000" }
    if ((Test-Path $fPidFile) -and (Get-Process -Id (Get-Content $fPidFile) -ErrorAction SilentlyContinue)) {
        Write-Host "  Frontend: " -NoNewline; Write-Host "Running" -ForegroundColor Green -NoNewline; Write-Host " - http://localhost:$fPort"
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

    # -- Step 2: Stop any previous FinanceTracker instance --------------------
    Write-Step "Step 2/6: Stopping any previous FinanceTracker instance..."

    # Only stop OUR own previous run (via PID files). We never kill by port or
    # process name, so co-running apps (on 8000, 3000, ...) are never touched.
    foreach ($svc in @("backend", "frontend")) {
        $pf = Join-Path $LogsDir "$svc.pid"
        if (Test-Path $pf) {
            Stop-Process -Id (Get-Content $pf) -Force -ErrorAction SilentlyContinue
            Remove-Item $pf -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Ok "Ready to start (other apps left untouched)"

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

    # Auto-pick free ports for BOTH services (prefers 8420 / 3000; skips to the
    # next free port automatically — never steals a port another app is using).
    $BackendPort  = Find-FreePort @(8420,8421,8422,8423,8424,8425,8426,8427,8428,8429)
    $FrontendPort = Find-FreePort @(3000,3001,3002,3003,3004,3005)
    "$BackendPort"  | Set-Content (Join-Path $LogsDir "backend.port")
    "$FrontendPort" | Set-Content (Join-Path $LogsDir "frontend.port")

    # Backend — on the chosen port; CORS allows the chosen frontend origin
    Push-Location $BackendDir
    Write-Info "Starting backend on port $BackendPort..."
    $env:CORS_ORIGINS = "http://localhost:$FrontendPort,http://localhost:3000,http://localhost:1420,https://tauri.localhost"
    $backendLog = Join-Path $LogsDir "backend.log"
    $backendProc = Start-Process -NoNewWindow -PassThru -FilePath "uv" `
        -ArgumentList "run uvicorn app.main:app --reload --host 127.0.0.1 --port $BackendPort" `
        -RedirectStandardOutput $backendLog -RedirectStandardError (Join-Path $LogsDir "backend-err.log")
    $backendProc.Id | Set-Content (Join-Path $LogsDir "backend.pid")
    Pop-Location

    # Wait for backend
    for ($i = 1; $i -le 40; $i++) {
        try {
            $resp = Invoke-WebRequest -Uri "http://localhost:$BackendPort/health" -TimeoutSec 1 -ErrorAction Stop
            Write-Ok "Backend running on port $BackendPort (PID: $($backendProc.Id))"
            break
        } catch {
            if ($i -eq 40) { Write-Warn "Backend still starting on port $BackendPort..." }
            Start-Sleep -Milliseconds 500
        }
    }

    # Frontend — on the chosen port; pointed at the backend we just started
    Push-Location $ProjectRoot
    Write-Info "Starting frontend on port $FrontendPort..."
    $env:PORT = "$FrontendPort"
    $env:NEXT_PUBLIC_API_URL = "http://localhost:$BackendPort/api/v1"
    $env:NEXT_PUBLIC_WS_URL  = "ws://localhost:$BackendPort"
    $frontendLog = Join-Path $LogsDir "frontend.log"
    $frontendProc = Start-Process -NoNewWindow -PassThru -FilePath "pnpm" `
        -ArgumentList "--filter @finance-tracker/web dev" `
        -RedirectStandardOutput $frontendLog -RedirectStandardError (Join-Path $LogsDir "frontend-err.log")
    $frontendProc.Id | Set-Content (Join-Path $LogsDir "frontend.pid")
    Pop-Location

    # Wait for frontend
    for ($i = 1; $i -le 40; $i++) {
        try {
            Invoke-WebRequest -Uri "http://localhost:$FrontendPort" -TimeoutSec 1 -ErrorAction Stop | Out-Null
            Write-Ok "Frontend running on port $FrontendPort (PID: $($frontendProc.Id))"
            break
        } catch {
            if ($i -eq 40) { Write-Warn "Frontend still starting on port $FrontendPort..." }
            Start-Sleep -Milliseconds 500
        }
    }

    # -- Step 6: Done! --------------------------------------------------------
    Write-Step "Step 6/6: Ready!"

    Start-Sleep -Seconds 1

    # Open browser
    Start-Process "http://localhost:$FrontendPort"

    Write-Host ""
    Write-Host "+========================================+" -ForegroundColor Green
    Write-Host "|     FinanceTracker is now running!     |" -ForegroundColor Green
    Write-Host "+========================================+" -ForegroundColor Green
    Write-Host ""
    Write-Host "  App:      http://localhost:$FrontendPort" -ForegroundColor White
    Write-Host "  API:      http://localhost:$BackendPort" -ForegroundColor White
    Write-Host "  Docs:     http://localhost:$BackendPort/docs" -ForegroundColor White
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
