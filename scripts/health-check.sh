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

# Backend API
if curl -s http://localhost:8000/health | grep -q "healthy" 2>/dev/null; then
    echo -e "  Backend API:     ${GREEN}Healthy ✓${NC}  http://localhost:8000"
else
    echo -e "  Backend API:     ${RED}Down ✗${NC}"
fi

# Web App
if curl -s http://localhost:3000 &>/dev/null; then
    echo -e "  Web App:         ${GREEN}Running ✓${NC}  http://localhost:3000"
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

# Database
DB_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/backend/finance.db"
if [ -f "$DB_FILE" ]; then
    DB_SIZE=$(du -h "$DB_FILE" 2>/dev/null | cut -f1)
    echo -e "  Database:        ${GREEN}SQLite ✓${NC}  Size: $DB_SIZE"
else
    echo -e "  Database:        ${YELLOW}Not created yet${NC}"
fi

echo ""
