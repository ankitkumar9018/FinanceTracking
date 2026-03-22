# =============================================================================
# FinanceTracker — Health Check Script (Windows PowerShell)
# Checks the status of all services
# =============================================================================

Write-Host "===================================================" -ForegroundColor Blue
Write-Host "  FinanceTracker - Service Health" -ForegroundColor Blue
Write-Host "===================================================" -ForegroundColor Blue
Write-Host ""

# Backend API
try {
    $resp = Invoke-WebRequest -Uri "http://localhost:8000/health" -TimeoutSec 2 -ErrorAction Stop
    if ($resp.Content -match "healthy") {
        Write-Host "  Backend API:     " -NoNewline; Write-Host "Healthy" -ForegroundColor Green -NoNewline; Write-Host "  http://localhost:8000"
    } else {
        Write-Host "  Backend API:     " -NoNewline; Write-Host "Unhealthy" -ForegroundColor Red
    }
} catch {
    Write-Host "  Backend API:     " -NoNewline; Write-Host "Down" -ForegroundColor Red
}

# Web App
try {
    Invoke-WebRequest -Uri "http://localhost:3000" -TimeoutSec 2 -ErrorAction Stop | Out-Null
    Write-Host "  Web App:         " -NoNewline; Write-Host "Running" -ForegroundColor Green -NoNewline; Write-Host "  http://localhost:3000"
} catch {
    Write-Host "  Web App:         " -NoNewline; Write-Host "Down" -ForegroundColor Red
}

# Redis
try {
    $redisPing = redis-cli ping 2>&1
    if ($redisPing -eq "PONG") {
        Write-Host "  Redis:           " -NoNewline; Write-Host "Connected" -ForegroundColor Green
    } else {
        throw "not pong"
    }
} catch {
    Write-Host "  Redis:           " -NoNewline; Write-Host "Not available" -ForegroundColor Yellow -NoNewline; Write-Host " (using fallback)"
}

# Ollama
try {
    $ollamaResp = Invoke-WebRequest -Uri "http://localhost:11434/api/tags" -TimeoutSec 2 -ErrorAction Stop
    $tags = $ollamaResp.Content | ConvertFrom-Json
    $models = ($tags.models | ForEach-Object { $_.name }) -join ", "
    if (-not $models) { $models = "none" }
    Write-Host "  Ollama:          " -NoNewline; Write-Host "Running" -ForegroundColor Green -NoNewline; Write-Host "  Models: $models"
} catch {
    Write-Host "  Ollama:          " -NoNewline; Write-Host "Not available" -ForegroundColor Yellow -NoNewline; Write-Host " (AI disabled)"
}

# Database
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$dbFile = Join-Path $ProjectRoot "backend" "finance.db"
if (Test-Path $dbFile) {
    $dbSize = (Get-Item $dbFile).Length
    $dbSizeStr = if ($dbSize -gt 1MB) { "{0:N1} MB" -f ($dbSize / 1MB) } else { "{0:N0} KB" -f ($dbSize / 1KB) }
    Write-Host "  Database:        " -NoNewline; Write-Host "SQLite" -ForegroundColor Green -NoNewline; Write-Host "  Size: $dbSizeStr"
} else {
    Write-Host "  Database:        " -NoNewline; Write-Host "Not created yet" -ForegroundColor Yellow
}

Write-Host ""
