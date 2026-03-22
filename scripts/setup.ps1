# =============================================================================
# FinanceTracker — First-Time Setup (Windows PowerShell)
# =============================================================================

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BackendDir = Join-Path $ProjectDir "backend"

Write-Host "FinanceTracker - First-Time Setup" -ForegroundColor Blue
Write-Host ""

# Install uv
try { uv --version | Out-Null } catch {
    Write-Host "Installing uv..." -ForegroundColor Yellow
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
}

# Install pnpm
try { pnpm --version | Out-Null } catch {
    Write-Host "Installing pnpm..." -ForegroundColor Yellow
    npm install -g pnpm
}

# Backend
Set-Location $BackendDir
if ((-not (Test-Path ".env")) -and (Test-Path ".env.example")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from template" -ForegroundColor Green
}
uv sync
Write-Host "Backend dependencies installed" -ForegroundColor Green

if (Test-Path "alembic.ini") {
    uv run alembic upgrade head
    Write-Host "Database initialized" -ForegroundColor Green
}

# Frontend
Set-Location $ProjectDir
if (Test-Path "pnpm-workspace.yaml") {
    pnpm install
    Write-Host "Frontend dependencies installed" -ForegroundColor Green
}

Write-Host ""
Write-Host "Setup complete! Run .\scripts\start.ps1 to launch." -ForegroundColor Green
