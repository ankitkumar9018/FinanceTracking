#!/bin/bash
# =============================================================================
# FinanceTracker — Health Check Script
# Checks the status of all services
# =============================================================================

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
echo -e "${BLUE}  FinanceTracker — Service Health${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
echo ""

# Resolve the actual ports chosen at launch (from either the .pids or logs dir,
# matching start.sh / run.sh respectively). Fall back to the defaults.
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$PROJECT_ROOT/backend"
PID_DIR="$PROJECT_ROOT/.pids"
LOGS_DIR="$PROJECT_ROOT/logs"
BPORT=$(cat "$PID_DIR/backend.port" "$LOGS_DIR/backend.port" 2>/dev/null | head -1)
BPORT=${BPORT:-8420}
FPORT=$(cat "$PID_DIR/frontend.port" "$LOGS_DIR/frontend.port" 2>/dev/null | head -1)
FPORT=${FPORT:-3000}

# Backend API
if curl -s "http://localhost:$BPORT/health" | grep -q "healthy" 2>/dev/null; then
    echo -e "  Backend API:     ${GREEN}Healthy ✓${NC}  http://localhost:$BPORT"
else
    echo -e "  Backend API:     ${RED}Down ✗${NC}"
fi

# Web App (on the actual chosen frontend port, not a hard-coded 3000)
if curl -s "http://localhost:$FPORT" &>/dev/null; then
    echo -e "  Web App:         ${GREEN}Running ✓${NC}  http://localhost:$FPORT"
else
    echo -e "  Web App:         ${RED}Down ✗${NC}"
fi

# Redis
if command -v redis-cli &>/dev/null && redis-cli ping &>/dev/null; then
    echo -e "  Redis:           ${GREEN}Connected ✓${NC}"
else
    echo -e "  Redis:           ${YELLOW}Not available ⚠${NC} (using fallback)"
fi

# Ollama
if curl -s http://localhost:11434/api/tags &>/dev/null; then
    MODELS=$(curl -s http://localhost:11434/api/tags | python3 -c "import sys,json; tags=json.load(sys.stdin); print(', '.join(m['name'] for m in tags.get('models',[])))" 2>/dev/null || echo "unknown")
    echo -e "  Ollama:          ${GREEN}Running ✓${NC}  Models: $MODELS"
else
    echo -e "  Ollama:          ${YELLOW}Not available ⚠${NC} (AI disabled)"
fi

# Database — resolve the real dev DB file from backend/.env (DATABASE_URL)
# instead of hard-coding a name/path; fall back to the common dev DB names.
DB_FILE=""
ENV_FILE="$BACKEND_DIR/.env"
[ -f "$ENV_FILE" ] || ENV_FILE="$BACKEND_DIR/.env.example"
if [ -f "$ENV_FILE" ]; then
    DB_URL=$(grep -E '^DATABASE_URL=' "$ENV_FILE" | head -1 | sed -E 's/^DATABASE_URL=//' | tr -d '\r')
    case "$DB_URL" in
        *sqlite*) DB_FILE="$BACKEND_DIR/${DB_URL##*/}" ;;  # trailing filename of the sqlite URL
    esac
fi
if [ -z "$DB_FILE" ] || [ ! -f "$DB_FILE" ]; then
    for candidate in "$BACKEND_DIR/finance.db" "$BACKEND_DIR/finance_tracker.db"; do
        [ -f "$candidate" ] && { DB_FILE="$candidate"; break; }
    done
fi
if [ -n "$DB_FILE" ] && [ -f "$DB_FILE" ]; then
    DB_SIZE=$(du -h "$DB_FILE" 2>/dev/null | cut -f1)
    echo -e "  Database:        ${GREEN}SQLite ✓${NC}  $(basename "$DB_FILE") (Size: $DB_SIZE)"
else
    echo -e "  Database:        ${YELLOW}Not created yet${NC}"
fi

echo ""
