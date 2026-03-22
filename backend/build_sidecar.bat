@echo off
setlocal enabledelayedexpansion

REM Build the FinanceTracker backend as a PyInstaller binary for Tauri sidecar.

set SCRIPT_DIR=%~dp0
set PROJECT_ROOT=%SCRIPT_DIR%..
set BINARIES_DIR=%PROJECT_ROOT%\apps\desktop\src-tauri\binaries

REM Detect architecture
if "%PROCESSOR_ARCHITECTURE%"=="ARM64" (
    set TARGET=aarch64-pc-windows-msvc
) else (
    set TARGET=x86_64-pc-windows-msvc
)

echo Building sidecar for target: %TARGET%

cd /d "%SCRIPT_DIR%"

REM Ensure PyInstaller is available (it's a dev dependency in pyproject.toml)
uv run python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo Installing PyInstaller as dev dependency...
    uv add --dev pyinstaller
)

REM Run PyInstaller
uv run pyinstaller financetracker.spec --clean --noconfirm
if errorlevel 1 (echo ERROR: PyInstaller build failed && exit /b 1)

if not exist "dist\financetracker-backend.exe" (
    echo ERROR: Binary not found after build
    exit /b 1
)

REM Smoke test -- catch module errors before copying
echo.
echo Smoke-testing sidecar binary...
set "SMOKE_DB=%TEMP%\ft_smoke_%RANDOM%.db"
start /b /wait dist\financetracker-backend.exe --port 59999 --host 127.0.0.1 --db-path "!SMOKE_DB!" --seed 2>"!TEMP!\ft_smoke_err.txt"
set "SMOKE_EXIT=!ERRORLEVEL!"
if !SMOKE_EXIT! NEQ 0 (
    echo.
    echo ERROR: Sidecar binary crashed ^(exit code !SMOKE_EXIT!^)
    echo --- Error output ---
    type "!TEMP!\ft_smoke_err.txt"
    echo --------------------
    del /q "!SMOKE_DB!" 2>nul
    del /q "!TEMP!\ft_smoke_err.txt" 2>nul
    exit /b 1
)
del /q "!SMOKE_DB!" 2>nul
del /q "!TEMP!\ft_smoke_err.txt" 2>nul
echo [OK] Sidecar binary starts successfully

REM Create binaries directory
if not exist "%BINARIES_DIR%" mkdir "%BINARIES_DIR%"

REM Copy with target-triple suffix
set BINARY_NAME=financetracker-backend-%TARGET%.exe
copy /Y "dist\financetracker-backend.exe" "%BINARIES_DIR%\%BINARY_NAME%"

echo.
echo Sidecar built: %BINARIES_DIR%\%BINARY_NAME%

endlocal
