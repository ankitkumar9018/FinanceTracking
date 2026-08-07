#!/bin/bash
# =============================================================================
# FinanceTracker — Stop Script (macOS / Linux)
# Stops all running FinanceTracker services
# =============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_DIR="$PROJECT_DIR/.pids"

# Shared helpers: stop_by_pidfile (TERM, grace, KILL fallback, rm pidfile)
# (this script lives in scripts/, next to the library)
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib.sh"

echo -e "${BLUE}Stopping FinanceTracker services...${NC}"

stop_service() {
    local name="$1"
    local pid_file="$PID_DIR/$name.pid"
    if [ -f "$pid_file" ]; then
        local pid
        pid=$(cat "$pid_file" 2>/dev/null)
        if stop_by_pidfile "$pid_file" 1; then
            echo -e "  ${GREEN}✓${NC} Stopped $name (PID $pid)"
        else
            echo -e "  ${GREEN}✓${NC} $name was not running"
        fi
    fi
}

# Stop only OUR own services, by the exact PID we recorded when starting them.
# We deliberately do NOT kill by port or by bare process name — that would kill
# other apps (another uvicorn, another frontend on 3000, the app on 8000, ...).
stop_service "uvicorn"
stop_service "celery"
stop_service "nextjs"
stop_service "ollama"

rm -f "$PID_DIR/backend.port" "$PID_DIR/frontend.port"

echo ""
echo -e "${GREEN}All services stopped.${NC}"
