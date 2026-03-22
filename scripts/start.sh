#!/bin/bash
# =============================================================================
# FinanceTracker — Start Script (macOS / Linux)
# Checks prerequisites, installs dependencies, stops existing services, starts all
# =============================================================================

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$PROJECT_DIR/backend"
WEB_DIR="$PROJECT_DIR/apps/web"
PID_DIR="$PROJECT_DIR/.pids"

mkdir -p "$PID_DIR"

echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  FinanceTracker — Setup & Launch${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
echo ""

# ── Helper Functions ─────────────────────────────────────────────────────────

check_command() {
    if command -v "$1" &> /dev/null; then
        return 0
    else
        return 1
    fi
}

check_version() {
    local cmd="$1"
    local required="$2"
    local current
    current=$($cmd --version 2>/dev/null | head -1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
    if [ -z "$current" ]; then
        return 1
    fi
    local current_major current_minor required_major required_minor
    current_major=$(echo "$current" | cut -d. -f1)
    current_minor=$(echo "$current" | cut -d. -f2)
    required_major=$(echo "$required" | cut -d. -f1)
    required_minor=$(echo "$required" | cut -d. -f2)
    if [ "$current_major" -gt "$required_major" ] || \
       ([ "$current_major" -eq "$required_major" ] && [ "$current_minor" -ge "$required_minor" ]); then
        return 0
    fi
    return 1
}

kill_if_running() {
    local name="$1"
    local pid_file="$PID_DIR/$name.pid"
    if [ -f "$pid_file" ]; then
        local pid
        pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            echo -e "  Stopping $name (PID $pid)..."
            kill "$pid" 2>/dev/null || true
            sleep 1
            kill -9 "$pid" 2>/dev/null || true
        fi
        rm -f "$pid_file"
    fi
    # Also try to kill by process name
    pkill -f "$name" 2>/dev/null || true
}

# ── Step 1: Check Prerequisites ─────────────────────────────────────────────

echo -e "${YELLOW}[1/6] Checking prerequisites...${NC}"

MISSING=()

# Python 3.12+
if check_command python3 && check_version python3 "3.12"; then
    PYTHON_VER=$(python3 --version 2>&1)
    echo -e "  ${GREEN}✓${NC} $PYTHON_VER"
else
    echo -e "  ${RED}✗${NC} Python 3.12+ not found"
    MISSING+=("Python 3.12+ (https://www.python.org/downloads/)")
fi

# uv
if check_command uv; then
    UV_VER=$(uv --version 2>&1)
    echo -e "  ${GREEN}✓${NC} $UV_VER"
else
    echo -e "  ${YELLOW}⚠${NC} uv not found — installing..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.cargo/bin:$PATH"
    if check_command uv; then
        echo -e "  ${GREEN}✓${NC} uv installed successfully"
    else
        MISSING+=("uv (https://docs.astral.sh/uv/)")
    fi
fi

# Node.js 20+
if check_command node && check_version node "20.0"; then
    NODE_VER=$(node --version 2>&1)
    echo -e "  ${GREEN}✓${NC} Node.js $NODE_VER"
else
    echo -e "  ${RED}✗${NC} Node.js 20+ not found"
    MISSING+=("Node.js 20+ (https://nodejs.org/)")
fi

# pnpm
if check_command pnpm; then
    PNPM_VER=$(pnpm --version 2>&1)
    echo -e "  ${GREEN}✓${NC} pnpm $PNPM_VER"
else
    echo -e "  ${YELLOW}⚠${NC} pnpm not found — installing..."
    npm install -g pnpm 2>/dev/null || corepack enable pnpm 2>/dev/null
    if check_command pnpm; then
        echo -e "  ${GREEN}✓${NC} pnpm installed"
    else
        MISSING+=("pnpm (npm install -g pnpm)")
    fi
fi

# Redis (optional)
if check_command redis-server; then
    echo -e "  ${GREEN}✓${NC} Redis available"
    HAS_REDIS=true
else
    echo -e "  ${YELLOW}⚠${NC} Redis not found (using in-memory fallback)"
    HAS_REDIS=false
fi

# Ollama (optional)
if check_command ollama; then
    echo -e "  ${GREEN}✓${NC} Ollama available"
    HAS_OLLAMA=true
else
    echo -e "  ${YELLOW}⚠${NC} Ollama not found (AI features disabled)"
    HAS_OLLAMA=false
fi

# Exit if required tools missing
if [ ${#MISSING[@]} -gt 0 ]; then
    echo ""
    echo -e "${RED}Missing required tools:${NC}"
    for tool in "${MISSING[@]}"; do
        echo -e "  - $tool"
    done
    echo ""
    echo "Please install the missing tools and try again."
    exit 1
fi

# ── Step 2: Install Dependencies ────────────────────────────────────────────

echo ""
echo -e "${YELLOW}[2/6] Installing dependencies...${NC}"

# Backend (Python via uv)
echo "  Installing backend dependencies..."
cd "$BACKEND_DIR"
uv sync 2>&1 | tail -1
echo -e "  ${GREEN}✓${NC} Backend dependencies installed"

# Frontend (JS via pnpm)
cd "$PROJECT_DIR"
if [ -f "pnpm-workspace.yaml" ]; then
    echo "  Installing frontend dependencies..."
    pnpm install --frozen-lockfile 2>/dev/null || pnpm install 2>&1 | tail -1
    echo -e "  ${GREEN}✓${NC} Frontend dependencies installed"
fi

# ── Step 3: Setup Database ──────────────────────────────────────────────────

echo ""
echo -e "${YELLOW}[3/6] Setting up database...${NC}"

cd "$BACKEND_DIR"
if [ ! -f ".env" ] && [ -f ".env.example" ]; then
    cp .env.example .env
    echo -e "  ${GREEN}✓${NC} Created .env from .env.example"
fi

# Run migrations if alembic is configured
if [ -f "alembic.ini" ]; then
    uv run alembic upgrade head 2>&1 | tail -1
    echo -e "  ${GREEN}✓${NC} Database migrations applied"
else
    echo -e "  ${YELLOW}⚠${NC} Alembic not configured yet — tables created on startup"
fi

# ── Step 4: Stop Existing Services ──────────────────────────────────────────

echo ""
echo -e "${YELLOW}[4/6] Stopping existing services...${NC}"

kill_if_running "uvicorn"
kill_if_running "celery"
# Kill any existing Next.js dev server on port 3000
lsof -ti:3000 2>/dev/null | xargs kill -9 2>/dev/null || true
# Kill any existing uvicorn on port 8000
lsof -ti:8000 2>/dev/null | xargs kill -9 2>/dev/null || true

echo -e "  ${GREEN}✓${NC} Existing services stopped"

# ── Step 5: Start Services ──────────────────────────────────────────────────

echo ""
echo -e "${YELLOW}[5/6] Starting services...${NC}"

# Start Redis (if available and not already running)
if [ "$HAS_REDIS" = true ]; then
    if ! redis-cli ping &>/dev/null; then
        redis-server --daemonize yes --loglevel warning 2>/dev/null
        echo -e "  ${GREEN}✓${NC} Redis started"
    else
        echo -e "  ${GREEN}✓${NC} Redis already running"
    fi
fi

# Start Ollama (if available and not already running)
if [ "$HAS_OLLAMA" = true ]; then
    if ! curl -s http://localhost:11434/api/tags &>/dev/null; then
        ollama serve &>/dev/null &
        echo "$!" > "$PID_DIR/ollama.pid"
        sleep 2
        echo -e "  ${GREEN}✓${NC} Ollama started"
    else
        echo -e "  ${GREEN}✓${NC} Ollama already running"
    fi
fi

# Start backend
cd "$BACKEND_DIR"
uv run uvicorn app.main:app --reload --port 8000 --host 0.0.0.0 &>/dev/null &
echo "$!" > "$PID_DIR/uvicorn.pid"
echo -e "  ${GREEN}✓${NC} Backend: http://localhost:8000"

# Start Celery (if Redis available)
if [ "$HAS_REDIS" = true ] && redis-cli ping &>/dev/null; then
    uv run celery -A app.tasks.celery_app worker --beat --loglevel=warning &>/dev/null &
    echo "$!" > "$PID_DIR/celery.pid"
    echo -e "  ${GREEN}✓${NC} Celery worker started"
fi

# Start web app (if it exists)
cd "$PROJECT_DIR"
if [ -d "$WEB_DIR" ] && [ -f "$WEB_DIR/package.json" ]; then
    cd "$WEB_DIR"
    pnpm dev &>/dev/null &
    echo "$!" > "$PID_DIR/nextjs.pid"
    echo -e "  ${GREEN}✓${NC} Web App: http://localhost:3000"
fi

# ── Step 6: Health Check ────────────────────────────────────────────────────

echo ""
echo -e "${YELLOW}[6/6] Running health check...${NC}"
sleep 3

echo ""
echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  Service Status${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"

# Backend
if curl -s http://localhost:8000/health &>/dev/null; then
    echo -e "  Backend:   ${GREEN}Running ✓${NC}  http://localhost:8000"
else
    echo -e "  Backend:   ${YELLOW}Starting...${NC}  http://localhost:8000"
fi

# Web App
if [ -d "$WEB_DIR" ] && [ -f "$WEB_DIR/package.json" ]; then
    echo -e "  Web App:   ${GREEN}Running ✓${NC}  http://localhost:3000"
fi

# API Docs
echo -e "  API Docs:  ${GREEN}Available${NC}  http://localhost:8000/docs"

# Redis
if [ "$HAS_REDIS" = true ] && redis-cli ping &>/dev/null; then
    echo -e "  Redis:     ${GREEN}Connected ✓${NC}"
else
    echo -e "  Redis:     ${YELLOW}Fallback mode ⚠${NC}"
fi

# Ollama
if [ "$HAS_OLLAMA" = true ] && curl -s http://localhost:11434/api/tags &>/dev/null; then
    echo -e "  Ollama:    ${GREEN}Connected ✓${NC}"
else
    echo -e "  Ollama:    ${YELLOW}Not available ⚠${NC}"
fi

echo ""
echo -e "${GREEN}FinanceTracker is running!${NC}"
echo ""
echo "  To stop:  ./scripts/stop.sh"
echo "  Logs:     Check individual service logs"
echo ""
