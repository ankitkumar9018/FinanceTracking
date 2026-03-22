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

# Kill by port as fallback
foreach ($port in @(8000, 3000)) {
    $conns = Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue
    if ($conns) {
        $pids = $conns | Select-Object -ExpandProperty OwningProcess -Unique
        foreach ($pid in $pids) {
            if ($pid -ne 0) {
                Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue
                Write-Host "  Killed process on port $port (PID: $pid)" -ForegroundColor Green
            }
        }
    }
}

# Kill by process name as last resort
Get-Process -Name "uvicorn" -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process -Name "celery" -ErrorAction SilentlyContinue | Stop-Process -Force

Write-Host "All services stopped." -ForegroundColor Green
