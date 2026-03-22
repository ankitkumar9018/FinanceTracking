#!/bin/bash
set -e

# Build the FinanceTracker backend as a PyInstaller binary for Tauri sidecar.
# The output is placed in apps/desktop/src-tauri/binaries/ with the correct
# target-triple suffix that Tauri expects.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BINARIES_DIR="$PROJECT_ROOT/apps/desktop/src-tauri/binaries"

cd "$SCRIPT_DIR"

# Detect target triple
OS="$(uname -s)"
ARCH="$(uname -m)"

case "$OS" in
    Darwin)
        case "$ARCH" in
            arm64) TARGET="aarch64-apple-darwin" ;;
            x86_64) TARGET="x86_64-apple-darwin" ;;
            *) echo "Unsupported arch: $ARCH"; exit 1 ;;
        esac
        ;;
    Linux)
        case "$ARCH" in
            x86_64) TARGET="x86_64-unknown-linux-gnu" ;;
            aarch64) TARGET="aarch64-unknown-linux-gnu" ;;
            *) echo "Unsupported arch: $ARCH"; exit 1 ;;
        esac
        ;;
    *)
        echo "Unsupported OS: $OS (use build_sidecar.bat on Windows)"
        exit 1
        ;;
esac

echo "Building sidecar for target: $TARGET"

# Ensure PyInstaller is available (it's a dev dependency in pyproject.toml)
uv run python -c "import PyInstaller" 2>/dev/null || uv add --dev pyinstaller

# Run PyInstaller
uv run pyinstaller financetracker.spec --clean --noconfirm 2>&1 | tail -5

# Create binaries directory
mkdir -p "$BINARIES_DIR"

# Copy with target-triple suffix
BINARY_NAME="financetracker-backend-$TARGET"
cp "dist/financetracker-backend" "$BINARIES_DIR/$BINARY_NAME"
chmod +x "$BINARIES_DIR/$BINARY_NAME"

echo ""
echo "Sidecar built: $BINARIES_DIR/$BINARY_NAME"
echo "Size: $(du -h "$BINARIES_DIR/$BINARY_NAME" | cut -f1)"
