# Desktop App — Build & Development Guide

FinanceTracker ships as a native desktop app built with **Tauri v2**. It bundles the Next.js frontend as a static export and a PyInstaller-compiled Python backend as a sidecar binary. The result is a lightweight native app (5-10 MB) that runs on macOS, Windows, and Linux.

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Prerequisites](#prerequisites)
3. [Quick Build (One Command)](#quick-build-one-command)
4. [Step-by-Step Manual Build](#step-by-step-manual-build)
5. [Development Mode](#development-mode)
6. [How the Desktop App Works](#how-the-desktop-app-works)
7. [Platform-Specific Details](#platform-specific-details)
8. [CI/CD Automated Builds](#cicd-automated-builds)
9. [Troubleshooting](#troubleshooting)
10. [File Structure Reference](#file-structure-reference)

---

## Architecture Overview

```
+-------------------------------------------------------+
|  Tauri Shell (native window, system tray, menus)      |
|  - Rust binary (~3 MB)                                |
|  - Uses OS webview (WebKit/WebView2/WebKitGTK)        |
|                                                        |
|  +--------------------------------------------------+ |
|  |  Static Frontend (Next.js export)                 | |
|  |  - HTML/CSS/JS served from local files            | |
|  |  - Connects to localhost:PORT for API             | |
|  +--------------------------------------------------+ |
|                                                        |
|  +--------------------------------------------------+ |
|  |  Backend Sidecar (PyInstaller binary)             | |
|  |  - FastAPI server on 127.0.0.1:random_port        | |
|  |  - SQLite database in app data directory          | |
|  |  - Spawned/killed by Tauri lifecycle              | |
|  +--------------------------------------------------+ |
+-------------------------------------------------------+
```

**Key design decisions:**
- The backend binds to `127.0.0.1` only (not exposed to network)
- CORS is set to `*` in sidecar mode (safe because local-only)
- The port is dynamically assigned and injected into the frontend
- The SQLite database lives in the OS app data directory
- All ML/heavy dependencies are excluded (graceful degradation)

---

## Prerequisites

You need these 5 tools installed before building:

| Tool | Version | Install |
|------|---------|---------|
| **Node.js** | 20+ | https://nodejs.org |
| **pnpm** | 9+ | `npm install -g pnpm` |
| **Python** | 3.12+ | https://python.org |
| **uv** | latest | macOS/Linux: `curl -LsSf https://astral.sh/uv/install.sh \| sh`<br>Windows: `powershell -c "irm https://astral.sh/uv/install.ps1 \| iex"` |
| **Rust** | stable | https://rustup.rs |

**Linux only** — install system libraries:
```bash
sudo apt-get install -y libwebkit2gtk-4.1-dev libappindicator3-dev librsvg2-dev patchelf
```

---

## Quick Build (One Command)

The build-installer scripts handle everything automatically:

**macOS / Linux:**
```bash
./build-installer.sh
```

**Windows:**
```bat
build-installer.bat
```

These scripts perform all 7 steps (prerequisite check, dependency install, PyInstaller build, frontend export, Tauri build) and output the final installer.

**Output locations:**

| Platform | Installer Type | Path |
|----------|---------------|------|
| macOS | `.dmg` + `.app` | `apps/desktop/src-tauri/target/release/bundle/dmg/` |
| macOS | `.app` (direct) | `apps/desktop/src-tauri/target/release/bundle/macos/` |
| Windows | `.msi` | `apps/desktop/src-tauri/target/release/bundle/msi/` |
| Windows | `.exe` (NSIS) | `apps/desktop/src-tauri/target/release/bundle/nsis/` |
| Linux | `.AppImage` | `apps/desktop/src-tauri/target/release/bundle/appimage/` |
| Linux | `.deb` | `apps/desktop/src-tauri/target/release/bundle/deb/` |

---

## Step-by-Step Manual Build

If you prefer to run each step individually (useful for debugging):

### Step 1: Install backend dependencies

```bash
cd backend
uv sync
```

### Step 2: Install frontend dependencies

```bash
cd ..   # back to project root
pnpm install
```

### Step 3: Build the backend sidecar binary

The backend is compiled into a standalone binary using PyInstaller.

**macOS / Linux:**
```bash
cd backend
uv run pyinstaller financetracker.spec --clean --noconfirm
```

**Windows:**
```bat
cd backend
uv run pyinstaller financetracker.spec --clean --noconfirm
```

This produces:
- macOS/Linux: `backend/dist/financetracker-backend`
- Windows: `backend/dist/financetracker-backend.exe`

### Step 4: Copy sidecar to Tauri binaries directory

Tauri expects sidecar binaries named with the target triple suffix.

**macOS (Apple Silicon):**
```bash
mkdir -p apps/desktop/src-tauri/binaries
cp backend/dist/financetracker-backend apps/desktop/src-tauri/binaries/financetracker-backend-aarch64-apple-darwin
chmod +x apps/desktop/src-tauri/binaries/financetracker-backend-aarch64-apple-darwin
```

**macOS (Intel):**
```bash
cp backend/dist/financetracker-backend apps/desktop/src-tauri/binaries/financetracker-backend-x86_64-apple-darwin
chmod +x apps/desktop/src-tauri/binaries/financetracker-backend-x86_64-apple-darwin
```

**Windows (x64):**
```bat
mkdir apps\desktop\src-tauri\binaries
copy backend\dist\financetracker-backend.exe apps\desktop\src-tauri\binaries\financetracker-backend-x86_64-pc-windows-msvc.exe
```

**Windows (ARM64):**
```bat
copy backend\dist\financetracker-backend.exe apps\desktop\src-tauri\binaries\financetracker-backend-aarch64-pc-windows-msvc.exe
```

**Linux (x64):**
```bash
cp backend/dist/financetracker-backend apps/desktop/src-tauri/binaries/financetracker-backend-x86_64-unknown-linux-gnu
chmod +x apps/desktop/src-tauri/binaries/financetracker-backend-x86_64-unknown-linux-gnu
```

**Target triple reference:**

| Platform | Architecture | Target Triple |
|----------|-------------|---------------|
| macOS | Apple Silicon (M1/M2/M3/M4) | `aarch64-apple-darwin` |
| macOS | Intel | `x86_64-apple-darwin` |
| Windows | x64 | `x86_64-pc-windows-msvc` |
| Windows | ARM64 | `aarch64-pc-windows-msvc` |
| Linux | x64 | `x86_64-unknown-linux-gnu` |

### Step 5: Build the static frontend

The frontend is exported as static HTML/CSS/JS for embedding in Tauri.

```bash
cd ..   # back to project root
STATIC_EXPORT=true pnpm --filter @finance-tracker/web build
```

On Windows:
```bat
set STATIC_EXPORT=true
pnpm --filter @finance-tracker/web build
```

This creates `apps/web/out/` with the static export.

### Step 6: Copy frontend to Tauri dist

```bash
rm -rf apps/desktop/dist
cp -r apps/web/out apps/desktop/dist
```

On Windows:
```bat
if exist apps\desktop\dist rmdir /s /q apps\desktop\dist
xcopy /E /I /Q apps\web\out apps\desktop\dist
```

### Step 7: Build the Tauri installer

```bash
cd apps/desktop
npx @tauri-apps/cli build
```

This compiles the Rust shell, bundles the frontend and sidecar, and produces the platform-specific installer.

---

## Development Mode

For active development, use Tauri's dev mode which supports hot-reload:

```bash
# Terminal 1: Start backend
cd backend
uv run uvicorn app.main:app --reload --port 8000

# Terminal 2: Start Tauri dev (includes frontend dev server)
cd apps/desktop
pnpm tauri dev
```

In dev mode:
- The frontend runs via Next.js dev server (with HMR)
- The Tauri window points to `localhost:3000`
- The backend runs separately (not as a sidecar)
- Changes to Rust code trigger a Tauri rebuild
- Changes to frontend code hot-reload instantly

---

## How the Desktop App Works

### Startup sequence

1. Tauri launches the native window
2. The Rust code in `src-tauri/src/lib.rs` runs the `setup` hook
3. The setup hook:
   a. Resolves the app data directory (OS-specific)
   b. Creates the SQLite database path
   c. Finds a free port on localhost
   d. Spawns the sidecar binary with `--port PORT --db-path DB_PATH --seed`
   e. Waits for the backend to respond to health checks
   f. Injects the API port into the frontend via JavaScript
4. The frontend loads and connects to `http://localhost:PORT`

### Sidecar lifecycle

- **Spawned** on app start via Tauri's shell plugin
- **Monitored** — Tauri tracks the child process
- **Killed** on app close — Tauri's drop handler terminates the sidecar

### Database location

The SQLite database is stored in the OS app data directory:

| Platform | Path |
|----------|------|
| macOS | `~/Library/Application Support/com.financetracker.app/finance.db` |
| Windows | `C:\Users\<user>\AppData\Local\com.financetracker.app\finance.db` |
| Linux | `~/.local/share/com.financetracker.app/finance.db` |

### CORS handling

The sidecar sets `CORS_ORIGINS=*` because:
- The backend binds to `127.0.0.1` only (not network-accessible)
- Tauri webviews use different origin schemes per platform:
  - macOS (WKWebView): `tauri://localhost` or opaque `null`
  - Windows (WebView2): `https://tauri.localhost`
  - Linux (WebKitGTK): varies
- Wildcard CORS with `allow_credentials=False` works safely for local-only backends

---

## Platform-Specific Details

### macOS

- Uses WKWebView (built into macOS, no extra download)
- DMG installer includes drag-to-Applications layout
- Minimum macOS version: 10.15 (Catalina)
- Supports both Apple Silicon (ARM64) and Intel (x86_64)

**Code Signing & Notarization** (required for distribution):

1. Get a Developer ID certificate from [developer.apple.com](https://developer.apple.com)
2. Set the identity in `financetracker.spec`:
   ```python
   codesign_identity = "Developer ID Application: Your Name (TEAMID)"
   ```
3. Build the sidecar: `cd backend && ./build_sidecar.sh`
4. Sign the binary:
   ```bash
   codesign --force --options runtime --sign "Developer ID Application: Your Name (TEAMID)" \
     apps/desktop/src-tauri/binaries/financetracker-backend-aarch64-apple-darwin
   ```
5. Build the Tauri app: `cd apps/desktop && pnpm tauri build`
6. Notarize the DMG:
   ```bash
   xcrun notarytool submit target/release/bundle/dmg/FinanceTracker_*.dmg \
     --apple-id "you@example.com" --team-id "TEAMID" --password "@keychain:notary-password" \
     --wait
   xcrun stapler staple target/release/bundle/dmg/FinanceTracker_*.dmg
   ```

### Windows

- Uses WebView2 (Edge-based, pre-installed on Windows 10/11)
- The PyInstaller binary has `console=False` to prevent console window flash
- The `financetracker.spec` detects Windows and uses `Lib/site-packages` (not `lib/pythonX.Y/site-packages`)
- SQLite paths are normalized to forward slashes for URL compatibility
- Produces both `.msi` (Windows Installer) and `.exe` (NSIS) installers
- Supports both x64 and ARM64 architectures

**Prerequisites** (Windows-specific):
- **Visual Studio Build Tools 2022** — required for Rust compilation. Install with the "Desktop development with C++" workload from [visualstudio.microsoft.com/visual-cpp-build-tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)
- **PowerShell Execution Policy** — if scripts are blocked, run:
  ```powershell
  Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
  ```
- **WebView2 Runtime** — pre-installed on Windows 10/11. For Windows Server or LTSC editions, download from [developer.microsoft.com/en-us/microsoft-edge/webview2](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)

### Linux

- Uses WebKitGTK (must be installed as a system dependency)
- AppImage is self-contained and runs on most distros
- System tray requires `libappindicator3-dev` (or equivalent)

**Debian/Ubuntu:**
```bash
sudo apt-get install -y libwebkit2gtk-4.1-dev libappindicator3-dev librsvg2-dev patchelf
```

**Fedora/RHEL:**
```bash
sudo dnf install -y webkit2gtk4.1-devel libappindicator-gtk3-devel librsvg2-devel
```

**Arch Linux:**
```bash
sudo pacman -S webkit2gtk-4.1 libappindicator-gtk3 librsvg
```

### Database Backup

The SQLite database can be backed up by simply copying the file:

```bash
# macOS
cp ~/Library/Application\ Support/com.financetracker.app/finance.db ~/Desktop/finance-backup.db

# Windows (PowerShell)
Copy-Item "$env:LOCALAPPDATA\com.financetracker.app\finance.db" "$env:USERPROFILE\Desktop\finance-backup.db"

# Linux
cp ~/.local/share/com.financetracker.app/finance.db ~/finance-backup.db
```

To restore, replace the database file and restart the app.

---

## CI/CD Automated Builds

The GitHub Actions workflow `.github/workflows/release-desktop.yml` automatically builds installers for all platforms when a version tag is pushed.

### Trigger

```bash
git tag v1.0.0
git push origin v1.0.0
```

### Build matrix

| Runner | Target | Output |
|--------|--------|--------|
| `macos-latest` | `aarch64-apple-darwin` | `.dmg`, `.app` |
| `macos-latest` | `x86_64-apple-darwin` | `.dmg`, `.app` |
| `ubuntu-22.04` | `x86_64-unknown-linux-gnu` | `.AppImage`, `.deb` |
| `windows-latest` | `x86_64-pc-windows-msvc` | `.msi`, `.exe` |
| `windows-latest` | `aarch64-pc-windows-msvc` | `.msi`, `.exe` |

### What the CI does

1. Checks out code
2. Sets up Node.js 20, pnpm 9, Python 3.12, uv, Rust stable
3. Installs Linux system deps (Ubuntu only)
4. Installs backend deps (`uv sync`) + PyInstaller
5. Builds PyInstaller sidecar binary
6. Copies binary to `src-tauri/binaries/` with correct target triple suffix
7. Builds static frontend (`STATIC_EXPORT=true pnpm build`)
8. Copies static export to `apps/desktop/dist/`
9. Runs `tauri-action` which builds and creates a GitHub draft release with all installers attached

### Release artifacts

After the workflow completes, a draft release appears on GitHub with:
- macOS: `FinanceTracker_x.y.z_aarch64.dmg`, `FinanceTracker_x.y.z_x64.dmg`
- Windows: `FinanceTracker_x.y.z_x64-setup.exe`, `FinanceTracker_x.y.z_x64_en-US.msi`
- Linux: `FinanceTracker_x.y.z_amd64.AppImage`, `finance-tracker_x.y.z_amd64.deb`

---

## Troubleshooting

### Build fails: "failed to create sidecar command"

The sidecar binary is missing or has the wrong name. Ensure the binary in `apps/desktop/src-tauri/binaries/` matches the pattern `financetracker-backend-{TARGET_TRIPLE}[.exe]`.

Check your target triple:
```bash
rustc -vV | grep host
```

### Build fails: PyInstaller can't find dependencies

Ensure the venv exists and is populated:
```bash
cd backend && uv sync
```

The `financetracker.spec` file automatically detects the platform and uses the correct venv path.

### Windows: console window flashes briefly

This was fixed — the spec sets `console=False` on Windows. If you see this with an older build, rebuild the sidecar.

### Windows: database not created

Windows paths with backslashes are normalized to forward slashes in `__main__.py`. If you encounter SQLite URL errors, verify the path conversion is working:
```python
from pathlib import Path
print(Path("C:\\Users\\test\\finance.db").as_posix())
# Output: C:/Users/test/finance.db
```

### macOS: "FinanceTracker is damaged and can't be opened"

The app isn't code-signed. Bypass Gatekeeper:
```bash
xattr -cr /Applications/FinanceTracker.app
```

For distribution, configure code signing in the Tauri config.

### Linux: WebKitGTK not found

Install required system packages:
```bash
sudo apt-get install -y libwebkit2gtk-4.1-dev libappindicator3-dev librsvg2-dev patchelf
```

### Backend sidecar doesn't start

Check the sidecar binary runs standalone:
```bash
./apps/desktop/src-tauri/binaries/financetracker-backend-{TRIPLE} --port 9999 --db-path /tmp/test.db
# Should start and listen on http://127.0.0.1:9999
```

### Frontend shows blank page

Ensure the static export was copied correctly:
```bash
ls apps/desktop/dist/index.html
# Should exist
```

If missing, rebuild: `STATIC_EXPORT=true pnpm --filter @finance-tracker/web build && cp -r apps/web/out apps/desktop/dist`

---

## File Structure Reference

```
apps/desktop/
├── package.json              # Tauri CLI dependency
├── dist/                     # Static frontend (copied from apps/web/out)
│   ├── index.html
│   ├── dashboard.html
│   └── ...
└── src-tauri/
    ├── Cargo.toml            # Rust dependencies (tauri, plugins)
    ├── tauri.conf.json       # App config (name, window, externalBin)
    ├── capabilities/
    │   └── default.json      # Permissions (shell:spawn, notification)
    ├── binaries/
    │   └── financetracker-backend-{TRIPLE}[.exe]   # PyInstaller sidecar
    ├── icons/                # App icons (all sizes)
    └── src/
        ├── main.rs           # Entry point
        └── lib.rs            # Setup hook, sidecar spawn, port injection

backend/
├── financetracker.spec       # PyInstaller build spec (cross-platform)
├── build_sidecar.sh          # macOS/Linux sidecar build helper
├── build_sidecar.bat         # Windows sidecar build helper
└── app/
    └── __main__.py           # CLI entry point (--port, --db-path, --seed)

# Root level
├── build-installer.sh        # Full macOS/Linux installer builder (7 steps)
├── build-installer.bat       # Full Windows installer builder (7 steps)
└── .github/workflows/
    └── release-desktop.yml   # CI/CD for all-platform builds
```
