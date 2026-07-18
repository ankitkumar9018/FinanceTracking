# System Architecture

> FinanceTracker -- Personal Investment Portfolio Tracker for Indian & German Markets

## Overview

FinanceTracker is a full-stack, cross-platform investment tracking application built as a monorepo. It targets non-technical users who invest in Indian markets (NSE/BSE) and German markets (XETRA/Frankfurt), providing real-time portfolio monitoring, intelligent alerts, AI-powered insights, and interactive charts.

---

## Architecture Diagram

```
                            FinanceTracker System Architecture
 ==============================================================================

  CLIENTS
  -------
  +-------------------+     +-------------------+     +-------------------+
  |   Next.js 15      |     |   Tauri v2         |     |   Mobile (PWA)    |
  |   Web App         |     |   Desktop App      |     |   Service Worker  |
  |   (React 19 + TS) |     |   (Rust + React)   |     |   + Web Push      |
  +--------+----------+     +--------+----------+     +--------+----------+
           |                          |                          |
           +------------- HTTPS/WSS -+------ REST/WS -----------+
                                     |
                                     v
  API GATEWAY
  -----------
  +----------------------------------------------------------------------+
  |                        FastAPI 0.115+ (Python 3.12+)                 |
  |                                                                      |
  |  +------------------+  +------------------+  +--------------------+  |
  |  | REST API (v1)    |  | WebSocket Server |  | OpenAPI / Swagger  |  |
  |  | - Auth           |  | - /ws/prices     |  | Auto-generated     |  |
  |  | - Portfolio       |  | - /ws/alerts     |  | docs at /docs      |  |
  |  | - Holdings       |  +------------------+  +--------------------+  |
  |  | - Transactions   |                                                |
  |  | - Market Data    |                                                |
  |  | - Alerts         |  +------------------------------------------+ |
  |  | - Charts         |  |            Middleware Stack               | |
  |  | - Tax            |  | - CORS   - Rate Limit (slowapi, auth)    | |
  |  | - AI/ML          |  | - Static file serving (desktop build)    | |
  |  | - Import/Export  |  +------------------------------------------+ |
  |  | - Settings       |                                                |
  |  +------------------+                                                |
  +----------------------------------------------------------------------+
           |                    |                        |
           v                    v                        v
  SERVICES LAYER (~40 services)
  -----------------------------
  +------------------+  +------------------+  +---------------------+
  |  Portfolio       |  |  Market Data     |  |  Notification       |
  |  Service         |  |  Service         |  |  Service            |
  |  - Holdings CRUD |  |  - yfinance      |  |  - Email (SendGrid) |
  |  - P&L calc      |  |  - Broker APIs   |  |  - WhatsApp (Twilio)|
  |  - XIRR          |  |                  |  |  - Telegram Bot     |
  +------------------+  +------------------+  |  - SMS (Twilio)     |
  +------------------+  +------------------+  |  - In-App Toast     |
  |  Alert Service   |  |  Tax Service     |  +---------------------+
  |  - Range checks  |  |  - STCG/LTCG FIFO|  +---------------------+
  |  - RSI alerts    |  |  - IN grandfath. |  |  Forex Service      |
  |  - Custom rules  |  |  - German advncd.|  |  - yfinance rates   |
  +------------------+  |  - Tax harvest   |  |  - DB rate cache    |
  +------------------+  +------------------+  +---------------------+
  |  Broker Service  |  +------------------+  +---------------------+
  |  - Zerodha       |  |  Excel/Export    |  |  Net Worth Service  |
  |  - ICICI Direct  |  |  - Import .xlsx  |  |  - Multi-asset      |
  |  - Groww         |  |  - Export CSV/PDF|  |  - Live pricing     |
  |  - Angel One     |  |  - Google Sheets |  |  - Crypto/Gold/FD/  |
  |  - Deutsche Bank |  +------------------+  |    Bond/Real Estate |
  +------------------+  +------------------+  +---------------------+
  +------------------+  |  Benchmark       |  +---------------------+
  |  Dividend Service|  |  Service         |  |  What-If Simulator  |
  |  - DRIP handling |  |  - NIFTY50/SENSEX|  |  - Scenario analysis|
  |  - Yield calc    |  |  - DAX/S&P500   |  |  - Benchmark compare|
  |  - Calendar      |  |  - NASDAQ        |  +---------------------+
  +------------------+  +------------------+  +---------------------+
  +------------------+  +------------------+  |  Analytics Services |
  |  Mutual Fund Svc |  |  F&O Service     |  |  - Drift detection  |
  |  - mfapi.in NAV  |  |  - Options CRUD  |  |  - Sector rotation  |
  |  - Scheme search |  |  - Futures CRUD  |  |  - 52-week proximity|
  +------------------+  |  - P&L calc      |  |  - Data freshness   |
  +------------------+  +------------------+  |  - SIP calendar     |
  |  Goal Service    |  +------------------+  |  - Recurring detect  |
  |  - SIP calculator|  |  Comparison Svc  |  +---------------------+
  |  - Progress sync |  |  - Up to 3 stocks|  +---------------------+
  +------------------+  +------------------+  |  ESG / Earnings Svc |
  +------------------+  +------------------+  |  - ESG scoring      |
  |  Backtest Service|  |  Stop-Loss Svc   |  |  - Earnings calendar|
  |  - RSI strategy  |  |  - Threshold set |  +---------------------+
  |  - SMA crossover |  |  - Alert trigger |
  |  - Bollinger     |  +------------------+
  +------------------+
  +------------------+  +------------------+  +---------------------+
  |  Concentration   |  |  FIRE Service    |  |  Screener Service   |
  |  - HHI / N_eff   |  |  - Retirement    |  |  - Liquid universe  |
  |  - Cap buckets   |  |    projection    |  |  - RSI/yield/52wk   |
  |  - Diversif grade|  |  - SIP step-up   |  |    filters          |
  +------------------+  +------------------+  +---------------------+
  +------------------+  +------------------+
  |  Corporate Actn  |  |  Economic Cal.   |
  |  - Split/bonus   |  |  - Macro/earnings|
  |    detect+apply  |  |    catalysts     |
  +------------------+  +------------------+
           |                    |                        |
           v                    v                        v
  ML / AI LAYER
  -------------
  +----------------------------------------------------------------------+
  |                          ML / AI Services                            |
  |                                                                      |
  |  +-----------------+ +------------------+ +------------------------+ |
  |  | Technical       | | Price Predictor  | | Sentiment Analyzer     | |
  |  | Indicators      | | (PyTorch LSTM)   | | (FinBERT)              | |
  |  | (pandas_ta)     | |                  | |                        | |
  |  | - RSI-14        | | - Next 1/5/10d   | | - RSS feed parsing     | |
  |  | - MACD          | | - Confidence %   | | - Per-stock sentiment  | |
  |  | - Bollinger     | | - Nightly retrain| | - Bullish/Bearish/     | |
  |  | - SMA/EMA       | +------------------+ |   Neutral scoring      | |
  |  +-----------------+ +------------------+ +------------------------+ |
  |  +-----------------+ +------------------+ +------------------------+ |
  |  | Anomaly         | | Portfolio        | | LLM Assistant          | |
  |  | Detector        | | Optimizer        | | (LangChain)            | |
  |  | (Isolation      | | (Efficient       | |                        | |
  |  |  Forest)        | |  Frontier)       | | Primary: Ollama/Llama  | |
  |  |                 | |                  | | Optional: OpenAI,      | |
  |  | - Volume spikes | | - Risk tolerance | |   Claude, Gemini       | |
  |  | - Price anomaly | | - Rebalance      | | Graceful degradation   | |
  |  +-----------------+ +------------------+ +------------------------+ |
  |  +-----------------+                                                 |
  |  | Risk Calculator |                                                 |
  |  | - Sharpe Ratio  |                                                 |
  |  | - Sortino Ratio |                                                 |
  |  | - VaR (95%)     |                                                 |
  |  | - Max Drawdown  |                                                 |
  |  +-----------------+                                                 |
  +----------------------------------------------------------------------+
           |                    |                        |
           v                    v                        v
  DATA LAYER
  ----------
  +----------------------------------------------------------------------+
  |                                                                      |
  |  +------------------------+     +----------------------------------+ |
  |  |  SQLAlchemy 2.0 Async  |     |  Celery + Redis                  | |
  |  |  ORM + Alembic         |     |  (Background Tasks)              | |
  |  |                        |     |                                  | |
  |  |  DEV:  SQLite +        |     |  Beat schedule:                  | |
  |  |        aiosqlite       |     |  - fetch_prices (5 min)          | |
  |  |                        |     |  - check_alerts (1 min)          | |
  |  |  PROD: PostgreSQL +    |     |                                  | |
  |  |        asyncpg         |     |  Fallback: APScheduler           | |
  |  |                        |     |  AsyncIOScheduler if Redis /     | |
  |  |  Zero code changes     |     |  Celery is unavailable           | |
  |  |  between dev and prod  |     |                                  | |
  |  +------------------------+     +----------------------------------+ |
  |                                                                      |
  +----------------------------------------------------------------------+

  EXTERNAL SERVICES
  -----------------
  +-------------+  +-------------+  +------------------+
  | yfinance    |  | Broker APIs |  | News RSS Feeds   |
  | (prices+FX) |  | (Kite, etc) |  | (MoneyControl,   |
  |             |  |             |  |  Economic Times)  |
  +-------------+  +-------------+  +------------------+
  +-------------+  +-------------+  +-----------+
  | SendGrid    |  | Twilio      |  | Telegram  |
  | (Email)     |  | (WA/SMS)    |  | Bot API   |
  +-------------+  +-------------+  +-----------+
```

### Component Overview (Mermaid)

The same architecture as a layered component graph. Clients are same-origin with the API in the desktop build (the FastAPI process serves the Next.js static export); the browser talks to the API over HTTPS/WSS.

```mermaid
flowchart TB
    subgraph Clients
        WEB["Next.js 15 Web App<br/>React 19 + TS / PWA"]
        DESK["Tauri v2 Desktop<br/>Rust shell + WebView"]
    end

    subgraph API["FastAPI 0.115+ (Python 3.12+)"]
        REST["REST API /api/v1<br/>~171 endpoint handlers"]
        WS["WebSocket Server<br/>/ws/prices, /ws/alerts"]
        MW["Middleware<br/>CORS, slowapi rate limit,<br/>static file serving"]
        AUTH["JWT auth dependency<br/>get_current_user"]
    end

    subgraph Logic["Business Logic"]
        SVC["Services (~40)<br/>portfolio, tax, dividend,<br/>forex, alert, notification, ..."]
        ML["ML / AI Layer<br/>LSTM predictor, Isolation Forest,<br/>FinBERT sentiment, LLM assistant"]
    end

    subgraph Data["Data Layer"]
        ORM["SQLAlchemy 2.0 Async ORM<br/>+ Alembic migrations"]
        DB[("SQLite (dev)<br/>PostgreSQL (prod)")]
        SCHED["Celery + Redis beat<br/>-> APScheduler fallback"]
    end

    subgraph External["External Services (all optional / degrade gracefully)"]
        YF["yfinance<br/>prices + FX"]
        MFAPI["mfapi.in<br/>MF NAV"]
        LLMP["Ollama / OpenAI /<br/>Anthropic / Google"]
        NOTIF["SendGrid / Telegram /<br/>Twilio (WA/SMS)"]
        BROKER["Broker APIs<br/>(Kite, ICICI, ...)"]
    end

    WEB -->|HTTPS / WSS| REST
    WEB -->|WSS| WS
    DESK -->|same-origin| REST
    DESK --> WS
    REST --> MW --> AUTH --> SVC
    WS --> AUTH
    SVC --> ML
    SVC --> ORM
    ML --> ORM
    ORM --> DB
    SCHED --> SVC
    SVC --> YF
    SVC --> MFAPI
    SVC --> BROKER
    ML --> LLMP
    SVC --> NOTIF
```

---

## Monorepo Structure

FinanceTracker uses a monorepo managed by **Turborepo** (for JavaScript/TypeScript packages) and **uv** (for the Python backend). Package management is handled by **pnpm** for JS and **uv** for Python.

```
financeTracking/
|
+-- turbo.json                 # Turborepo pipeline configuration
+-- pnpm-workspace.yaml        # pnpm workspace: apps/* and packages/*
+-- package.json               # Root package.json (scripts, devDeps)
|
+-- backend/                   # Python FastAPI backend (managed by uv)
|   +-- pyproject.toml         # uv project config, all Python deps
|   +-- uv.lock                # Deterministic lockfile
|   +-- alembic.ini            # Database migration configuration
|   +-- alembic/versions/      # Migration scripts
|   +-- app/
|       +-- main.py            # FastAPI app entry point, lifespan
|       +-- config.py          # pydantic-settings based configuration
|       +-- database.py        # Async engine + session factory
|       +-- models/            # SQLAlchemy ORM models
|       +-- schemas/           # Pydantic request/response schemas
|       +-- api/v1/            # REST API route handlers
|       +-- api/ws/            # WebSocket handlers
|       +-- services/          # Business logic layer
|       +-- brokers/           # Broker adapter implementations
|       +-- ml/                # ML/AI model services
|       +-- tasks/             # Celery background tasks
|       +-- utils/             # Security, constants, helpers
|
+-- apps/
|   +-- web/                   # Next.js 15 web application
|   |   +-- package.json
|   |   +-- next.config.ts
|   |   +-- app/               # App Router pages
|   |   +-- components/        # React components
|   |   +-- hooks/             # Custom React hooks
|   |   +-- lib/               # API client, WebSocket, utilities
|   |
|   +-- desktop/               # Tauri v2 desktop application
|       +-- package.json
|       +-- src-tauri/          # Rust backend (Cargo.toml, src/lib.rs)
|       +-- src/                # Shares React components from web
|
+-- packages/
|   +-- ui/                    # Shared UI component library
|       +-- src/components/    # Hand-rolled shared components
|       +-- src/themes/        # Light + dark theme tokens
|       +-- src/animations/    # Framer Motion animation presets
|
+-- scripts/                   # Setup, start, stop, health-check
+-- docs/                      # This documentation
+-- .github/workflows/         # CI/CD pipelines
```

### Why This Structure?

| Decision | Rationale |
|---|---|
| Monorepo (not polyrepo) | Shared types, atomic cross-package changes, single CI pipeline |
| Turborepo | Incremental builds, remote caching, parallelized tasks |
| pnpm (not npm/yarn) | Strict dependency resolution, disk-efficient, workspace-native |
| uv (not pip/poetry) | 10-100x faster installs, lockfile support, replaces pip+venv+poetry |
| Separate `packages/ui` | Shared components between web and desktop without duplication |

---

## Backend Architecture

### FastAPI Application

The backend is a Python 3.12+ application built on **FastAPI 0.115+**, chosen for its async-first design, native WebSocket support, automatic OpenAPI documentation generation, and Pydantic-based validation.

```
Request Flow:

  Client Request
       |
       v
  +-- Middleware Stack --+
  |  1. CORS             |
  |  2. Rate Limiting    |
  |     (slowapi, auth   |
  |      endpoints only) |
  |  3. Static files     |
  |     (desktop build)  |
  +----------+-----------+
             |
             v
  +-- JWT Authentication --+
  |  Verify access token    |
  |  Extract user_id        |
  +----------+--------------+
             |
             v
  +-- API Route Handler --+     +-- Pydantic Schema --+
  |  Validate request body |<--->|  Type-safe I/O      |
  +----------+-------------+     +---------------------+
             |
             v
  +-- Service Layer --+
  |  Business logic    |
  |  Orchestration     |
  +----------+---------+
             |
             v
  +-- SQLAlchemy ORM --+      +-- External APIs --+
  |  Async queries      |      |  yfinance         |
  |  Transactions       |      |  Broker APIs      |
  +---------------------+      +-------------------+
```

The same request lifecycle as a sequence — an authenticated read such as `GET /api/v1/portfolios/{id}/summary`. The JWT auth dependency (`get_current_user`) runs before the route handler; a missing or invalid token short-circuits with `401` and never reaches the service layer.

```mermaid
sequenceDiagram
    participant B as Browser / Desktop
    participant M as Middleware<br/>(CORS, rate limit)
    participant A as Auth dependency<br/>get_current_user
    participant R as Route handler<br/>/api/v1/...
    participant S as Service layer
    participant DB as SQLAlchemy / DB

    B->>M: HTTPS request + Bearer JWT
    M->>A: forward (after CORS / rate-limit)
    A->>A: decode + verify access token
    alt token invalid or expired
        A-->>B: 401 Unauthorized
    else token valid
        A->>R: inject current_user
        R->>R: validate body/query (Pydantic)
        R->>S: call business logic
        S->>DB: async query / transaction
        DB-->>S: rows / ORM objects
        S-->>R: computed result
        R-->>B: 200 + JSON (Pydantic schema)
    end
```

### Database Strategy

SQLAlchemy 2.0 is used in fully async mode with the following strategy:

- **Development**: SQLite via `aiosqlite` driver. Zero configuration, single file (`finance.db`).
- **Production**: PostgreSQL via `asyncpg` driver. Connection pooling, concurrent writes.
- **Migration**: Alembic handles all schema migrations. The same migration scripts work for both databases.
- **Switching**: Change only the `DATABASE_URL` environment variable. No code changes required.

```python
# config.py -- database URL determines the backend
DATABASE_URL = "sqlite+aiosqlite:///./finance.db"      # Dev
DATABASE_URL = "postgresql+asyncpg://user:pass@host/db" # Prod
```

### Background Task Architecture

```
  +-- Celery + Redis (Primary) --+
  |                               |
  |  Beat Schedule:               |
  |  - fetch_prices:   every 5m   |
  |  - check_alerts:   every 1m   |
  |                               |
  +-------------------------------+
              |
              | If Redis/Celery unavailable
              v
  +-- APScheduler Fallback --+
  |                           |
  |  AsyncIOScheduler with    |
  |  interval jobs:           |
  |  - fetch_prices_job       |
  |  - check_alerts_job       |
  |                           |
  |  Same logic, single       |
  |  process, no Redis        |
  +------+--------------------+
```

When Redis is available, Celery provides distributed task execution with a beat scheduler running two periodic tasks (`fetch-prices`, `check-alerts`). When Redis or Celery is not installed (common for local development), the system falls back to APScheduler's `AsyncIOScheduler` running the same two interval jobs inside the FastAPI process.

### Service Layer Additions & Extensions

Beyond the representative services shown in the diagram above, the service layer includes several newer modules:

**New services:**

- `concentration_service` -- portfolio concentration and diversification scoring via the Herfindahl-Hirschman Index (HHI), effective holding count (`N_eff = 1/HHI`), market-cap buckets, and a letter grade (`GET /analytics/concentration/{portfolio_id}`).
- `fire_service` -- FIRE / retirement corpus projection and SIP step-up modelling (`GET /goals/fire`, `GET /goals/sip-projection`).
- `corporate_actions_service` -- detects stock splits and bonuses from yfinance and lets the user apply or dismiss them per holding (`/corporate-actions/*`), backed by the new `CorporateAction` model.
- `screener_service` -- stock screener over a curated liquid universe with RSI, dividend-yield, and 52-week filters (`GET /market/screener`).
- `economic_calendar_service` -- macro / earnings catalysts for a portfolio's holdings (`GET /analytics/economic-calendar/{portfolio_id}`).

**Extended services:**

- `tax_service` -- per-lot **FIFO** capital-gains matching (STCG/LTCG split per lot), Indian LTCG grandfathering (31-Jan-2018 FMV cost basis), German Teilfreistellung partial exemption, Vorabpauschale advance-tax estimate, and the Sparer-Pauschbetrag allowance tracker.
- `dividend_service` -- dividend income forecast and yield-on-cost (`GET /dividends/forecast`).
- `mutual_fund_service` -- real XIRR plus fund-overlap X-ray and expense / fee analysis (`GET /mutual-funds/overlap`, `/mutual-funds/expense-analysis`).
- `export_service` -- consolidated, ITR-ready capital-gains tax report (CSV + HTML).
- `portfolio_service` / `net_worth_service` -- optional, additive `display_currency` conversion on summary and net-worth responses (existing response fields are left unchanged).

**New models this cycle:** `PasswordReset` (single-use, SHA-256-hashed password-reset tokens with a 1-hour expiry) and `CorporateAction` (detected splits / bonuses with apply/dismiss state). See [security.md](security.md) for the password-reset flow.

---

## Frontend Architecture

### Next.js 15 Web Application

The web application uses the **App Router** with React Server Components (RSC) and streaming SSR:

```
apps/web/src/
+-- app/
|   +-- layout.tsx              # Root: theme provider, fonts, metadata
|   +-- (auth)/
|   |   +-- login/page.tsx
|   |   +-- register/page.tsx
|   |   +-- forgot-password/page.tsx  # Request a reset email
|   |   +-- reset-password/page.tsx   # Set a new password via token
|   +-- (dashboard)/
|       +-- layout.tsx          # Dashboard shell: sidebar, top bar
|       +-- page.tsx            # Portfolio overview (main table)
|       +-- holdings/           # Holdings table with bulk edit
|       +-- watchlist/          # Watchlist with alert ranges
|       +-- charts/             # TradingView candlestick charts
|       +-- alerts/             # Alerts + drift alerts
|       +-- tax/                # Tax summary (IN/DE)
|       +-- goals/              # Goal tracking + SIP calculator
|       +-- mutual-funds/       # MF holdings + NAV
|       +-- dividends/          # Dividend history + DRIP
|       +-- ai-assistant/       # LLM chat + voice input
|       +-- risk/               # Risk metrics dashboard
|       +-- brokers/            # Broker connection management
|       +-- backtest/           # Strategy backtesting
|       +-- optimizer/          # Portfolio optimizer
|       +-- visualizations/     # Correlation, treemap, calendar, drawdown
|       +-- net-worth/          # Multi-asset net worth
|       +-- esg/                # ESG scoring gauges
|       +-- whatif/             # What-if simulator
|       +-- earnings/           # Earnings calendar
|       +-- market-heatmap/     # Sector heatmap
|       +-- screener/           # Stock screener (liquid universe)
|       +-- compare/            # Side-by-side stock comparison
|       +-- corporate-actions/  # Splits & bonuses detect/apply
|       +-- economic-calendar/  # Macro & earnings catalysts
|       +-- fno/                # Futures & Options positions
|       +-- sip-calendar/       # SIP calendar grid
|       +-- ipo/                # IPO tracker
|       +-- snapshot/           # Shareable portfolio snapshot
|       +-- reports/            # Reports & export
|       +-- import/             # Excel/CSV import
|       +-- settings/           # User settings
|       +-- help/               # Help center + topic pages
+-- components/                 # Portfolio table, charts, AI chat, shared UI
+-- hooks/                      # usePortfolio, useWebSocket, useTheme, use-price-stream (live /ws/prices client), use-keyboard-shortcuts
+-- stores/                     # Zustand stores (auth, portfolio)
+-- lib/                        # API client, WebSocket manager, utilities
```

**Charting Libraries:**

| Library | Purpose | Size |
|---|---|---|
| TradingView Lightweight Charts v4.2 | Candlestick, OHLCV, real-time price | ~45KB |
| Recharts 2.15 | Donut/pie, goal progress, analytics charts | ~60KB |

### Tauri v2 Desktop Application

The desktop app wraps the same React components in a native shell:

```
apps/desktop/
+-- src-tauri/
|   +-- Cargo.toml              # Rust dependencies
|   +-- tauri.conf.json         # Window config, permissions
|   +-- src/lib.rs              # Tauri setup and plugins
|   +-- capabilities/           # Fine-grained permission model
+-- src/
|   +-- index.html              # Loader page that navigates to the backend-served frontend
```

The desktop WebView navigates to the backend on the dynamically-chosen port (default `8420`, auto-advancing to the next free port if it's busy). The chosen port is conveyed to the frontend, which serves the Next.js static export — so frontend and API stay same-origin.

**Tauri Advantages over Electron:**
- Bundle size: 5-10MB vs Electron's 100MB+
- Memory usage: ~30MB vs Electron's 100-200MB
- Native OS integration via Rust plugins (shell, notifications)

---

## Data Flow

### Price Update Flow

```
1. Market opens (09:15 IST / 09:00 CET)
2. Scheduler (Celery beat or APScheduler) triggers fetch_prices every 5 minutes
3. For each holding:
   a. Poll yfinance (15-min delayed for NSE)
   b. If yfinance fails -> serve cached price with "stale" flag
4. Price stored in price_history table
5. check_alerts task runs every 1 minute:
   a. Compare current_price against holding range levels
   b. Determine action_needed state (N / Y with color)
   c. If state changed -> trigger notifications
6. WebSocket pushes price + alert updates to all connected clients
7. Frontend subscribes to `/ws/prices` via the `use-price-stream` hook (auto-reconnect with backoff) and animates number transitions in real-time
```

There is no real-time broker price feed — all prices come from yfinance; broker connections are used for holdings sync only.

The push side of that loop — from the scheduler tick to the browser — as a sequence:

```mermaid
sequenceDiagram
    participant SCHED as Scheduler<br/>(Celery beat / APScheduler)
    participant FETCH as fetch_prices task
    participant YF as yfinance
    participant DB as price_history / holdings
    participant CM as ConnectionManager
    participant WS as /ws/prices
    participant FE as Frontend<br/>(use-price-stream hook)

    Note over SCHED,FETCH: every 5 min while market open
    SCHED->>FETCH: trigger fetch_prices
    FETCH->>YF: poll quotes (15-min delayed for NSE)
    alt yfinance ok
        YF-->>FETCH: latest OHLCV
    else yfinance fails / rate-limited
        FETCH->>DB: read cached price (mark "stale")
    end
    FETCH->>DB: upsert price + recompute action_needed
    FETCH->>CM: broadcast price update
    CM->>WS: push to subscribed clients
    WS-->>FE: {symbol, price, rsi, action_needed}
    Note over FE: animate number transition,<br/>auto-reconnect with backoff on drop
```

### Excel Import Flow

```
1. User uploads .xlsx file via drag-and-drop
2. Backend parses with openpyxl
3. Column mapping validated (Stock, Date, Qty, Price, Ranges...)
4. Import runs in one shot (no preview/confirm step):
   a. Create/update holdings with range levels
   b. Create transactions (BUY/SELL records)
   c. Calculate cumulative_quantity and average_price
5. Response returns rows_parsed / holdings_created / transactions_created
6. Dashboard reflects the new holdings on next refresh
```

---

## Graceful Degradation

Every external dependency has a fallback. The core application (portfolio tracking, Excel import, manual entry, alerts, charts) works without any optional service:

| Service | If Missing | Fallback |
|---|---|---|
| Redis | Not installed | APScheduler in-process scheduler |
| Celery | Not installed | APScheduler scheduled jobs within FastAPI |
| Ollama / LLM | Not installed | AI features show "AI offline" banner; all other features work |
| yfinance | Rate limited | Show last cached price with "stale" timestamp |
| Broker API | Connection fails | Manual data entry; show "Broker disconnected" badge |
| SendGrid | Not configured | Email alerts disabled; other channels work |
| Twilio | Not configured | WhatsApp/SMS disabled; other channels work |
| Telegram | Not configured | Telegram disabled; other channels work |
| Internet | Offline | Desktop app shows cached data with "Offline" indicator |
| PostgreSQL | Not available | Falls back to SQLite (default) |

---

## Technology Versions

| Technology | Minimum Version | Purpose |
|---|---|---|
| Python | 3.12+ | Backend runtime |
| FastAPI | 0.115+ | Web framework |
| SQLAlchemy | 2.0+ | Async ORM |
| Node.js | 20+ | Frontend build tools |
| React | 19 | UI framework |
| Next.js | 15 | Web app framework |
| Tauri | 2.x | Desktop app shell |
| PyTorch | 2.x | ML model training |
| Tailwind CSS | 4 | Utility-first styling |
| pnpm | 9+ | JS package manager |
| uv | latest | Python package manager |

---

## Security Architecture Summary

See [security.md](security.md) for the full security document. Key points:

- JWT authentication with 15-minute access tokens and 7-day refresh tokens
- Optional TOTP-based 2FA with a full setup/disable UI, plus change-password and self-service password reset (single-use, SHA-256-hashed tokens)
- Fernet encryption for stored API keys and secrets
- CORS strict origin allowlist
- Rate limiting via slowapi on auth endpoints (5/min register, 10/min login, 20/min refresh)
- SQLAlchemy ORM prevents SQL injection (no raw SQL)
- React auto-escaping prevents XSS
- All secrets in `.env` files, never committed to git

---

## Related Documentation

- [API Reference](api-reference.md) -- REST endpoints and WebSocket channels
- [Database Schema](database-schema.md) -- Full table definitions and relationships
- [Broker Integration](broker-integration.md) -- How each broker connects
- [ML/AI Models](ml-models.md) -- Machine learning features and models
- [Deployment](deployment.md) -- Development and production deployment
- [Security](security.md) -- Security architecture and compliance
