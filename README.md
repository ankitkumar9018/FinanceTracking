# FinanceTracker

> Your personal investment command center for Indian & German markets

A highly visual, cross-platform portfolio tracking application designed for non-technical users. Track stocks across NSE, BSE, and XETRA with real-time prices, intelligent color-coded alerts, AI-powered insights, and beautiful data visualizations.

---

## Features

### Core Portfolio Management
- **Excel Import/Export** — Bulk import your existing portfolio from Excel spreadsheets
- **Manual Entry** — Add stocks, transactions, and price ranges directly from the dashboard
- **Custom Columns** — Add your own columns and reorder the table to your liking
- **Cumulative Holdings** — Automatic calculation of quantity and weighted average price
- **Real-time Prices** — Live stock prices via broker WebSocket or yfinance
- **RSI Tracking** — 14-period RSI calculated and displayed for every holding

### Intelligent Alerts (Color-Coded)
- **Light Red** — Stock price entered lower mid range (caution zone)
- **Light Green** — Stock price entered upper mid range (opportunity zone)
- **Dark Red** — Stock price at or below base level (critical)
- **Dark Green** — Stock price at or near top level (target reached)
- **Multi-Channel Notifications** — Email, WhatsApp, Telegram, SMS, Desktop Push, In-App

### Interactive Charts
- **Candlestick Charts** — TradingView-quality OHLCV charts with 30-day default view
- **RSI Movement** — Click any RSI cell to see the RSI chart over time
- **Price Ranges on Chart** — Base, top, and mid-range levels shown as horizontal lines
- **Technical Indicators** — MACD, Bollinger Bands, Moving Averages, Fibonacci, Support/Resistance

### Broker Integration
- **Indian Brokers** — Zerodha (Kite Connect), ICICI Direct (Breeze), Groww, Angel One, Upstox, 5Paisa
- **German Brokers** — Deutsche Bank, comdirect (via PSD2/Open Banking)
- **Auto-Sync** — Holdings, positions, and transactions sync automatically

### Tax Tracking
- **India** — STCG/LTCG classification, tax harvesting suggestions, ITR report generation
- **Germany** — Abgeltungssteuer, Vorabpauschale, Freistellungsauftrag tracking, Anlage KAP support
- **Multi-Currency** — INR + EUR with real-time forex rates from ECB

### AI Assistant
- **Natural Language Queries** — Ask "Which stocks are underperforming?" or "How much LTCG tax will I owe?"
- **Local-First AI** — Runs on Ollama + Llama 3.2 locally (free, private)
- **Optional Cloud AI** — Plug in OpenAI, Claude, or Gemini for enhanced capabilities
- **Graceful Degradation** — App works 100% without AI; AI features are optional enhancements

### Additional Features
- **Mutual Fund Tracking** — Import CAS from CAMS/KFintech, AMFI NAV data
- **Dividend Tracking** — DRIP support, dividend calendar, tax implications
- **Goal-Based Investing** — Set financial goals, track progress with visual gauges
- **Portfolio Analytics** — XIRR, Sharpe Ratio, Sortino Ratio, VaR, Max Drawdown
- **Backtesting** — Test trading strategies on historical data
- **News Sentiment** — AI-powered sentiment analysis for your holdings
- **Watchlist** — Track stocks you're interested in with the same alert system
- **Voice Queries** — Ask about your portfolio using voice (browser Speech API)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI (Python 3.12+) with async SQLAlchemy 2.0 |
| Python Packages | uv (by Astral) |
| Web App | Next.js 15 + React 19 + TypeScript |
| Desktop App | Tauri v2 + React (Windows, macOS, Linux) |
| UI Components | Shadcn/ui + Tailwind CSS 4 + Framer Motion |
| Charts | TradingView Lightweight Charts + Apache ECharts |
| Database | SQLite (dev) / PostgreSQL (prod) via SQLAlchemy |
| ML/AI | PyTorch, scikit-learn, pandas_ta, LangChain |
| LLM | Ollama + Llama 3.2 (local) / OpenAI / Claude / Gemini |
| Task Queue | Celery + Redis (optional — falls back to in-memory) |
| Monorepo | Turborepo + pnpm |

---

## Quick Start

### Prerequisites

**Required:**
- Python 3.12+ and [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh`)
- Node.js 20+ and [pnpm](https://pnpm.io/) (`npm install -g pnpm`)

**Optional (for enhanced features):**
- [Redis](https://redis.io/) — For background task queue (falls back to in-memory if absent)
- [Ollama](https://ollama.ai/) — For local AI assistant (`ollama pull llama3.2`)

### Install & Run

```bash
# Clone the repository
git clone https://github.com/yourusername/financeTracking.git
cd financeTracking

# Option 1: Use the setup script (first time)
chmod +x scripts/setup.sh
./scripts/setup.sh

# Option 2: Use the start script (after setup)
chmod +x scripts/start.sh
./scripts/start.sh
```

**Windows:**
```powershell
# First time setup
.\scripts\setup.ps1

# Start everything
.\scripts\start.ps1

# Or use the one-click launcher (same as run.sh but for Windows)
.\run.ps1
```

### Manual Setup

```bash
# Install backend dependencies
cd backend && uv sync && cd ..

# Install frontend dependencies
pnpm install

# Run database migrations
cd backend && uv run alembic upgrade head && cd ..

# Start backend
cd backend && uv run uvicorn app.main:app --reload --port 8000 &

# Start web app
cd apps/web && pnpm dev &
```

### Demo Login

Seed the database first, then log in with the demo account:

```bash
cd backend && uv run python scripts/seed.py
```

| Field | Value |
|---|---|
| Email | `demo@financetracker.dev` |
| Password | `demo1234` |

### Access

| Service | URL |
|---|---|
| Web App | http://localhost:3000 |
| API | http://localhost:8000 |
| API Docs (Swagger) | http://localhost:8000/docs |
| API Docs (ReDoc) | http://localhost:8000/redoc |

---

## Desktop App (Windows, macOS, Linux)

FinanceTracker ships as a native desktop app with everything bundled — no dependencies to install.

### Download Installers

Pre-built installers are available on the [Releases](https://github.com/yourusername/financeTracking/releases) page:

| Platform | Installer |
|---|---|
| macOS | `FinanceTracker_x.x.x_aarch64.dmg` (Apple Silicon) / `_x64.dmg` (Intel) |
| Windows | `FinanceTracker_x.x.x_x64-setup.exe` or `.msi` |
| Linux | `FinanceTracker_x.x.x_amd64.AppImage` or `.deb` |

### Build Installer Locally

Run the build script on the target platform:

```bash
# macOS / Linux
./build-installer.sh

# Windows (Command Prompt)
build-installer.bat
```

This builds everything from source — the backend is compiled into a standalone binary (no Python needed on the target machine), and the frontend is statically exported. The resulting installer is fully self-contained.

**Prerequisites for building:** Node.js 20+, pnpm, Python 3.12+, uv, Rust

**Supported targets:** macOS (Apple Silicon + Intel), Windows (x64 + ARM64), Linux (x64)

See [docs/desktop-app.md](docs/desktop-app.md) for the full step-by-step build guide, architecture details, and troubleshooting.

---

## How It Works

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│   Import Excel   │     │   Manual Entry   │     │   Broker Sync    │
│   (.xlsx file)   │     │  (from dashboard)│     │ (Zerodha, ICICI) │
└────────┬─────────┘     └────────┬─────────┘     └────────┬─────────┘
         │                        │                         │
         └────────────────────────┼─────────────────────────┘
                                  ▼
                    ┌─────────────────────────┐
                    │     FastAPI Backend      │
                    │  (Portfolio Management)  │
                    └────────────┬────────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                   ▼
     ┌────────────────┐ ┌───────────────┐ ┌─────────────────┐
     │  Price Engine   │ │  Alert Engine │ │   AI Assistant  │
     │  (yfinance +   │ │ (Color-coded  │ │ (Ollama/LLM +   │
     │   broker API)  │ │  ranges)      │ │  LangChain)     │
     └────────────────┘ └───────────────┘ └─────────────────┘
              │                  │                   │
              └──────────────────┼───────────────────┘
                                 ▼
                    ┌─────────────────────────┐
                    │    Dashboard (Web/       │
                    │    Desktop App)          │
                    │  - Color-coded table     │
                    │  - Interactive charts    │
                    │  - Real-time updates     │
                    │  - AI chat panel         │
                    └─────────────────────────┘
```

---

## Configuration

All settings can be configured via `.env` file OR from the Settings page in the app.

Copy `.env.example` to `.env` and fill in your values:

```bash
cp backend/.env.example backend/.env
```

See [docs/user-guide.md](docs/user-guide.md) for detailed configuration instructions.

---

## Project Structure

```
financeTracking/
├── backend/          # FastAPI Python backend (uv managed)
├── apps/
│   ├── web/          # Next.js 15 web application
│   └── desktop/      # Tauri v2 desktop app (Windows, macOS, Linux)
├── packages/
│   └── ui/           # Shared UI components (Shadcn/ui)
├── docs/             # Comprehensive documentation
├── scripts/          # Setup, start, stop, health-check scripts
├── PROJECT_PLAN.md   # Detailed implementation plan with phases
└── README.md         # This file
```

---

## Documentation

| Document | Description |
|---|---|
| [Architecture](docs/architecture.md) | System design, diagrams, data flow |
| [API Reference](docs/api-reference.md) | REST endpoints & WebSocket channels |
| [Database Schema](docs/database-schema.md) | Tables, relationships, ERD |
| [Desktop App](docs/desktop-app.md) | Build guide, architecture, CI/CD for desktop |
| [Broker Integration](docs/broker-integration.md) | How to connect each broker |
| [ML/AI Models](docs/ml-models.md) | ML features, models, training |
| [Deployment](docs/deployment.md) | How to deploy to production |
| [User Guide](docs/user-guide.md) | End-user manual (non-technical) |
| [Security](docs/security.md) | Security architecture & compliance |
| [Tax Guide](docs/tax-guide.md) | Indian & German tax handling |
| [FAQ](docs/faq.md) | Frequently Asked Questions |
| [Troubleshooting](docs/troubleshooting.md) | Common issues & solutions |
| [Contributing](docs/contributing.md) | Developer setup & guidelines |
| [Changelog](docs/changelog.md) | Version history & release notes |

---

## In-App Help

The application includes a built-in Help Center accessible from every page:
- Searchable help articles for every feature
- Interactive onboarding wizard for first-time users
- Contextual help buttons on every page
- Financial glossary (RSI, MACD, STCG, LTCG explained simply)
- Tooltips on every column header, button, and icon

---

## Development

```bash
# Run backend tests
cd backend && uv run pytest -v --cov=app

# Run frontend tests
pnpm --filter web test

# Run E2E tests
pnpm --filter web test:e2e

# Run all tests
pnpm test

# Lint
pnpm lint

# Type check
pnpm typecheck
```

---

## Contributing

See [docs/contributing.md](docs/contributing.md) for development setup and contribution guidelines.

---

## License

MIT License - see [LICENSE](LICENSE) for details.
