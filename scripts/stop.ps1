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
        $pid = Get-Content $pidFile
        Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
        Write-Host "  Stopped $service (PID: $pid)" -ForegroundColor Green
        Remove-Item $pidFile -Force
    }
}

# We only ever stop our OWN processes (via the PID files above) — we never kill
# by port or by process name, so co-running apps are never touched.
Remove-Item (Join-Path $LogsDir "backend.port")  -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $LogsDir "frontend.port") -Force -ErrorAction SilentlyContinue

Write-Host "All services stopped." -ForegroundColor Green
