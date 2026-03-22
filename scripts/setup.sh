#!/bin/bash
# =============================================================================
# FinanceTracker — First-Time Setup Script (macOS / Linux)
# Run this once to set up the project for the first time
# =============================================================================

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"

echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  FinanceTracker — First-Time Setup${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
echo ""

# Install uv if not present
if ! command -v uv &>/dev/null; then
    echo -e "${YELLOW}Installing uv package manager...${NC}"
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
fi

# Install pnpm if not present
if ! command -v pnpm &>/dev/null; then
    echo -e "${YELLOW}Installing pnpm...${NC}"
    npm install -g pnpm 2>/dev/null || corepack enable pnpm 2>/dev/null
fi

# Backend setup
echo -e "${YELLOW}Setting up backend...${NC}"
cd "$BACKEND_DIR"

# Create .env from example
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    cp .env.example .env
    echo -e "  ${GREEN}✓${NC} Created .env from template"
fi

# Install Python dependencies
uv sync
echo -e "  ${GREEN}✓${NC} Python dependencies installed"

# Run initial migrations
if [ -f "alembic.ini" ]; then
    uv run alembic upgrade head
    echo -e "  ${GREEN}✓${NC} Database initialized"
fi

# Frontend setup
cd "$PROJECT_DIR"
if [ -f "pnpm-workspace.yaml" ]; then
    echo -e "${YELLOW}Setting up frontend...${NC}"
    pnpm install
    echo -e "  ${GREEN}✓${NC} Frontend dependencies installed"
fi

echo ""
echo -e "${GREEN}Setup complete!${NC}"
echo ""
echo "Next steps:"
echo "  1. Edit backend/.env with your API keys (optional)"
echo "  2. Run ./scripts/start.sh to launch everything"
echo ""
