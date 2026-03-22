#!/bin/bash
set -e

# ============================================================================
#  FinanceTracker — Build Installer
#  Creates a native installer for the current platform:
#    macOS  → .dmg + .app
#    Linux  → .AppImage + .deb
#    Windows → use build-installer.bat instead
#
#  Usage: ./build-installer.sh
#  Auto-installs missing prerequisites: Node.js, pnpm, Python, uv, Rust
# ============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
WEB_DIR="$PROJECT_ROOT/apps/web"
DESKTOP_DIR="$PROJECT_ROOT/apps/desktop"
BINARIES_DIR="$DESKTOP_DIR/src-tauri/binaries"

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "\n${CYAN}▶ $1${NC}"; }
log_install() { echo -e "${YELLOW}[MISSING]${NC} $1 — installing..."; }

# Detect platform and target triple
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Darwin)
        case "$ARCH" in
            arm64)  TARGET="aarch64-apple-darwin" ;;
            x86_64) TARGET="x86_64-apple-darwin" ;;
            *)      log_error "Unsupported architecture: $ARCH"; exit 1 ;;
        esac
        PLATFORM="macOS"
        ;;
    Linux)
        case "$ARCH" in
            x86_64)  TARGET="x86_64-unknown-linux-gnu" ;;
            aarch64) TARGET="aarch64-unknown-linux-gnu" ;;
            *)       log_error "Unsupported architecture: $ARCH"; exit 1 ;;
        esac
        PLATFORM="Linux"
        ;;
    *)
        log_error "Unsupported OS: $OS. Use build-installer.bat on Windows."
        exit 1
        ;;
esac

clear 2>/dev/null || true
echo ""
echo -e "${GREEN}╔════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  FinanceTracker — Installer Builder        ║${NC}"
echo -e "${GREEN}║  Platform: $PLATFORM ($ARCH)$(printf '%*s' $((22 - ${#PLATFORM} - ${#ARCH})) '')║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════╝${NC}"
echo ""

# -------------------------------------------------------------------------
# Helper: reload PATH from shell profile
# -------------------------------------------------------------------------
reload_path() {
    # Source common profile files to pick up newly installed tools
    for f in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile" "$HOME/.bash_profile" "$HOME/.zprofile"; do
        [ -f "$f" ] && source "$f" 2>/dev/null || true
    done
    # Also add common install locations directly
    export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$HOME/.nvm/versions/node/$(ls "$HOME/.nvm/versions/node/" 2>/dev/null | sort -V | tail -1)/bin:/opt/homebrew/bin:/usr/local/bin:$PATH" 2>/dev/null || true
}

# -------------------------------------------------------------------------
# Helper: add directory to shell PATH permanently
# -------------------------------------------------------------------------
add_to_path() {
    local dir="$1"
    export PATH="$dir:$PATH"

    # Persist to shell config
    local shell_rc=""
    if [ -n "$ZSH_VERSION" ] || [ "$(basename "$SHELL")" = "zsh" ]; then
        shell_rc="$HOME/.zshrc"
    else
        shell_rc="$HOME/.bashrc"
    fi

    if [ -f "$shell_rc" ]; then
        if ! grep -qF "$dir" "$shell_rc" 2>/dev/null; then
            echo "export PATH=\"$dir:\$PATH\"" >> "$shell_rc"
            echo "  [PATH] Added $dir to $shell_rc"
        fi
    fi
}

# -------------------------------------------------------------------------
# Step 1: Check and auto-install prerequisites
# -------------------------------------------------------------------------
log_step "Step 1/7: Checking prerequisites (will auto-install if missing)..."

# --- Node.js ---
if ! command -v node &>/dev/null; then
    log_install "Node.js"
    if [ "$OS" = "Darwin" ]; then
        if command -v brew &>/dev/null; then
            brew install node@20
            brew link --overwrite node@20 2>/dev/null || true
        else
            log_info "Installing Homebrew first..."
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
            # Add Homebrew to PATH for Apple Silicon
            if [ "$ARCH" = "arm64" ]; then
                add_to_path "/opt/homebrew/bin"
                eval "$(/opt/homebrew/bin/brew shellenv)"
            fi
            brew install node@20
            brew link --overwrite node@20 2>/dev/null || true
        fi
    elif [ "$OS" = "Linux" ]; then
        # Use NodeSource for up-to-date Node.js
        if command -v apt-get &>/dev/null; then
            curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
            sudo apt-get install -y nodejs
        elif command -v dnf &>/dev/null; then
            curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo bash -
            sudo dnf install -y nodejs
        elif command -v pacman &>/dev/null; then
            sudo pacman -S --noconfirm nodejs npm
        else
            log_error "Cannot auto-install Node.js. Install manually: https://nodejs.org"
            exit 1
        fi
    fi
    reload_path
fi
if ! command -v node &>/dev/null; then
    log_error "Node.js install failed. Please install manually from https://nodejs.org"
    exit 1
fi
NODE_VER=$(node -v | cut -d'v' -f2 | cut -d'.' -f1)
if [ "$NODE_VER" -lt 20 ]; then
    log_error "Node.js 20+ required (found v$NODE_VER). Please update."
    exit 1
fi
log_success "Node.js $(node -v)"

# --- pnpm ---
if ! command -v pnpm &>/dev/null; then
    log_install "pnpm"
    npm install -g pnpm 2>/dev/null || {
        log_info "npm global install failed, trying standalone..."
        curl -fsSL https://get.pnpm.io/install.sh | sh -
        add_to_path "$HOME/.local/share/pnpm"
        reload_path
    }
fi
if ! command -v pnpm &>/dev/null; then
    log_error "pnpm install failed. Run: npm install -g pnpm"
    exit 1
fi
log_success "pnpm $(pnpm -v)"

# --- Python 3.12+ ---
PYTHON_CMD=""
for cmd in python3.13 python3.12 python3; do
    if command -v $cmd &>/dev/null; then
        VER=$($cmd -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || echo "0")
        if [ "$VER" -ge 12 ]; then
            PYTHON_CMD=$cmd
            break
        fi
    fi
done
if [ -z "$PYTHON_CMD" ]; then
    log_install "Python 3.12+"
    if [ "$OS" = "Darwin" ]; then
        brew install python@3.13
        brew link --overwrite python@3.13 2>/dev/null || true
    elif [ "$OS" = "Linux" ]; then
        if command -v apt-get &>/dev/null; then
            sudo apt-get update
            sudo apt-get install -y python3.12 python3.12-venv python3-pip 2>/dev/null || \
            sudo apt-get install -y python3 python3-venv python3-pip
        elif command -v dnf &>/dev/null; then
            sudo dnf install -y python3.12 python3-pip 2>/dev/null || \
            sudo dnf install -y python3 python3-pip
        elif command -v pacman &>/dev/null; then
            sudo pacman -S --noconfirm python python-pip
        fi
    fi
    reload_path
    # Re-detect
    for cmd in python3.13 python3.12 python3; do
        if command -v $cmd &>/dev/null; then
            VER=$($cmd -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || echo "0")
            if [ "$VER" -ge 12 ]; then
                PYTHON_CMD=$cmd
                break
            fi
        fi
    done
fi
if [ -z "$PYTHON_CMD" ]; then
    log_error "Python 3.12+ is required. Please install manually."
    exit 1
fi
log_success "Python $($PYTHON_CMD --version 2>&1 | cut -d' ' -f2)"

# --- uv ---
if ! command -v uv &>/dev/null; then
    log_install "uv"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    add_to_path "$HOME/.local/bin"
    reload_path
fi
if ! command -v uv &>/dev/null; then
    log_error "uv install failed. Run: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi
log_success "uv $(uv --version 2>/dev/null | head -1)"

# --- Rust ---
if ! command -v rustc &>/dev/null; then
    log_install "Rust"
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
    add_to_path "$HOME/.cargo/bin"
    source "$HOME/.cargo/env" 2>/dev/null || true
    reload_path
fi
if ! command -v rustc &>/dev/null; then
    log_error "Rust install failed. Install from https://rustup.rs"
    exit 1
fi
log_success "Rust $(rustc --version | cut -d' ' -f2)"

# --- Linux system deps for Tauri ---
if [ "$OS" = "Linux" ]; then
    MISSING_PKGS=""
    for pkg in libwebkit2gtk-4.1-dev libappindicator3-dev librsvg2-dev patchelf; do
        if ! dpkg -s "$pkg" &>/dev/null 2>&1; then
            MISSING_PKGS="$MISSING_PKGS $pkg"
        fi
    done
    if [ -n "$MISSING_PKGS" ]; then
        log_install "Linux system packages:$MISSING_PKGS"
        sudo apt-get update
        sudo apt-get install -y $MISSING_PKGS
        log_success "System packages installed"
    else
        log_success "Linux system packages present"
    fi
fi

echo ""
log_success "All prerequisites ready!"

# -------------------------------------------------------------------------
# Step 2: Install dependencies
# -------------------------------------------------------------------------
log_step "Step 2/7: Installing dependencies..."

cd "$BACKEND_DIR"
uv sync --quiet 2>/dev/null || uv sync
log_success "Backend dependencies installed"

cd "$PROJECT_ROOT"
pnpm install --silent 2>/dev/null || pnpm install
log_success "Frontend dependencies installed"

# -------------------------------------------------------------------------
# Step 3: Install PyInstaller
# -------------------------------------------------------------------------
log_step "Step 3/7: Setting up PyInstaller..."

cd "$BACKEND_DIR"
uv run python -c "import PyInstaller" 2>/dev/null || uv add --dev pyinstaller
log_success "PyInstaller ready"

# -------------------------------------------------------------------------
# Step 4: Build backend sidecar binary
# -------------------------------------------------------------------------
log_step "Step 4/7: Building backend sidecar binary (this may take a few minutes)..."

cd "$BACKEND_DIR"
uv run pyinstaller financetracker.spec --clean --noconfirm 2>&1 | grep -E "^(INFO|WARNING|Building|$)" | head -20

if [ ! -f "dist/financetracker-backend" ]; then
    log_error "PyInstaller build failed — binary not found"
    exit 1
fi

mkdir -p "$BINARIES_DIR"
BINARY_NAME="financetracker-backend-$TARGET"
cp "dist/financetracker-backend" "$BINARIES_DIR/$BINARY_NAME"
chmod +x "$BINARIES_DIR/$BINARY_NAME"

BINARY_SIZE=$(du -h "$BINARIES_DIR/$BINARY_NAME" | cut -f1)
log_success "Sidecar binary: $BINARY_NAME ($BINARY_SIZE)"

# -------------------------------------------------------------------------
# Step 5: Build static frontend
# -------------------------------------------------------------------------
log_step "Step 5/7: Building static frontend..."

cd "$PROJECT_ROOT"
STATIC_EXPORT=true pnpm --filter @finance-tracker/web build 2>&1 | grep -E "(Route|First Load|Exporting|Error)" | head -5

if [ ! -d "$WEB_DIR/out" ]; then
    log_error "Static export failed — out/ directory not found"
    exit 1
fi

rm -rf "$DESKTOP_DIR/dist"
cp -r "$WEB_DIR/out" "$DESKTOP_DIR/dist"

FRONTEND_SIZE=$(du -sh "$DESKTOP_DIR/dist" | cut -f1)
log_success "Static frontend: $FRONTEND_SIZE"

# -------------------------------------------------------------------------
# Step 6: Build Tauri installer
# -------------------------------------------------------------------------
log_step "Step 6/7: Building Tauri installer (this may take a few minutes on first run)..."

cd "$DESKTOP_DIR"
npx @tauri-apps/cli build 2>&1 | grep -E "(Compiling finance-tracker|Finished|Bundling|Built|Error|error)" | head -10

# -------------------------------------------------------------------------
# Step 7: Done — show output
# -------------------------------------------------------------------------
log_step "Step 7/7: Build complete!"

BUNDLE_DIR="$DESKTOP_DIR/src-tauri/target/release/bundle"
echo ""
echo -e "${GREEN}╔════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Installer built successfully!            ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════╝${NC}"
echo ""

if [ "$OS" = "Darwin" ]; then
    echo -e "  ${CYAN}App:${NC}"
    APP_PATH=$(find "$BUNDLE_DIR/macos" -name "*.app" -maxdepth 1 2>/dev/null | head -1)
    if [ -n "$APP_PATH" ]; then
        echo -e "    $APP_PATH"
    fi
    echo ""
    echo -e "  ${CYAN}Installer:${NC}"
    DMG_PATH=$(find "$BUNDLE_DIR/dmg" -name "*.dmg" -maxdepth 1 2>/dev/null | head -1)
    if [ -n "$DMG_PATH" ]; then
        DMG_SIZE=$(du -h "$DMG_PATH" | cut -f1)
        echo -e "    $DMG_PATH ($DMG_SIZE)"
    fi
elif [ "$OS" = "Linux" ]; then
    echo -e "  ${CYAN}Installers:${NC}"
    for f in $(find "$BUNDLE_DIR" -name "*.AppImage" -o -name "*.deb" 2>/dev/null); do
        FSIZE=$(du -h "$f" | cut -f1)
        echo -e "    $f ($FSIZE)"
    done
fi

echo ""
echo -e "  ${YELLOW}To install:${NC}"
if [ "$OS" = "Darwin" ]; then
    echo -e "    Double-click the .dmg file, drag FinanceTracker to Applications"
    echo -e "    Or run: open \"$APP_PATH\""
elif [ "$OS" = "Linux" ]; then
    echo -e "    chmod +x *.AppImage && ./*.AppImage"
    echo -e "    Or: sudo dpkg -i *.deb"
fi
echo ""
