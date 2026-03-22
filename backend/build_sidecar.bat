@echo off
setlocal

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

REM Create binaries directory
if not exist "%BINARIES_DIR%" mkdir "%BINARIES_DIR%"

REM Copy with target-triple suffix
set BINARY_NAME=financetracker-backend-%TARGET%.exe
copy /Y "dist\financetracker-backend.exe" "%BINARIES_DIR%\%BINARY_NAME%"

echo.
echo Sidecar built: %BINARIES_DIR%\%BINARY_NAME%

endlocal
