# Deployment Guide

> FinanceTracker -- Development & Production Deployment

## Overview

FinanceTracker supports multiple deployment configurations:

| Environment | Backend | Frontend | Database | Task Queue |
|---|---|---|---|---|
| **Local Dev** | uvicorn (reload) | next dev | SQLite | asyncio fallback |
| **Docker Dev** | Docker Compose | Docker Compose | SQLite/PostgreSQL | Celery + Redis |
| **Production Web** | Docker / Railway | Vercel | PostgreSQL | Celery + Redis |
| **Desktop** | Bundled | Tauri .dmg/.msi | SQLite (local) | asyncio fallback |

---

## Local Development

### Prerequisites

| Tool | Minimum Version | Install |
|---|---|---|
| Python | 3.12+ | https://python.org or `pyenv install 3.12` |
| uv | Latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node.js | 20+ | https://nodejs.org or `nvm install 20` |
| pnpm | 9+ | `npm install -g pnpm` |
| Redis | 7+ | Optional: `brew install redis` (macOS) |
| Ollama | Latest | Optional: https://ollama.ai |

### Quick Start

```bash
# Clone the repository
git clone https://github.com/yourusername/financeTracking.git
cd financeTracking

# First-time setup
chmod +x scripts/setup.sh
./scripts/setup.sh

# Start all services
chmod +x scripts/start.sh
./scripts/start.sh
```

### Manual Start (Step by Step)

```bash
# 1. Install backend dependencies
cd backend && uv sync && cd ..

# 2. Install frontend dependencies
pnpm install

# 3. Create environment file
cp backend/.env.example backend/.env
# Edit backend/.env with your settings

# 4. Run database migrations
cd backend && uv run alembic upgrade head && cd ..

# 5. Start backend (terminal 1)
cd backend && uv run uvicorn app.main:app --reload --port 8000

# 6. Start web app (terminal 2)
cd apps/web && pnpm dev

# 7. Start desktop app (terminal 3, optional)
cd apps/desktop && pnpm tauri dev
```

### Optional Services

```bash
# Start Redis (for background task queue)
redis-server --daemonize yes

# Start Celery worker (requires Redis)
cd backend && uv run celery -A app.tasks.celery_app worker --beat -l info

# Start Ollama (for AI assistant)
ollama serve
ollama pull llama3.2
```

### Service URLs (Development)

| Service | URL |
|---|---|
| Web App | http://localhost:3000 |
| API | http://localhost:8000 |
| Swagger Docs | http://localhost:8000/docs |
| ReDoc Docs | http://localhost:8000/redoc |
| Redis | redis://localhost:6379 |
| Ollama | http://localhost:11434 |

---

## Docker Development

### Docker Compose

Create `docker-compose.yml` in the project root:

```yaml
version: "3.9"

services:
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    volumes:
      - ./backend:/app
      - backend-data:/app/data
    environment:
      - DATABASE_URL=postgresql+asyncpg://finance:finance@db:5432/financetracker
      - REDIS_URL=redis://redis:6379/0
      - SECRET_KEY=${SECRET_KEY:-change-me-in-production}
    depends_on:
      - db
      - redis
    restart: unless-stopped

  celery-worker:
    build:
      context: ./backend
      dockerfile: Dockerfile
    command: celery -A app.tasks.celery_app worker --beat -l info
    volumes:
      - ./backend:/app
    environment:
      - DATABASE_URL=postgresql+asyncpg://finance:finance@db:5432/financetracker
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - db
      - redis
    restart: unless-stopped

  web:
    build:
      context: .
      dockerfile: apps/web/Dockerfile
    ports:
      - "3000:3000"
    environment:
      - NEXT_PUBLIC_API_URL=http://localhost:8000
    depends_on:
      - backend
    restart: unless-stopped

  db:
    image: postgres:16-alpine
    ports:
      - "5432:5432"
    environment:
      - POSTGRES_USER=finance
      - POSTGRES_PASSWORD=finance
      - POSTGRES_DB=financetracker
    volumes:
      - postgres-data:/var/lib/postgresql/data
    restart: unless-stopped

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis-data:/data
    restart: unless-stopped

  ollama:
    image: ollama/ollama
    ports:
      - "11434:11434"
    volumes:
      - ollama-data:/root/.ollama
    restart: unless-stopped

volumes:
  postgres-data:
  redis-data:
  ollama-data:
  backend-data:
```

### Backend Dockerfile

Create `backend/Dockerfile`:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install Python dependencies
RUN uv sync --frozen --no-dev

# Copy application code
COPY . .

# Run database migrations and start server
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000"]

EXPOSE 8000
```

### Web App Dockerfile

Create `apps/web/Dockerfile`:

```dockerfile
FROM node:20-alpine AS base

# Install pnpm
RUN npm install -g pnpm

WORKDIR /app

# Copy workspace config
COPY pnpm-workspace.yaml package.json pnpm-lock.yaml turbo.json ./
COPY apps/web/package.json apps/web/
COPY packages/ui/package.json packages/ui/

# Install dependencies
RUN pnpm install --frozen-lockfile

# Copy source code
COPY apps/web/ apps/web/
COPY packages/ui/ packages/ui/

# Build
RUN pnpm --filter web build

# Production image
FROM node:20-alpine AS runner
WORKDIR /app

COPY --from=base /app/apps/web/.next/standalone ./
COPY --from=base /app/apps/web/.next/static ./apps/web/.next/static
COPY --from=base /app/apps/web/public ./apps/web/public

CMD ["node", "apps/web/server.js"]

EXPOSE 3000
```

### Running with Docker

```bash
# Start all services
docker compose up -d

# View logs
docker compose logs -f backend

# Stop all services
docker compose down

# Reset database
docker compose down -v  # Warning: deletes all data
```

---

## Production Deployment

### Backend (Docker / Railway / Render)

#### Railway Deployment

```bash
# Install Railway CLI
npm install -g @railway/cli

# Login and initialize
railway login
railway init

# Set environment variables
railway variables set DATABASE_URL="postgresql+asyncpg://..."
railway variables set SECRET_KEY="your-secure-secret-key"
railway variables set REDIS_URL="redis://..."

# Deploy
railway up
```

#### Environment Variables (Production)

| Variable | Description | Required |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string | Yes |
| `SECRET_KEY` | JWT signing key (min 32 chars) | Yes |
| `REDIS_URL` | Redis connection string | Yes (for Celery) |
| `API_PORT` | Server port | No (default: 8000) |
| `CORS_ORIGINS` | Allowed origins (comma-separated) | Yes |
| `SENDGRID_API_KEY` | Email notifications | No |
| `TWILIO_ACCOUNT_SID` | WhatsApp/SMS | No |
| `TWILIO_AUTH_TOKEN` | WhatsApp/SMS | No |
| `TELEGRAM_BOT_TOKEN` | Telegram notifications | No |
| `OLLAMA_URL` | Ollama server URL | No |
| `OPENAI_API_KEY` | OpenAI API key | No |
| `ANTHROPIC_API_KEY` | Claude API key | No |
| `GOOGLE_API_KEY` | Gemini API key | No |

### Web App (Vercel)

The Next.js web application deploys seamlessly to Vercel:

```bash
# Install Vercel CLI
npm install -g vercel

# Deploy from apps/web directory
cd apps/web
vercel

# Set environment variables
vercel env add NEXT_PUBLIC_API_URL
# Enter: https://your-api-domain.com
```

**Vercel Configuration** (`apps/web/vercel.json`):

```json
{
  "buildCommand": "cd ../.. && pnpm --filter web build",
  "outputDirectory": ".next",
  "installCommand": "cd ../.. && pnpm install",
  "framework": "nextjs"
}
```

### Desktop App (Tauri Builds)

The desktop app bundles a PyInstaller-compiled backend sidecar and a static Next.js frontend into a native Tauri shell. It builds for 5 targets: macOS (ARM64 + Intel), Windows (x64 + ARM64), and Linux (x64).

#### Quick Build

```bash
# macOS / Linux
./build-installer.sh

# Windows
build-installer.bat
```

This runs all 7 steps automatically (prerequisites, deps, PyInstaller sidecar, static frontend, Tauri build) and outputs the platform-specific installer.

#### Output Locations

| Platform | Installer Type | Path |
|---|---|---|
| macOS | `.dmg` + `.app` | `apps/desktop/src-tauri/target/release/bundle/dmg/` |
| Windows | `.msi` + `.exe` (NSIS) | `apps/desktop/src-tauri/target/release/bundle/msi/` and `nsis/` |
| Linux | `.AppImage` + `.deb` | `apps/desktop/src-tauri/target/release/bundle/appimage/` and `deb/` |

#### CI/CD Automated Builds

The `.github/workflows/release-desktop.yml` workflow builds all 5 targets when a version tag is pushed:

```bash
git tag v1.0.0
git push origin v1.0.0
```

This creates a GitHub draft release with all installers attached.

#### Full Documentation

See [desktop-app.md](desktop-app.md) for the complete build guide, including:
- Step-by-step manual build instructions
- Sidecar binary naming conventions and target triples
- How the desktop app works (startup sequence, CORS, database location)
- Platform-specific details (macOS code signing, Windows console hiding, Linux system deps)
- Troubleshooting common build issues

---

## Database Migration Strategy

### Development Workflow

```bash
# After modifying SQLAlchemy models:

# 1. Generate migration
cd backend && uv run alembic revision --autogenerate -m "add new column to holdings"

# 2. Review the generated migration in alembic/versions/
# 3. Apply migration
uv run alembic upgrade head

# 4. If something went wrong, rollback
uv run alembic downgrade -1
```

### Production Migration

Migrations run automatically on container startup (`alembic upgrade head`). For zero-downtime deployments:

1. **Additive changes** (new tables, new columns with defaults): Safe to apply while app is running
2. **Column renames**: Use a two-step migration (add new column, migrate data, drop old column in next release)
3. **Column removals**: Deploy code that stops using the column first, then remove in next release
4. **Data migrations**: Run as a separate Celery task, not in the migration itself

### Backup Before Migration

```bash
# PostgreSQL backup
pg_dump -Fc financetracker > backup_$(date +%Y%m%d).dump

# SQLite backup
cp finance.db finance_backup_$(date +%Y%m%d).db
```

---

## Monitoring & Health Checks

### Health Check Endpoint

```
GET /health
```

Returns:
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "database": "connected",
  "redis": "connected",
  "uptime_seconds": 86400
}
```

### Logging

- Backend logs: structured JSON via `structlog`
- Log levels: DEBUG (dev), INFO (production)
- Log aggregation: stdout (captured by Docker/Railway)

### Health Check Script

```bash
# macOS / Linux
./scripts/health-check.sh

# Windows PowerShell
.\scripts\health-check.ps1

# Output:
# === FinanceTracker Health Check ===
# Backend API:  OK (http://localhost:8000/health)
# Web App:      OK (http://localhost:3000)
# Database:     OK (SQLite, 12.5 MB)
# Redis:        WARN (not running, using fallback)
# Ollama:       OK (llama3.2 loaded)
# Celery:       WARN (not running, using asyncio)
```

---

## SSL / HTTPS

### Development

Not needed. Everything runs on localhost over HTTP.

### Production

- **Vercel**: HTTPS provided automatically
- **Railway**: HTTPS provided automatically with custom domain support
- **Self-hosted**: Use a reverse proxy (nginx/Caddy) with Let's Encrypt certificates

Example Caddy configuration:

```
financetracker.yourdomain.com {
    reverse_proxy localhost:8000
}

app.financetracker.yourdomain.com {
    reverse_proxy localhost:3000
}
```

---

## Scaling Considerations

| Component | Scaling Strategy |
|---|---|
| Backend API | Horizontal: multiple uvicorn workers behind load balancer |
| Celery Workers | Horizontal: add more worker containers |
| PostgreSQL | Vertical: larger instance; read replicas for analytics |
| Redis | Vertical: larger instance; or use Upstash (serverless) |
| Web App | Handled by Vercel's edge network |
| ML Models | Run on dedicated worker with more RAM/GPU |

For a personal portfolio tracker, a single instance handles thousands of holdings without issue. Scaling is relevant only if the application is offered as a multi-tenant SaaS.

---

## Related Documentation

- [Architecture](architecture.md) -- System design overview
- [Contributing](contributing.md) -- Developer setup instructions
- [Security](security.md) -- Production security configuration
- [Troubleshooting](troubleshooting.md) -- Common deployment issues
