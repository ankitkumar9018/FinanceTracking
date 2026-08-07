#!/bin/bash
set -e

# ============================================================================
#  FinanceTracker - Single Script Launcher
#  Usage: ./run.sh [start|stop|restart|status|logs]
# ============================================================================

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
LOGS_DIR="$PROJECT_ROOT/logs"

# Shared helpers: find_free_port, wait_for_url, stop_by_pidfile
# (run.sh lives at the repo root; the library lives in scripts/)
source "$PROJECT_ROOT/scripts/lib.sh"

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[OK]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }
log_step() { echo -e "\n${CYAN}▶ $1${NC}"; }

# -----------------------------------------------------------------------------
# STOP function
# -----------------------------------------------------------------------------
do_stop() {
    echo -e "${YELLOW}Stopping FinanceTracker...${NC}"

    # Kill by PID files (stop_by_pidfile: TERM, grace, KILL fallback, rm pidfile)
    if [ -f "$LOGS_DIR/backend.pid" ]; then
        PID=$(cat "$LOGS_DIR/backend.pid")
        if stop_by_pidfile "$LOGS_DIR/backend.pid" 1; then
            log_success "Backend stopped (PID: $PID)"
        fi
    fi

    if [ -f "$LOGS_DIR/frontend.pid" ]; then
        PID=$(cat "$LOGS_DIR/frontend.pid")
        if stop_by_pidfile "$LOGS_DIR/frontend.pid" 1; then
            log_success "Frontend stopped (PID: $PID)"
        fi
    fi

    # We only ever stop our OWN processes (via the PID files above) — we never
    # kill by port, so a co-running app on 8000/3000/etc. is never touched.
    rm -f "$LOGS_DIR/backend.port" "$LOGS_DIR/frontend.port"

    echo -e "${GREEN}FinanceTracker stopped.${NC}"
}

# -----------------------------------------------------------------------------
# STATUS function
# -----------------------------------------------------------------------------
do_status() {
    echo -e "${CYAN}FinanceTracker Status${NC}"
    echo ""

    # Backend (read the actual chosen port from the runtime file)
    BPORT=$(cat "$LOGS_DIR/backend.port" 2>/dev/null || echo "")
    if [ -f "$LOGS_DIR/backend.pid" ] && kill -0 "$(cat "$LOGS_DIR/backend.pid" 2>/dev/null)" 2>/dev/null; then
        echo -e "  Backend:  ${GREEN}Running${NC} (PID: $(cat "$LOGS_DIR/backend.pid"))${BPORT:+ - http://localhost:$BPORT}"
    else
        echo -e "  Backend:  ${RED}Stopped${NC}"
    fi

    # Frontend
    FPORT=$(cat "$LOGS_DIR/frontend.port" 2>/dev/null || echo "")
    if [ -f "$LOGS_DIR/frontend.pid" ] && kill -0 "$(cat "$LOGS_DIR/frontend.pid" 2>/dev/null)" 2>/dev/null; then
        echo -e "  Frontend: ${GREEN}Running${NC} (PID: $(cat "$LOGS_DIR/frontend.pid"))${FPORT:+ - http://localhost:$FPORT}"
    else
        echo -e "  Frontend: ${RED}Stopped${NC}"
    fi
    echo ""
}

# -----------------------------------------------------------------------------
# LOGS function
# -----------------------------------------------------------------------------
do_logs() {
    if [ ! -d "$LOGS_DIR" ]; then
        log_error "No logs directory found. Start the app first."
        exit 1
    fi
    echo -e "${BLUE}Following logs (Ctrl+C to exit)...${NC}"
    tail -f "$LOGS_DIR/backend.log" "$LOGS_DIR/frontend.log" 2>/dev/null || log_error "No log files found"
}

# -----------------------------------------------------------------------------
# START function (main)
# -----------------------------------------------------------------------------
do_start() {
    clear 2>/dev/null || true
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║   FinanceTracker - One Click Launch    ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
    echo ""

    OS="$(uname -s)"
    ARCH="$(uname -m)"

    # -------------------------------------------------------------------------
    # Step 1: Install prerequisites
    # -------------------------------------------------------------------------
    log_step "Step 1/6: Checking & installing prerequisites..."

    install_homebrew() {
        if ! command -v brew &> /dev/null; then
            log_warn "Homebrew not found. Installing..."
            /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
            if [[ "$OS" == "Darwin" && "$ARCH" == "arm64" ]]; then
                eval "$(/opt/homebrew/bin/brew shellenv)"
            else
                eval "$(/usr/local/bin/brew shellenv)"
            fi
        fi
    }

    # Node.js
    if ! command -v node &> /dev/null; then
        log_warn "Node.js not found. Installing..."
        if [[ "$OS" == "Darwin" ]]; then
            install_homebrew
            brew install node@20
        elif [[ "$OS" == "Linux" ]]; then
            curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
            sudo apt-get install -y nodejs
        fi
    fi
    NODE_VERSION=$(node -v 2>/dev/null | cut -d'v' -f2 | cut -d'.' -f1 || echo "0")
    if [ "$NODE_VERSION" -lt 20 ]; then
        log_error "Node.js 20+ required. Please install: https://nodejs.org"
        exit 1
    fi
    log_success "Node.js $(node -v)"

    # pnpm
    if ! command -v pnpm &> /dev/null; then
        log_warn "pnpm not found. Installing..."
        npm install -g pnpm
    fi
    log_success "pnpm $(pnpm -v)"

    # Python
    PYTHON_CMD=""
    for cmd in python3.13 python3.12 python3; do
        if command -v $cmd &> /dev/null; then
            VER=$($cmd -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || echo "0")
            if [ "$VER" -ge 12 ]; then
                PYTHON_CMD=$cmd
                break
            fi
        fi
    done

    if [ -z "$PYTHON_CMD" ]; then
        log_warn "Python 3.12+ not found. Installing..."
        if [[ "$OS" == "Darwin" ]]; then
            install_homebrew
            brew install python@3.12
            PYTHON_CMD="python3.12"
        elif [[ "$OS" == "Linux" ]]; then
            sudo apt-get update && sudo apt-get install -y python3.12 python3.12-venv
            PYTHON_CMD="python3.12"
        fi
    fi
    PYTHON_VERSION=$($PYTHON_CMD -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    log_success "Python $PYTHON_VERSION"

    # uv
    if ! command -v uv &> /dev/null; then
        log_warn "uv not found. Installing..."
        curl -LsSf https://astral.sh/uv/install.sh | sh
        export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
    fi
    log_success "uv $(uv --version 2>/dev/null | cut -d' ' -f2 || echo 'installed')"

    # -------------------------------------------------------------------------
    # Step 2: Stop existing processes
    # -------------------------------------------------------------------------
    log_step "Step 2/6: Stopping any previous FinanceTracker instance..."

    # Only stop OUR own previous run (via PID files). We never kill by port, so
    # co-running apps (e.g. on 8000 or 3000) are never touched.
    for svc in backend frontend; do
        if [ -f "$LOGS_DIR/$svc.pid" ]; then
            OLDPID=$(cat "$LOGS_DIR/$svc.pid")
            if stop_by_pidfile "$LOGS_DIR/$svc.pid" 1; then
                log_warn "Stopped previous $svc (PID: $OLDPID)"
            fi
        fi
    done
    log_success "Ready to start (other apps left untouched)"

    # -------------------------------------------------------------------------
    # Step 3: Install dependencies
    # -------------------------------------------------------------------------
    log_step "Step 3/6: Installing dependencies..."

    cd "$BACKEND_DIR"
    log_info "Backend packages..."
    uv sync --quiet 2>/dev/null || uv sync
    log_success "Backend ready"

    cd "$PROJECT_ROOT"
    log_info "Frontend packages..."
    pnpm install --silent 2>/dev/null || pnpm install
    log_success "Frontend ready"

    # -------------------------------------------------------------------------
    # Step 4: Setup environment & database
    # -------------------------------------------------------------------------
    log_step "Step 4/6: Setting up environment..."

    cd "$BACKEND_DIR"

    if [ ! -f ".env" ]; then
        if [ -f ".env.example" ]; then
            cp .env.example .env
            SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || openssl rand -hex 32 2>/dev/null || echo "dev-secret-$(date +%s)")
            if [[ "$OS" == "Darwin" ]]; then
                sed -i '' "s/^SECRET_KEY=.*/SECRET_KEY=$SECRET_KEY/" .env 2>/dev/null || true
            else
                sed -i "s/^SECRET_KEY=.*/SECRET_KEY=$SECRET_KEY/" .env 2>/dev/null || true
            fi
            log_success ".env created with secure secret key"
        else
            cat > .env << EOF
DATABASE_URL=sqlite+aiosqlite:///./finance_tracker.db
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || openssl rand -hex 32 2>/dev/null || echo "dev-secret-$(date +%s)")
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7
ENVIRONMENT=development
EOF
            log_success ".env created"
        fi
    else
        log_success ".env exists"
    fi

    log_info "Running database migrations..."
    # Do NOT hide a failed migration behind the pipe or `|| true`: starting the
    # backend on a broken/partial schema causes confusing runtime errors. Capture
    # alembic's output AND its real exit code, and abort startup on failure.
    if migration_output=$(uv run python -c "from app.__main__ import _run_migrations; _run_migrations()" 2>&1); then
        echo "$migration_output" | grep -E "^(Running|INFO)" | head -3 || true
        log_success "Database ready"
    else
        alembic_status=$?
        log_error "Database migration failed (alembic exit $alembic_status). Aborting startup."
        echo "$migration_output" | tail -20
        exit 1
    fi

    # -------------------------------------------------------------------------
    # Step 5: Start services
    # -------------------------------------------------------------------------
    log_step "Step 5/6: Starting services..."

    mkdir -p "$LOGS_DIR"

    # Auto-pick free ports for BOTH services (prefers 8420 / 3000, but never
    # steals a port another app is using — falls through automatically).
    BACKEND_PORT=$(find_free_port 8420 8421 8422 8423 8424 8425 8426 8427 8428 8429)
    FRONTEND_PORT=$(find_free_port 3000 3001 3002 3003 3004 3005)
    echo "$BACKEND_PORT" > "$LOGS_DIR/backend.port"
    echo "$FRONTEND_PORT" > "$LOGS_DIR/frontend.port"

    # Backend — on the chosen port; CORS allows the chosen frontend origin
    cd "$BACKEND_DIR"
    log_info "Starting backend on port $BACKEND_PORT..."
    CORS_ORIGINS="http://localhost:$FRONTEND_PORT,http://localhost:3000,http://localhost:1420,https://tauri.localhost" \
        uv run uvicorn app.main:app --host 127.0.0.1 --port "$BACKEND_PORT" > "$LOGS_DIR/backend.log" 2>&1 &
    BACKEND_PID=$!
    echo $BACKEND_PID > "$LOGS_DIR/backend.pid"

    if wait_for_url "http://localhost:$BACKEND_PORT/health" 40 0.5; then
        log_success "Backend running on port $BACKEND_PORT (PID: $BACKEND_PID)"
    else
        log_warn "Backend still starting on port $BACKEND_PORT..."
    fi

    # Frontend — on the chosen port; pointed at the backend we just started
    cd "$PROJECT_ROOT"
    log_info "Starting frontend on port $FRONTEND_PORT..."
    PORT="$FRONTEND_PORT" \
    NEXT_PUBLIC_API_URL="http://localhost:$BACKEND_PORT/api/v1" \
    NEXT_PUBLIC_WS_URL="ws://localhost:$BACKEND_PORT" \
        pnpm --filter @finance-tracker/web dev > "$LOGS_DIR/frontend.log" 2>&1 &
    FRONTEND_PID=$!
    echo $FRONTEND_PID > "$LOGS_DIR/frontend.pid"

    if wait_for_url "http://localhost:$FRONTEND_PORT" 40 0.5; then
        log_success "Frontend running on port $FRONTEND_PORT (PID: $FRONTEND_PID)"
    else
        log_warn "Frontend still starting on port $FRONTEND_PORT..."
    fi

    # -------------------------------------------------------------------------
    # Step 6: Done!
    # -------------------------------------------------------------------------
    log_step "Step 6/6: Ready!"

    sleep 1

    # Open browser
    if [[ "$OS" == "Darwin" ]]; then
        open "http://localhost:$FRONTEND_PORT" 2>/dev/null &
    elif command -v xdg-open &> /dev/null; then
        xdg-open "http://localhost:$FRONTEND_PORT" 2>/dev/null &
    fi

    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║     FinanceTracker is now running!     ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
    echo ""
    echo -e "  ${CYAN}🌐 App:${NC}      http://localhost:$FRONTEND_PORT"
    echo -e "  ${CYAN}🔌 API:${NC}      http://localhost:$BACKEND_PORT"
    echo -e "  ${CYAN}📚 Docs:${NC}     http://localhost:$BACKEND_PORT/docs"
    echo ""
    echo -e "  ${YELLOW}Commands:${NC}"
    echo -e "     ./run.sh stop     Stop all services"
    echo -e "     ./run.sh status   Check service status"
    echo -e "     ./run.sh logs     Follow logs"
    echo -e "     ./run.sh restart  Restart everything"
    echo ""
}

# -----------------------------------------------------------------------------
# Main - Parse command
# -----------------------------------------------------------------------------
case "${1:-start}" in
    start)
        do_start
        ;;
    stop)
        do_stop
        ;;
    restart)
        do_stop
        sleep 2
        do_start
        ;;
    status)
        do_status
        ;;
    logs)
        do_logs
        ;;
    *)
        echo "Usage: ./run.sh [start|stop|restart|status|logs]"
        echo ""
        echo "  start    Install deps, setup DB, and start app (default)"
        echo "  stop     Stop all services"
        echo "  restart  Stop and start again"
        echo "  status   Show running status"
        echo "  logs     Follow log output"
        exit 1
        ;;
esac
