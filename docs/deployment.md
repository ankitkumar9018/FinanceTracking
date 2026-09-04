# Deployment Guide

> FinanceTracker -- Development, Production & Operations

## Overview

FinanceTracker supports multiple deployment configurations:

| Environment | Backend | Frontend | Database | Task Queue |
|---|---|---|---|---|
| **Local Dev** | uvicorn (reload) | next dev | SQLite | APScheduler (default) |
| **Docker Dev** | Docker Compose | Docker Compose | SQLite/PostgreSQL | Celery + Redis (`USE_CELERY=true`) |
| **Production Web** | Docker / Railway | Vercel | PostgreSQL | APScheduler (single worker) or Celery + Redis (`USE_CELERY=true`) |
| **Desktop** | Bundled PyInstaller sidecar | Static Next.js in Tauri | SQLite (app-data) | APScheduler (default) |

The backend is deliberately environment-agnostic. The **same code** runs in all four modes; the only things that change are environment variables (chiefly `DATABASE_URL`) and how the process is launched. There is no separate "production build" of the Python app.

### Deployment Topology

```mermaid
flowchart TB
    subgraph web["Web / Server Deployment"]
        direction TB
        browser["Browser / Next.js Web App<br/>(Vercel or self-hosted)"]
        api["FastAPI backend<br/>uvicorn/gunicorn : app.main:app"]
        db[("PostgreSQL<br/>(asyncpg)")]
        redis[("Redis<br/><i>optional</i>")]
        celery["Celery worker + beat<br/><i>only when USE_CELERY=true</i>"]
        aps["APScheduler<br/>(in-process, default)"]
        ollama["Ollama / LLM providers<br/><i>optional</i>"]

        browser -->|HTTPS REST + WS| api
        api --> db
        api -.->|if configured| redis
        celery -.->|broker| redis
        celery --> db
        api -->|"USE_CELERY unset/false"| aps
        api -.->|AI features| ollama
    end

    subgraph desktop["Desktop Deployment (single machine)"]
        direction TB
        shell["Tauri shell (WKWebView / WebView2 / WebKitGTK)"]
        sidecar["Bundled sidecar<br/>financetracker-backend (PyInstaller)"]
        localdb[("Local SQLite<br/>app-data/finance.db")]
        apsd["APScheduler (in-process)"]

        shell -->|http://127.0.0.1:PORT<br/>same-origin UI + API| sidecar
        sidecar --> localdb
        sidecar --> apsd
    end
```

In the desktop build the frontend, API, and database all live on one machine: Tauri spawns the sidecar bound to `127.0.0.1`, the sidecar serves the statically-exported Next.js UI **and** the API from the same origin, and data persists to a local SQLite file in the OS app-data directory. No network services are required.

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
cd backend && uv run uvicorn app.main:app --reload --port 8420

# 6. Start web app (terminal 2)
cd apps/web && pnpm dev

# 7. Start desktop app (terminal 3, optional)
cd apps/desktop && pnpm tauri dev
```

> **Preferred port & auto-selection:** the backend's default port is **8420**. When launched via `python -m app` (the PyInstaller sidecar, the `build-installer` scripts, and the desktop app all use this entry point), `--port` is treated as a *preference*: if 8420 is already in use the backend automatically advances to the next free port, prints which one it chose, and starts there — so a busy port never blocks startup and no other app's port is ever taken over. Pass `--strict-port` to require the exact port and fail if it's busy instead. A bare `uvicorn app.main:app --port 8420` binds that exact port with no auto-advance.

### Optional Services

```bash
# Start Redis (for background task queue)
redis-server --daemonize yes

# Start Celery worker (requires Redis; ONLY if you also set USE_CELERY=true
# on the API process — otherwise every job runs twice)
cd backend && USE_CELERY=true uv run celery -A app.tasks.celery_app worker --beat -l info

# Start Ollama (for AI assistant)
ollama serve
ollama pull llama3.2
```

### Service URLs (Development)

| Service | URL |
|---|---|
| Web App | http://localhost:3000 |
| API | http://localhost:8420 |
| Swagger Docs | http://localhost:8420/docs |
| ReDoc Docs | http://localhost:8420/redoc |
| Redis | redis://localhost:6379 |
| Ollama | http://localhost:11434 |

---

## Production Configuration

All backend configuration lives in `backend/app/config.py` (a `pydantic-settings` model) and is read from **environment variables** or a `backend/.env` file, both resolved **once at process start**. Any unknown variable is silently ignored (`extra="ignore"`), so a typo'd or unsupported name fails quietly rather than erroring. A fully documented template ships in `backend/.env.example`.

> **There is no runtime override from the UI.** The in-app **Settings** page edits *user* rows (currency, theme, display name, phone, Telegram chat ID, notification toggles) only — it never writes server configuration. An `app_settings` table is declared in `backend/app/models/app_settings.py` but nothing reads or writes it. Changing any variable below therefore requires a **backend restart**.

### Environment Variable Reference

Every name below is a real, declared field (`config.py`, except `LOG_LEVEL` which
`app/core/logging_config.py` reads directly); env-var names are the upper-cased
form. Rows marked **Declared but not read** exist in the settings model but no
code consults them — they are listed so you don't waste time setting them.

Because `Settings` uses `extra="ignore"`, a name that is *not* in this table is
dropped with no warning at all. `MFAPI_URL` and `NOTIFICATION_CHANNELS` were
previously documented here and were exactly that: the mfapi.in base URL is fixed
in `app/services/mutual_fund_service.py`, and notification channels are per-user
preferences, not a global env list.

| Variable | Default | Required in Prod | Purpose |
|---|---|---|---|
| `APP_NAME` | `FinanceTracker` | No | Display name (surfaced in `/health`). |
| `LOG_LEVEL` | `INFO` | No | Root log level: `CRITICAL`\|`ERROR`\|`WARNING`\|`INFO`\|`DEBUG`. Read at startup by `app/core/logging_config.py` (not a `config.py` field). The `audit` logger stays at INFO regardless, so raising this can never silently disable the security audit trail. |
| `APP_VERSION` | `0.1.0` | No | Version string (surfaced in `/health`). |
| `DEBUG` | `false` | Set `false` | Enables SQLAlchemy echo + verbose logging. **Must be `false` in production.** |
| `API_PORT` | `8420` | No | **Declared but not read.** The port comes from `python -m app --port N` (default `8420`, auto-advancing to a free port unless `--strict-port`). Setting `API_PORT` in `.env` has no effect. |
| `SECRET_KEY` | `dev-secret-CHANGE-IN-PRODUCTION` | **Yes** | JWT signing key. Generate a long random value (see below). |
| `FERNET_KEY` | `""` (empty) | **Yes** | Symmetric key encrypting stored broker credentials/secrets. If empty, an **ephemeral** key is generated per process — encrypted data becomes unreadable after restart. Set a persistent key in production. |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `15` | No | Access-token lifetime. |
| `REFRESH_TOKEN_EXPIRE_DAYS` | `7` | No | Refresh-token lifetime. |
| `DATABASE_URL` | `sqlite+aiosqlite:///…/finance.db` | **Yes** (Postgres) | SQLAlchemy async URL. See "Switching SQLite → PostgreSQL". |
| `REDIS_URL` | `redis://localhost:6379` | No | Celery broker/result backend (used only when `USE_CELERY=true`) **and** the alert-dedup/cache store. When unreachable the app uses in-memory caches. Redis reachability does **not** affect which scheduler runs — see `USE_CELERY`. |
| `USE_CELERY` | `false` | No | **The only switch that selects the scheduler.** `false` (default) → in-process APScheduler. `true` → the app skips APScheduler and expects an external `celery worker`/`beat` you run yourself. Setting it `true` without a running worker means **no** background jobs run at all; leaving it `false` while running a worker means **every job runs twice**. |
| `PRICE_REFRESH_INTERVAL` | `5` | No | Minutes between background price refreshes. |
| `DEFAULT_CHART_DAYS` | `30` | No | Default chart lookback. |
| `MARKET_HOURS_IN` / `MARKET_HOURS_DE` | `09:15-15:30` / `09:00-17:30` | No | **Declared but not read.** The per-exchange sessions used by the staleness logic are hard-coded in `app/services/freshness_service.py`. |
| `ALERT_CHECK_INTERVAL` | `60` | No | Seconds between alert evaluations. |
| `SENDGRID_API_KEY` / `EMAIL_FROM` | `""` | No | Email notifications (SendGrid). |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` | `""` | No | WhatsApp + SMS via Twilio. |
| `TWILIO_WHATSAPP_FROM` / `TWILIO_SMS_FROM` | `""` | No | Twilio sender numbers. |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | `""` | No | Telegram notifications (per-user chat IDs stored on the user row override the global default). |
| `LLM_PROVIDER` | `ollama` | No | One of `ollama`, `openai`, `anthropic`, `google`, `none`. |
| `OLLAMA_URL` / `OLLAMA_MODEL` | `http://localhost:11434` / `llama3.2` | No | Local LLM. |
| `OLLAMA_TIMEOUT` | `300.0` | No | Seconds to wait for an Ollama generation. Raise it on CPU-only or busy machines where local generation is slow. |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | `""` / `gpt-4` | No | OpenAI provider. |
| `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL` | `""` / `claude-sonnet-4-20250514` | No | Claude provider. |
| `GOOGLE_API_KEY` | `""` | No | Gemini provider. |
| `AI_DIGEST_TIMEOUT` | `120.0` | No | Budget (seconds) for AI digest and report-summary generation. On expiry the deterministic numbers-only digest is served (or the report renders without the AI section). |
| `AI_ALERT_EXPLANATIONS` | `true` | No | Append a one-sentence AI explanation to triggered alert notifications. Set `false` to disable. |
| `AI_ALERT_EXPLAIN_TIMEOUT` | `20.0` | No | Budget (seconds) for that explanation; on expiry the plain alert message is sent. |
| `ZERODHA_API_KEY` / `ZERODHA_API_SECRET` | `""` | No | **Not used to connect.** Broker credentials are entered on the in-app **Brokers** page and stored Fernet-encrypted per connection. These fields are read only by `GET /settings/health`, which reports `broker: configured` when either is non-empty. |
| `ICICI_APP_KEY` / `ICICI_SECRET_KEY` | `""` | No | Same as above — health-check signal only. |
| `CORS_ORIGINS` | `http://localhost:3000,http://localhost:1420,https://tauri.localhost` | **Yes** | Comma-separated allowed origins for the web app. Set to your web app's real origin(s) in production. |
| `DEFAULT_CURRENCY` / `DEFAULT_THEME` | `INR` / `dark` | No | **Declared but not read.** New accounts take their currency and theme defaults from the `User` model (`INR`, `dark`); each user then changes them on the Settings page. |

> **Note on `CORS_ORIGINS` in desktop mode:** the sidecar (`python -m app --db-path …`) force-sets `CORS_ORIGINS=*` at startup because it binds to `127.0.0.1` only and different platform webviews send different origins. Do **not** rely on `*` for a public web deployment — set explicit origins there.

> **`DATABASE_POOL_SIZE`** appears commented-out in `.env.example` as a placeholder; the current engine (`app/database.py`) uses SQLAlchemy's default pooling and does not read it. Tune the pool at the engine level if needed.

### Generating Secrets

```bash
# SECRET_KEY — a long, URL-safe random string
python -c "import secrets; print(secrets.token_urlsafe(64))"

# FERNET_KEY — a valid Fernet key (44-char base64)
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Store both in your secret manager / platform variables — **not** in source control. Rotating `FERNET_KEY` invalidates every stored (encrypted) broker credential; users must re-enter them. Rotating `SECRET_KEY` invalidates all outstanding JWTs, forcing re-login.

### Switching SQLite → PostgreSQL

The backend is database-agnostic (`app/database.py`): switching engines is a **one-variable change** with no code edits.

```bash
# Development (default)
DATABASE_URL=sqlite+aiosqlite:///./finance.db

# Production
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/financetracker
```

What the change does automatically:

- **Async driver**: `postgresql+asyncpg://…` selects the `asyncpg` driver for the async engine (already a project dependency). SQLite uses `aiosqlite`.
- **SQLite-only tweaks drop out**: `connect_args={"check_same_thread": False}` and the `PRAGMA foreign_keys=ON` connect-hook only apply when `is_sqlite` is true (URL contains `sqlite`). PostgreSQL enforces foreign keys natively.
- **Alembic uses a sync driver**: migrations derive a synchronous URL from `DATABASE_URL` (the desktop path strips `+aiosqlite`; for Postgres, configure `sqlalchemy.url` in `alembic.ini`/`env.py` to a sync driver such as `postgresql+psycopg://…` when running `alembic upgrade head`).

Provision the target database first, set `DATABASE_URL`, then run `alembic upgrade head`. Nothing else changes.

### Running with a Production ASGI Server

Do **not** use `--reload` in production. Run uvicorn directly, or gunicorn with uvicorn workers for multi-process concurrency:

```bash
# Single-process uvicorn (simple, good behind one container)
cd backend
uv run uvicorn app.main:app --host 0.0.0.0 --port 8420 --no-access-log

# Multi-worker uvicorn
uv run uvicorn app.main:app --host 0.0.0.0 --port 8420 --workers 4

# gunicorn managing uvicorn workers (graceful reloads, worker recycling)
uv run gunicorn app.main:app \
    -k uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:8420 \
    --workers 4 --timeout 120
```

**Important — background jobs with multiple workers:** APScheduler is the default mode and **runs inside every worker process**. With N uvicorn/gunicorn workers you get N schedulers firing the same price/alert/digest jobs. In any multi-worker deployment either pin the API to a single worker, or set `USE_CELERY=true` on **every** API process and run one external Celery worker/beat (see below) so periodic jobs fire exactly once.

---

## Background Tasks: APScheduler (default) vs Celery

FinanceTracker runs **three** periodic jobs, defined once in the shared `JOBS`
tuple in `app/tasks/celery_app.py`:

| Job id | What it does | Cadence |
|---|---|---|
| `fetch_prices_job` | Refresh prices/RSI for every tracked holding | every `PRICE_REFRESH_INTERVAL` minutes (also once at startup) |
| `check_alerts_job` | Evaluate every active alert and dispatch notifications | every `ALERT_CHECK_INTERVAL` seconds (also once at startup) |
| `ai_digest_job` | Generate scheduled AI portfolio digests | daily (never at startup — it would re-send on every restart) |

### Which scheduler runs is decided by `USE_CELERY` — and by nothing else

```mermaid
flowchart LR
    start["Backend startup<br/>start_scheduler()"] --> check{"settings.use_celery<br/>(env USE_CELERY)"}
    check -->|"false — the default"| aps["APScheduler starts in-process<br/>(FastAPI event loop)"]
    check -->|"true AND celery importable"| celery["APScheduler skipped —<br/>you must run celery worker + beat"]
    check -->|"true BUT celery not installed"| warn["Warning logged,<br/>APScheduler starts anyway"]
```

- **A reachable Redis changes nothing.** An earlier build auto-detected Celery
  by pinging Redis; that heuristic was removed because any unrelated local
  Redis satisfied it and silently disabled APScheduler while no worker
  consumed the queue — prices and alerts then never refreshed. The
  `is_celery_available()` helper still exists in `app/tasks/celery_app.py` but
  is **diagnostic only** and is not consulted by `start_scheduler()`.
- **APScheduler** (`app/tasks/scheduler.py`) uses an `AsyncIOScheduler` inside
  the FastAPI event loop, started and stopped by the app's lifespan hooks.
  `start_scheduler()` is idempotent. This is the mode every standard
  deployment uses — the desktop sidecar, `run.sh`, and plain `uvicorn`.
- **Celery** is strictly opt-in. Set `USE_CELERY=true` **and** run the worker
  yourself:

  ```bash
  cd backend
  USE_CELERY=true uv run celery -A app.tasks.celery_app worker --beat -l info
  ```

  The same `USE_CELERY=true` must be set on the **API** process too — that is
  what stops it from also starting APScheduler.

> **Get this wrong and it breaks quietly, in one of two directions:**
> `USE_CELERY=true` with no worker running → *no* background job ever fires
> (stale prices, no alerts, no digests). `USE_CELERY` left unset while a
> Celery worker *is* running → every job fires **twice** (duplicate alert
> emails/Telegram messages, duplicate digests, double the yfinance load).

> **Known limitation of Celery mode:** the WebSocket broadcasts inside the
> price-refresh and alert-check tasks execute in the *worker* process, whose
> connection manager holds no browser sockets. Live WS pushes are therefore
> **not** delivered to connected clients in Celery mode; the UI falls back to
> its normal polling. This is documented in `app/tasks/celery_app.py`.

- **When to use Celery:** multi-worker or horizontally-scaled deployments (so
  jobs fire once, centrally), or when jobs must survive an API restart.
- **When APScheduler is fine:** single-process deployments and the desktop
  app. No Redis, no extra process, and WS pushes work.

Redis, when present, is also used for alert deduplication/caching; without it
the app uses in-memory fallbacks. Nothing in the feature set requires Redis —
it is purely an optimisation/scale-out lever.

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
      - "8420:8420"
    volumes:
      - ./backend:/app
      - backend-data:/app/data
    environment:
      - DATABASE_URL=postgresql+asyncpg://finance:finance@db:5432/financetracker
      - REDIS_URL=redis://redis:6379/0
      # REQUIRED here: without it the API also starts its own APScheduler and
      # every job below runs twice (duplicate alerts, duplicate digests).
      - USE_CELERY=true
      - SECRET_KEY=${SECRET_KEY:-change-me-in-production}
      - FERNET_KEY=${FERNET_KEY}
      - CORS_ORIGINS=${CORS_ORIGINS:-http://localhost:3000}
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
      - USE_CELERY=true
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
      - NEXT_PUBLIC_API_URL=http://localhost:8420
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
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port 8420"]

EXPOSE 8420
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
railway variables set SECRET_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(64))')"
railway variables set FERNET_KEY="$(python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')"
railway variables set CORS_ORIGINS="https://app.yourdomain.com"
railway variables set REDIS_URL="redis://..."     # optional

# Deploy
railway up
```

Migrations run automatically on container start (`alembic upgrade head` in the Dockerfile `CMD`). See "Database Migration Strategy" below.

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

There is no checked-in `vercel.json`; configure the monorepo build in the Vercel dashboard (root directory `apps/web`, install command `pnpm install` from the repo root, build command `pnpm --filter @finance-tracker/web build`). Whatever origin Vercel assigns must be listed in the backend's `CORS_ORIGINS`.

### Desktop App (Tauri Builds)

The desktop app bundles a PyInstaller-compiled backend sidecar and a statically-exported Next.js frontend into a native Tauri shell. It builds for 5 targets: macOS (ARM64 + Intel), Windows (x64 + ARM64), and Linux (x64).

#### Quick Build

```bash
# macOS / Linux
./build-installer.sh

# Windows
build-installer.bat
```

#### Packaging Pipeline (build-installer.sh)

`build-installer.sh` runs 7 ordered steps. The **order matters**: the static frontend must be built and staged into `backend/static` *before* the PyInstaller step, because the sidecar serves the UI from a bundled copy.

```mermaid
flowchart TB
    s1["1. Check / auto-install prereqs<br/>Node, pnpm, Python 3.12+, uv, Rust,<br/>Linux GTK/webkit deps"]
    s2["2. Install deps<br/>uv sync + pnpm install"]
    s3["3. Ensure PyInstaller<br/>uv add --dev pyinstaller"]
    s4["4. Build static frontend<br/>STATIC_EXPORT=true → apps/web/out<br/>copy to apps/desktop/dist<br/><b>and</b> stage into backend/static"]
    s5["5. PyInstaller sidecar<br/>financetracker.spec → dist/financetracker-backend<br/>copy to binaries/financetracker-backend-&lt;target-triple&gt;"]
    s6["6. Tauri bundle<br/>tauri build → .dmg/.app, .msi/.exe, .AppImage/.deb"]
    s7["7. Print output paths"]
    s1 --> s2 --> s3 --> s4 --> s5 --> s6 --> s7
```

Step details worth knowing:

- **Step 4 → 5 ordering (the key fix):** the frontend export is copied to *two* places — `apps/desktop/dist` (Tauri's `frontendDist`) **and** `backend/static`. `financetracker.spec` bundles `backend/static` into the binary only if it exists, and `app/main.py` serves the UI from that bundled `static/` dir. Building in the old order shipped a sidecar with no frontend → a blank window after install.
- **Step 5 target-triple naming:** the binary is copied to `apps/desktop/src-tauri/binaries/financetracker-backend-<target>` where `<target>` is the platform triple (`aarch64-apple-darwin`, `x86_64-apple-darwin`, `x86_64-unknown-linux-gnu`, …). Tauri's `externalBin` resolves the sidecar by this suffix.
- **PyInstaller spec (`backend/financetracker.spec`):** onefile-style build from `sidecar_entry.py`; bundles `alembic.ini` + `alembic/` (for migrations) and `static/`; explicitly lists every `app.*` submodule as a hidden import; **excludes** heavy ML deps (`torch`, `sklearn`, `scipy`, `transformers`, `tensorflow`) that degrade gracefully at runtime.

#### The `%20` Path Fix (macOS "Application Support")

Every macOS install stores its database under `~/Library/Application Support/…`, a path containing a space. Two distinct places had to be hardened against it:

1. **Alembic config interpolation** (`app/__main__.py`): `configparser` treats `%` as interpolation syntax, so a URL-encoded `Application%20Support` crashed `set_main_option` with "invalid interpolation syntax". Fixed by escaping `%` → `%%` before setting `sqlalchemy.url`.
2. **The SQLite URL itself**: SQLAlchemy takes the SQLite path verbatim (no URL-decoding), so a percent-encoded `%20` would become a literal `%20` directory that doesn't exist. The DB path is passed with **raw spaces** (`Path(...).as_posix()`, no percent-encoding), which SQLAlchemy accepts.

#### First-Launch Timing & Startup Sequence

The onefile PyInstaller sidecar extracts its whole bundle on **every** launch, and on first run macOS Gatekeeper / Windows Defender may scan it, so a cold start can take **40–120 seconds**. The Tauri shell (`apps/desktop/src-tauri/src/lib.rs`) handles this:

- **Port selection:** tries `8420–8425` in order, then falls back to any free OS-assigned port. The sidecar itself (`python -m app`) also treats `--port` as a preference and auto-advances to a free port if the given one is busy, so startup is never blocked and no other app's port is taken over (pass `--strict-port` to require an exact port).
- **DB path & seed:** resolves `app_data_dir/finance.db`, always passes `--seed` (the seed function is a no-op if the demo user already exists), and passes `--db-path` so the sidecar runs migrations + additive reconciliation.
- **Immediate loading screen:** the window starts at `about:blank`; a spinner + "First launch can take a minute or two" is injected instantly so users never see a blank window.
- **Health polling:** a background thread polls `http://127.0.0.1:PORT/health` for up to **120 seconds**. On success it navigates the window to `http://localhost:PORT/#ftport=PORT` — same origin as the API, avoiding mixed-content blocking. The `#ftport=` hash tells the frontend which port the API is on (the Tauri IPC bridge is gone after navigation).
- **Self-healing recovery page:** if 120s elapses, a recovery page keeps polling `/health` every 2s (with a "Retry now" button) and navigates as soon as the backend answers — a plain reload would strand the user on the static shell with no monitor thread left.
- **Clean shutdown:** on exit Tauri kills the sidecar child and, as a belt-and-suspenders measure, `pkill`/`taskkill`s any stray `financetracker-backend` process.

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

See [desktop-app.md](desktop-app.md) for the complete build guide, including manual build steps, sidecar naming conventions and target triples, CORS/database behavior, platform-specific notes (code signing, console hiding, Linux deps), and troubleshooting.

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

### The Seven Migrations

There are currently **7 migrations**, with head at `e3f4a5b6c7d8` (listed in chain order):

| Revision | Adds |
|---|---|
| `b388e46e4f03` | Initial schema (all base tables). |
| `9ec39aff1e92` | `holdings.currency`. |
| `abf5040f074b` | `asset` + `fno_position` tables. |
| `8809e230b920` | Unique constraint on `(holding, portfolio)`. |
| `c1f2a3b4d5e6` | `users.phone`, `users.telegram_chat_id`, `password_resets` table. |
| `d2e3f4a5b6c7` | `holdings.fund_type`, `mutual_funds.fund_type`, `user_preferences.tax_settings`, `corporate_actions` table. |
| `e3f4a5b6c7d8` | `users.totp_backup_codes`. |

### Production Migration

Migrations run automatically on container startup (`alembic upgrade head`). For zero-downtime deployments:

1. **Additive changes** (new tables, new columns with defaults): safe to apply while the app is running.
2. **Column renames**: use a two-step migration (add new column, migrate data, drop old column in next release).
3. **Column removals**: deploy code that stops using the column first, then remove in a later release.
4. **Data migrations**: run as a separate task, not inside the schema migration.

### Additive Schema Reconciliation on Startup

When the backend is launched with a concrete database path (`python -m app --db-path …`, as the desktop sidecar does), it runs Alembic migrations and then an **additive schema-reconciliation pass** (`_reconcile_schema` in `backend/app/__main__.py`). This is a safety net for upgrades: it creates any tables and adds any columns that the current models declare but the existing database is missing, and it **never drops, renames, or rewrites anything** — existing data is untouched.

The startup path (`_run_migrations`) handles three cases:

1. **Fresh install** — no DB. Alembic creates every table from the migrations.
2. **Upgrade** — DB exists with an `alembic_version` table. Only pending migrations run.
3. **Legacy DB** — created by an old `create_all()` with no `alembic_version`. It is **stamped at head** first (so Alembic doesn't try to recreate existing tables), then reconciled additively so columns newer migrations *would* have added (e.g. `phone`, `fund_type`, `tax_settings`) are still created.

Because SQLite can't `ADD COLUMN` with `NOT NULL` and no default, reconciliation adds columns nullable (or with the model's scalar default). Reconciliation failures are caught and logged — they **never block startup**. This guarantees a database created by an *older* app version keeps working after installing a *newer* build.

### Upgrading an Existing Installation (Your Data Is Kept)

Upgrading is safe by design because **the data lives outside the app**. In the desktop build the entire database is a single SQLite file (`finance.db`) in the OS per-user app-data folder — never inside the installed program directory:

| OS | Database file |
|---|---|
| macOS | `~/Library/Application Support/com.financetracker.app/finance.db` |
| Windows | `%APPDATA%\com.financetracker.app\finance.db` (some builds use `%LOCALAPPDATA%\com.financetracker.app\finance.db`) |
| Linux | `~/.local/share/com.financetracker.app/finance.db` |

Installing a newer version replaces **only the application**, never this folder. And because every launch runs `alembic upgrade head` followed by the additive reconciliation described above, a database created by an *older* build (even one that's months old) is upgraded to the current schema automatically — new tables and columns are added, and **nothing is dropped, renamed, or rewritten**. Existing accounts, portfolios, holdings, and transactions are preserved and stay fully editable.

So the upgrade path is simply: **run the new installer over the old version and the data carries forward intact.** This has been verified end to end (old-schema DB → new build → data intact, schema upgraded, CRUD works). Before a major upgrade, it's still worth exporting a JSON/SQLite backup from the in-app **Reports** page (or copying the `finance.db` file above) as cheap insurance. On a server (PostgreSQL) deployment the same guarantees apply through Alembic; take a `pg_dump` before migrating (see below).

---

## Backups

### SQLite (dev + desktop)

The backend exposes an authenticated full-database download:

```
GET /api/v1/import-export/export/backup/sqlite
```

This returns the raw `finance.db` file (`finance_tracker_backup_<timestamp>.db`). Because that file contains **every** user's data — password hashes, TOTP secrets, Fernet-encrypted broker credentials — it is **owner-only**: the endpoint computes the instance owner as the **first-registered account** (`min(User.id)`) and returns **403** to anyone else. Non-owners should use the per-portfolio JSON export instead (`GET /api/v1/import-export/export/json/{portfolio_id}`), which is scoped to their own data. On a PostgreSQL deployment the endpoint returns **501** and directs you to `pg_dump`.

Filesystem-level backup (equivalent, no API needed):

```bash
cp finance.db finance_backup_$(date +%Y%m%d).db
```

Desktop DB locations (per OS app-data dir, identifier `com.financetracker.app`):

| OS | Path |
|---|---|
| macOS | `~/Library/Application Support/com.financetracker.app/finance.db` |
| Windows | `%APPDATA%\com.financetracker.app\finance.db` |
| Linux | `~/.local/share/com.financetracker.app/finance.db` |

### PostgreSQL (production)

Use `pg_dump` before every migration and on a schedule:

```bash
# Compressed custom-format dump (best for pg_restore)
pg_dump -Fc financetracker > backup_$(date +%Y%m%d).dump

# Restore
pg_restore -d financetracker --clean backup_20260718.dump
```

Automate nightly dumps to object storage and verify restores periodically.

---

## Monitoring & Health Checks

FinanceTracker exposes two health endpoints for different audiences.

### Public Liveness — `GET /health`

Unauthenticated, cheap, suitable for load balancers / container health probes:

```json
{
  "status": "healthy",
  "app": "FinanceTracker",
  "version": "1.0.0"
}
```

The static-frontend middleware explicitly lets `/health` (and `/api/…`, `/ws/…`) pass through to FastAPI, so it works even in the bundled desktop build. The Tauri shell polls exactly this endpoint to decide when to show the UI.

### Authenticated Service Status — `GET /api/v1/settings/health`

Requires a logged-in user. Returns per-dependency status so you can see *what* is degraded:

```json
{
  "database": "healthy",
  "redis": "healthy | unavailable",
  "ollama": "healthy | unavailable | disabled | using_openai",
  "broker": "configured | not_configured",
  "overall": "healthy | degraded"
}
```

Only the database is treated as critical for the `overall` verdict — Redis, the LLM provider, and broker keys are optional and reported as informational (the app degrades gracefully when they're absent).

### Health Check Script

```bash
# macOS / Linux
./scripts/health-check.sh

# Windows PowerShell
.\scripts\health-check.ps1

# Output:
# === FinanceTracker Health Check ===
# Backend API:  OK (http://localhost:8420/health)
# Web App:      OK (http://localhost:3000)
# Database:     OK (SQLite, 12.5 MB)
# Redis:        WARN (not running, using fallback)
# Ollama:       OK (llama3.2 loaded)
# Celery:       n/a  (USE_CELERY=false — APScheduler owns the schedule)
```

### Logging

- Backend logs: standard Python `logging`.
- Log levels: DEBUG when `DEBUG=true` (dev), INFO in production.
- Log aggregation: stdout (captured by Docker/Railway). In the desktop build the sidecar's stdout/stderr are piped to the Tauri console with a `[backend]` prefix.

---

## SSL / HTTPS

### Development

Not needed. Everything runs on localhost over HTTP. The desktop app also runs over local HTTP on `127.0.0.1` (same-origin UI + API), which is why the sidecar force-allows all CORS origins.

### Production

- **Vercel**: HTTPS provided automatically.
- **Railway**: HTTPS provided automatically with custom domain support.
- **Self-hosted**: use a reverse proxy (nginx/Caddy) with Let's Encrypt certificates, and ensure your TLS origin is listed in `CORS_ORIGINS`.

Example Caddy configuration:

```
financetracker.yourdomain.com {
    reverse_proxy localhost:8420
}

app.financetracker.yourdomain.com {
    reverse_proxy localhost:3000
}
```

WebSocket routes (`/ws/prices`, `/ws/alerts`) share the same origin/proxy — no extra configuration is required for Caddy/nginx beyond standard `Upgrade` handling.

---

## Scaling Considerations

| Component | Scaling Strategy |
|---|---|
| Backend API | Horizontal: multiple uvicorn workers behind a load balancer. **Set `USE_CELERY=true` on every API process and run one Celery worker/beat**, otherwise the in-process APScheduler multiplies the jobs per worker. |
| Celery Workers | Horizontal: add more worker containers; keep a single `beat`. |
| PostgreSQL | Vertical: larger instance; read replicas for analytics. |
| Redis | Vertical: larger instance; or use Upstash (serverless). |
| Web App | Handled by Vercel's edge network. |
| ML Models | The heavy ML deps (torch/sklearn/scipy) are optional and excluded from the desktop sidecar; run them on a dedicated worker with more RAM/GPU if enabled server-side. |

For a personal portfolio tracker, a single instance handles thousands of holdings without issue. Scaling is relevant only if the application is offered as a multi-tenant SaaS.

---

## Related Documentation

- [Architecture](architecture.md) -- System design overview
- [Desktop App](desktop-app.md) -- Full desktop build & packaging guide
- [Contributing](contributing.md) -- Developer setup instructions
- [Security](security.md) -- Production security configuration
- [Troubleshooting](troubleshooting.md) -- Common deployment issues
</content>
</invoke>
