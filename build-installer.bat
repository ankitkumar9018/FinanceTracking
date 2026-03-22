@echo off
setlocal enabledelayedexpansion

REM ============================================================================
REM  FinanceTracker — Build Installer (Windows)
REM  Creates a native .msi and .exe (NSIS) installer
REM
REM  Usage: build-installer.bat
REM  Auto-installs missing prerequisites: Node.js, pnpm, Python, uv, Rust
REM  Auto-updates system PATH so tools are available immediately
REM ============================================================================

set "PROJECT_ROOT=%~dp0"
set "BACKEND_DIR=%PROJECT_ROOT%backend"
set "WEB_DIR=%PROJECT_ROOT%apps\web"
set "DESKTOP_DIR=%PROJECT_ROOT%apps\desktop"
set "BINARIES_DIR=%DESKTOP_DIR%\src-tauri\binaries"
set "NEED_RESTART=0"

REM Detect architecture
if "%PROCESSOR_ARCHITECTURE%"=="AMD64" (
    set "TARGET=x86_64-pc-windows-msvc"
    set "ARCH=x64"
) else if "%PROCESSOR_ARCHITECTURE%"=="ARM64" (
    set "TARGET=aarch64-pc-windows-msvc"
    set "ARCH=arm64"
) else (
    echo ERROR: Unsupported architecture: %PROCESSOR_ARCHITECTURE%
    exit /b 1
)

echo.
echo ========================================
echo   FinanceTracker — Installer Builder
echo   Platform: Windows ^(%ARCH%^)
echo ========================================
echo.

REM -------------------------------------------------------------------------
REM Helper: Reload PATH from the registry into the current session
REM This picks up changes made by installers (winget, rustup, etc.)
REM without requiring the user to restart the terminal.
REM -------------------------------------------------------------------------
goto :skip_refresh_path
:refresh_path
    REM Read the system PATH from registry
    for /f "tokens=2*" %%A in ('reg query "HKLM\SYSTEM\CurrentControlSet\Control\Session Manager\Environment" /v Path 2^>nul') do set "SYS_PATH=%%B"
    REM Read the user PATH from registry
    for /f "tokens=2*" %%A in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "USR_PATH=%%B"
    REM Combine: keep current session overrides, then system, then user
    set "PATH=!SYS_PATH!;!USR_PATH!"
    goto :eof
:skip_refresh_path

REM -------------------------------------------------------------------------
REM Helper: Add a directory to the user PATH permanently (persists after reboot)
REM Usage: call :add_to_path "C:\some\directory"
REM -------------------------------------------------------------------------
goto :skip_add_to_path
:add_to_path
    set "NEW_DIR=%~1"
    REM Check if already in user PATH
    for /f "tokens=2*" %%A in ('reg query "HKCU\Environment" /v Path 2^>nul') do set "CUR_USR_PATH=%%B"
    echo !CUR_USR_PATH! | findstr /i /c:"!NEW_DIR!" >nul 2>&1
    if errorlevel 1 (
        REM Not found — append it
        if defined CUR_USR_PATH (
            setx PATH "!CUR_USR_PATH!;!NEW_DIR!" >nul 2>&1
        ) else (
            setx PATH "!NEW_DIR!" >nul 2>&1
        )
        echo   [PATH] Added !NEW_DIR! to user PATH
    )
    REM Also add to current session immediately
    set "PATH=!NEW_DIR!;!PATH!"
    goto :eof
:skip_add_to_path

REM -------------------------------------------------------------------------
REM Step 1: Check and auto-install prerequisites
REM -------------------------------------------------------------------------
echo [Step 1/7] Checking prerequisites ^(will auto-install if missing^)...
echo.

REM --- Node.js ---
where node >nul 2>&1
if errorlevel 1 (
    echo [MISSING] Node.js — installing via winget...
    winget install --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements -e
    if errorlevel 1 (
        echo [FALLBACK] winget failed. Trying fnm ^(Fast Node Manager^)...
        powershell -Command "irm https://fnm.vercel.app/install | iex" 2>nul
        if errorlevel 1 (
            echo ERROR: Could not install Node.js automatically.
            echo   Please install manually from https://nodejs.org ^(v20+^)
            exit /b 1
        )
        call :add_to_path "%LOCALAPPDATA%\fnm"
        fnm install --lts
        fnm use lts-latest
    )
    REM winget installs Node.js to Program Files — add to session PATH
    call :add_to_path "%ProgramFiles%\nodejs"
    call :refresh_path
)
where node >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js installed but not in PATH. Please restart your terminal and re-run.
    set "NEED_RESTART=1"
    goto :check_restart
)

REM Check Node.js version >= 20
for /f "usebackq tokens=*" %%a in (`node -v`) do set "NODE_VER=%%a"
set "NODE_VER=!NODE_VER:v=!"
for /f "tokens=1 delims=." %%a in ("!NODE_VER!") do set "NODE_MAJOR=%%a"
if !NODE_MAJOR! LSS 20 (
    echo ERROR: Node.js 20+ required ^(found v!NODE_MAJOR!^). Please update.
    exit /b 1
)
echo [OK] Node.js v!NODE_VER!

REM --- pnpm ---
where pnpm >nul 2>&1
if errorlevel 1 (
    echo [MISSING] pnpm — installing via npm...
    call npm install -g pnpm
    if errorlevel 1 (
        echo [FALLBACK] Trying standalone install...
        powershell -Command "iwr https://get.pnpm.io/install.ps1 -useb | iex"
        call :add_to_path "%LOCALAPPDATA%\pnpm"
    )
    REM npm global installs go to the npm prefix — add to session PATH
    for /f "usebackq tokens=*" %%a in (`npm config get prefix 2^>nul`) do call :add_to_path "%%a"
    call :refresh_path
)
where pnpm >nul 2>&1
if errorlevel 1 (
    echo ERROR: pnpm installed but not in PATH. Please restart terminal and re-run.
    set "NEED_RESTART=1"
    goto :check_restart
)
echo [OK] pnpm found

REM --- Python 3.12+ ---
where python >nul 2>&1
if errorlevel 1 (
    echo [MISSING] Python — installing via winget...
    winget install --id Python.Python.3.13 --accept-source-agreements --accept-package-agreements -e
    if errorlevel 1 (
        echo ERROR: Could not install Python automatically.
        echo   Please install manually from https://python.org ^(v3.12+, check "Add to PATH"^)
        exit /b 1
    )
    REM winget Python installs here by default
    call :add_to_path "%LOCALAPPDATA%\Programs\Python\Python313"
    call :add_to_path "%LOCALAPPDATA%\Programs\Python\Python313\Scripts"
    call :refresh_path
)
where python >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python installed but not in PATH. Please restart terminal and re-run.
    set "NEED_RESTART=1"
    goto :check_restart
)
python -c "import sys; exit(0 if sys.version_info >= (3,12) else 1)" 2>nul
if errorlevel 1 (
    echo ERROR: Python 3.12+ is required. Found older version.
    echo   Please install from https://python.org ^(check "Add to PATH"^)
    exit /b 1
)
for /f "usebackq tokens=*" %%a in (`python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"`) do set "PY_VER=%%a"
echo [OK] Python !PY_VER!

REM --- uv (Python package manager) ---
where uv >nul 2>&1
if errorlevel 1 (
    echo [MISSING] uv — installing...
    powershell -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    if errorlevel 1 (
        echo ERROR: Could not install uv automatically.
        echo   Please install from https://docs.astral.sh/uv/
        exit /b 1
    )
    REM uv installs to ~/.local/bin or cargo/bin
    call :add_to_path "%USERPROFILE%\.local\bin"
    call :add_to_path "%USERPROFILE%\.cargo\bin"
    call :refresh_path
)
where uv >nul 2>&1
if errorlevel 1 (
    echo ERROR: uv installed but not in PATH. Please restart terminal and re-run.
    set "NEED_RESTART=1"
    goto :check_restart
)
echo [OK] uv found

REM --- Rust (rustc + cargo) ---
where rustc >nul 2>&1
if errorlevel 1 (
    echo [MISSING] Rust — installing via rustup ^(silent, default toolchain^)...
    powershell -Command "Invoke-WebRequest -Uri 'https://win.rustup.rs/x86_64' -OutFile '%TEMP%\rustup-init.exe'"
    "%TEMP%\rustup-init.exe" -y --default-toolchain stable
    if errorlevel 1 (
        echo ERROR: Rust installation failed.
        echo   Please install manually from https://rustup.rs
        exit /b 1
    )
    call :add_to_path "%USERPROFILE%\.cargo\bin"
    call :refresh_path
)
where rustc >nul 2>&1
if errorlevel 1 (
    echo ERROR: Rust installed but not in PATH. Please restart terminal and re-run.
    set "NEED_RESTART=1"
    goto :check_restart
)
for /f "usebackq tokens=2" %%a in (`rustc --version`) do set "RUST_VER=%%a"
echo [OK] Rust !RUST_VER!

REM --- Visual Studio Build Tools (C++ workload for Rust) ---
where cl >nul 2>&1
if errorlevel 1 (
    if not exist "%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" (
        echo [MISSING] Visual Studio Build Tools — installing...
        echo   Downloading installer ^(this may take several minutes^)...
        powershell -Command "Invoke-WebRequest -Uri 'https://aka.ms/vs/17/release/vs_BuildTools.exe' -OutFile '%TEMP%\vs_BuildTools.exe'"
        "%TEMP%\vs_BuildTools.exe" --quiet --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended
        if errorlevel 1 (
            echo WARNING: VS Build Tools auto-install may have failed.
            echo   If the Tauri build fails later, install manually from:
            echo   https://visualstudio.microsoft.com/visual-cpp-build-tools/
            echo   Select "Desktop development with C++" workload.
            echo.
        ) else (
            echo [OK] VS Build Tools installed
            REM VS Build Tools sets up vcvarsall.bat — refresh PATH to pick up cl.exe
            call :refresh_path
        )
    ) else (
        echo [OK] VS Build Tools found
    )
) else (
    echo [OK] MSVC compiler found
)

REM --- WebView2 ---
set "WV2_FOUND=0"
reg query "HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" >nul 2>&1 && set "WV2_FOUND=1"
if "!WV2_FOUND!"=="0" (
    reg query "HKLM\SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}" >nul 2>&1 && set "WV2_FOUND=1"
)
if "!WV2_FOUND!"=="0" (
    echo [NOTE] WebView2 not detected — the NSIS installer will auto-install it for end users.
) else (
    echo [OK] WebView2 found
)

echo.
echo [OK] All prerequisites ready!
echo.

REM -------------------------------------------------------------------------
REM Step 2: Install project dependencies
REM -------------------------------------------------------------------------
echo [Step 2/7] Installing project dependencies...

cd /d "%BACKEND_DIR%"
uv sync --quiet 2>nul || uv sync
if errorlevel 1 (echo ERROR: Backend dependency install failed && exit /b 1)
echo [OK] Backend dependencies

cd /d "%PROJECT_ROOT%"
call pnpm install --silent 2>nul || call pnpm install
if errorlevel 1 (echo ERROR: Frontend dependency install failed && exit /b 1)
echo [OK] Frontend dependencies

REM -------------------------------------------------------------------------
REM Step 3: Ensure PyInstaller is available
REM -------------------------------------------------------------------------
echo.
echo [Step 3/7] Setting up PyInstaller...

cd /d "%BACKEND_DIR%"
uv run python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo Installing PyInstaller as dev dependency...
    uv add --dev pyinstaller
)
echo [OK] PyInstaller ready

REM -------------------------------------------------------------------------
REM Step 4: Build backend sidecar binary
REM -------------------------------------------------------------------------
echo.
echo [Step 4/7] Building backend sidecar binary ^(this may take a few minutes^)...

cd /d "%BACKEND_DIR%"
uv run pyinstaller financetracker.spec --clean --noconfirm
if errorlevel 1 (echo ERROR: PyInstaller build failed && exit /b 1)

if not exist "dist\financetracker-backend.exe" (
    echo ERROR: PyInstaller build failed — binary not found
    exit /b 1
)

if not exist "%BINARIES_DIR%" mkdir "%BINARIES_DIR%"
copy /Y "dist\financetracker-backend.exe" "%BINARIES_DIR%\financetracker-backend-%TARGET%.exe" >nul
if not exist "%BINARIES_DIR%\financetracker-backend-%TARGET%.exe" (
    echo ERROR: Failed to copy sidecar binary
    exit /b 1
)
echo [OK] Sidecar binary: financetracker-backend-%TARGET%.exe

REM -------------------------------------------------------------------------
REM Step 5: Build static frontend
REM -------------------------------------------------------------------------
echo.
echo [Step 5/7] Building static frontend...

cd /d "%PROJECT_ROOT%"
set "STATIC_EXPORT=true"
call pnpm --filter @finance-tracker/web build
if errorlevel 1 (echo ERROR: Frontend build failed && exit /b 1)

if not exist "%WEB_DIR%\out" (
    echo ERROR: Static export failed — out\ directory not found
    exit /b 1
)

if exist "%DESKTOP_DIR%\dist" rmdir /s /q "%DESKTOP_DIR%\dist"
xcopy /E /I /Q "%WEB_DIR%\out" "%DESKTOP_DIR%\dist" >nul
echo [OK] Static frontend copied

REM -------------------------------------------------------------------------
REM Step 6: Build Tauri installer
REM -------------------------------------------------------------------------
echo.
echo [Step 6/7] Building Tauri installer ^(this may take a few minutes on first run^)...

cd /d "%DESKTOP_DIR%"
call npx @tauri-apps/cli build
if errorlevel 1 (echo ERROR: Tauri build failed && exit /b 1)

REM -------------------------------------------------------------------------
REM Step 7: Done
REM -------------------------------------------------------------------------
echo.
echo ========================================
echo   Installer built successfully!
echo ========================================
echo.

set "BUNDLE_DIR=%DESKTOP_DIR%\src-tauri\target\release\bundle"

echo   MSI Installer:
for %%f in ("%BUNDLE_DIR%\msi\*.msi") do (
    echo     %%f
)
echo.

echo   NSIS Installer:
for %%f in ("%BUNDLE_DIR%\nsis\*.exe") do (
    echo     %%f
)
echo.

echo   To install: Double-click the .msi file or run the .exe installer
echo.

goto :end

REM -------------------------------------------------------------------------
REM Handle case where tools were installed but PATH refresh wasn't enough
REM -------------------------------------------------------------------------
:check_restart
if "!NEED_RESTART!"=="1" (
    echo.
    echo ========================================
    echo   Tools were installed but PATH needs a terminal restart.
    echo   Please close this terminal, open a new one, and re-run:
    echo     build-installer.bat
    echo   All installed tools will be found on the next run.
    echo ========================================
    exit /b 1
)

:end
endlocal
