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

echo -e "${BLUE}Stopping FinanceTracker services...${NC}"

stop_service() {
    local name="$1"
    local pid_file="$PID_DIR/$name.pid"
    if [ -f "$pid_file" ]; then
        local pid
        pid=$(cat "$pid_file")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            sleep 1
            kill -9 "$pid" 2>/dev/null || true
            echo -e "  ${GREEN}✓${NC} Stopped $name (PID $pid)"
        else
            echo -e "  ${GREEN}✓${NC} $name was not running"
        fi
        rm -f "$pid_file"
    fi
}

# Stop application services
stop_service "uvicorn"
stop_service "celery"
stop_service "nextjs"
stop_service "ollama"

# Kill by port as backup
lsof -ti:8000 2>/dev/null | xargs kill -9 2>/dev/null || true
lsof -ti:3000 2>/dev/null | xargs kill -9 2>/dev/null || true

# Kill by process name as backup
pkill -f "uvicorn app.main:app" 2>/dev/null || true
pkill -f "celery.*finance" 2>/dev/null || true

echo ""
echo -e "${GREEN}All services stopped.${NC}"
