# =============================================================================
# FinanceTracker — Stop Script (Windows PowerShell)
# =============================================================================

Write-Host "Stopping FinanceTracker services..." -ForegroundColor Blue

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$LogsDir = Join-Path $ProjectRoot "logs"

# Kill by PID files first
foreach ($service in @("backend", "frontend")) {
    $pidFile = Join-Path $LogsDir "$service.pid"
    if (Test-Path $pidFile) {
        # NOTE: use $procId, never $pid — $pid is a read-only PowerShell automatic
        # variable holding THIS shell's PID, so `$pid = ...` fails and a later
        # Stop-Process -Id $pid would kill our own host, orphaning the service.
        $procId = Get-Content $pidFile
        # The recorded PID is the `uv` wrapper; its uvicorn child must be killed
        # too or it is orphaned and keeps holding the port. Kill children first,
        # then the parent — strictly OUR recorded PID, never by port or name.
        Get-CimInstance Win32_Process -Filter "ParentProcessId=$procId" -ErrorAction SilentlyContinue |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        Write-Host "  Stopped $service (PID: $procId)" -ForegroundColor Green
        Remove-Item $pidFile -Force
    }
}

# We only ever stop our OWN processes (via the PID files above) — we never kill
# by port or by process name, so co-running apps are never touched.
Remove-Item (Join-Path $LogsDir "backend.port")  -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $LogsDir "frontend.port") -Force -ErrorAction SilentlyContinue

Write-Host "All services stopped." -ForegroundColor Green
