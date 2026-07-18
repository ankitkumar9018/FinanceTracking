# Changelog

All notable changes to FinanceTracker are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [0.11.0] - 2026-07 (Timers, Cash Flow, Hedging & 2FA Recovery)

### Added — Tax
- **Holding-period timer**: per-lot countdown to Indian LTCG eligibility (>12 months held), with the estimated tax saving once each lot crosses the long-term threshold — shown on the Tax page

### Added — Analytics
- **Cash-flow timeline** — new `/cash-flow` page (sidebar **Cash Flow**, under *Analysis*): monthly money in/out (buys, sells, dividends) with cumulative net, shown as a combined bar-and-line chart plus period totals

### Added — Planning & Risk
- **Emergency-fund indicator** (Net Worth page): enter your monthly expenses to see how many months your liquid assets (FD / crypto / gold; stocks counted separately) would cover, with a **critical / adequate / strong** status
- **Portfolio hedge calculator** (Risk page): an informational estimate of the cost of index-put downside protection for your portfolio — clearly labelled as an estimate, not investment advice

### Added — Discovery
- **Peer comparison** (Compare page): benchmark a stock against curated sector peers — Banking / IT / Energy / FMCG / Auto / Pharma / Metals for NSE, plus a few XETRA sectors — in a side-by-side metrics table

### Added — Security
- **2FA backup codes**: enabling Two-Factor Authentication now issues **10 one-time recovery codes**; each is single-use at login if you lose your authenticator, with a remaining-count display and a regenerate action (new `e3f4a5b6c7d8` migration adds TOTP backup codes)

---

## [0.10.0] - 2026-07 (Tax Correctness, Planning & Discovery)

### Added — Tax Correctness
- **Per-lot FIFO capital-gains matching**: sales matched against buy lots FIFO, STCG/LTCG split per lot, idempotent recompute
- **Indian LTCG grandfathering**: 31-Jan-2018 FMV used as the cost basis per FIFO lot (LTCG only)
- **German Teilfreistellung** partial exemption: equity 30% / mixed 15% / real-estate 60%, driven by holding/fund `fund_type` (`PUT /tax/fund-type/{holding_id}`)
- **German Vorabpauschale** advance-tax estimate: Basiszins table 2018–2025 (`GET /tax/vorabpauschale/{portfolio_id}`)
- **Sparer-Pauschbetrag allowance tracker**: €1,000 single / €2,000 joint; Freibetrag netting honors joint filing + Teilfreistellung (`GET /tax/allowance`, `PUT /tax/settings`)
- **Consolidated capital-gains tax report**: ITR-ready CSV + HTML export (`GET /tax/report/{financial_year}`)

### Added — Auth & Security
- **Forgot / reset password** flow: `PasswordReset` model, `POST /auth/forgot-password`, `POST /auth/reset-password`, plus `/forgot-password` and `/reset-password` pages
- **Change password** endpoint (`POST /auth/change-password`)
- **2FA/TOTP** now has a full setup / verify / disable UI
- **Per-user notification destinations**: `users.phone` and `users.telegram_chat_id` used across email / Telegram / WhatsApp / SMS / in-app, plus an SMS toggle

### Added — Real-Time
- Live-price WebSocket client wired into the UI via the `use-price-stream` hook
- In-app notification center in the top bar (bell)

### Added — Analytics & Insights
- **Concentration & diversification score** (HHI-based) — `GET /analytics/concentration/{portfolio_id}`
- **Economic / macro calendar** — `GET /analytics/economic-calendar/{portfolio_id}` + Economic Calendar page

### Added — Planning
- **FIRE / retirement projection** (`GET /goals/fire`) and **SIP step-up projection** (`GET /goals/sip-projection`); Goals page reorganized into tabs

### Added — Income
- **Dividend income forecast** + yield-on-cost (`GET /dividends/forecast`)
- **Real XIRR for mutual funds**

### Added — Discovery
- **Stock screener** over a curated liquid universe (`GET /market/screener`) + Screener page
- **Corporate-actions detection & apply** (splits / bonuses) — `/corporate-actions/*` + Corporate Actions page
- **Mutual-fund overlap X-ray** and **expense / fee analyzer** (`GET /mutual-funds/overlap`, `GET /mutual-funds/expense-analysis`)

### Added — Multi-Currency
- Optional **global display currency**: additive `?display_currency=` on portfolio summary and net worth, with a top-bar currency selector (existing response fields unchanged)

### Added — UX
- Create-portfolio modal in the top bar
- Holdings stop-loss + custom columns; stock **Compare** page
- AI insights panels (prediction / anomaly / sentiment)
- Dashboard XIRR + benchmark cards; dividend & net-worth delete
- Mobile drawer navigation, grouped sidebar, error / empty states
- ~45 aria-labels, reduced-motion support, dynamic-imported charts, offline service worker
- New sidebar entries: **Compare**, **Screener**, **Corporate Actions**, **Economic Calendar**

### Fixed — Desktop
- macOS backend-not-starting crash on "Application Support" paths (space encoded as `%20`)
- Corrected build order (frontend staged into `backend/static`)
- 120s startup wait with a self-healing loading page; `#ftport` hash for the dynamic port
- Additive schema reconciliation keeps existing databases usable across upgrades

---

## [0.9.1] - 2026-03 (Cross-Platform & Polish)

### Added
- **Desktop app build guide**: Comprehensive `docs/desktop-app.md` with architecture, step-by-step build instructions, platform details, CI/CD, and troubleshooting
- **Windows one-click launcher**: `run.ps1` with start/stop/restart/status/logs (mirrors `run.sh`)
- **Windows health check**: `scripts/health-check.ps1` (checks backend, frontend, Redis, Ollama, DB)
- **5Paisa broker stub**: `brokers/fivepaisa.py` adapter registered in broker registry
- **E2E tests in CI**: New `e2e-tests` job in `ci.yml` (starts backend+frontend, runs 32 Playwright tests)
- **ARM64 Windows builds**: `release-desktop.yml` now builds `aarch64-pc-windows-msvc` target

### Fixed
- **PyInstaller Windows venv path**: Detects `Lib/site-packages` on Windows vs `lib/pythonX.Y/site-packages` on Unix
- **SQLite URL on Windows**: Uses `Path.as_posix()` to normalize backslash paths in database URLs
- **Console window flash on Windows**: PyInstaller spec sets `console=False` on Windows
- **Silent exception swallowing**: Added `logger.debug()` with `exc_info=True` in `market_data.py`, `holdings.py`, `broker.py` (was bare `except: pass`)
- **bcrypt version pin removed**: Widened from `<4.1.0` to `>=4.0.0`, removed conftest.py monkey-patch
- **stop.ps1**: Now uses PID files + port-based kill (was just process name matching)
- **start.ps1**: Added Celery worker, Ollama detection, health check loop, PID file tracking
- **build_sidecar.bat**: Detects ARM64 via `%PROCESSOR_ARCHITECTURE%` (was hardcoded x64)

### Changed
- Updated all documentation to reflect Windows script parity and desktop build process
- Added `docs/desktop-app.md` link to README, deployment, and contributing docs

---

## [0.9.0] - 2025-02 (Pre-Release)

### Added — Phase 1: Backend Foundation
- FastAPI backend with async SQLAlchemy 2.0, aiosqlite (dev) / asyncpg (prod)
- JWT authentication with access/refresh tokens via python-jose
- 17 SQLAlchemy models, Pydantic schemas, 49 API endpoints
- Alembic initial migration (17 tables)
- Portfolio, holdings, transactions CRUD with automatic cumulative quantity / average price recalculation
- Excel import/export service (openpyxl) with preview and confirm flow
- Market data via yfinance with exchange suffix mapping (NSE→`.NS`, BSE→`.BO`, XETRA→`.DE`)
- RSI-14 calculation via pandas_ta with Wilder-smoothed fallback
- 5-zone action-needed alert system (DARK_RED, LOWER_MID, N, UPPER_MID, DARK_GREEN)
- Custom columns support (13 built-in + user-defined)
- Setup, start, stop, and health-check scripts (Unix + Windows)
- CI pipeline (`.github/workflows/ci.yml`)
- Full documentation suite (23 docs files)

### Added — Phase 2: Real-Time & Alerts
- WebSocket streaming: price stream, alert stream, connection manager
- Notification service: Email (SendGrid), Telegram Bot, WhatsApp (Twilio), SMS (Twilio), In-App toast
- Background tasks: Celery + Redis primary, APScheduler/asyncio fallback
- Alert engine with deduplication and zone-change detection

### Added — Phase 3: Web App UI
- Shared UI package (`packages/ui/`) with 10 components, theme tokens, animation presets
- Next.js 15 web app (`apps/web/`) with 13 routes
- Dashboard: portfolio table with color-coded action cells, RSI column, summary cards
- Charts: TradingView Lightweight Charts v4.2 (candlestick + volume), Recharts (donut)
- Pages: login, register, dashboard, holdings, watchlist, charts, alerts, import, settings, help
- Auth: Zustand stores, JWT in localStorage, auto-refresh on 401
- WebSocket client with auto-reconnect and exponential backoff

### Added — Phase 4: Tax, Multi-Currency, Mutual Funds, Dividends
- Indian tax: STCG 20%, LTCG 12.5% above ₹1.25L exemption, April–March FY
- German tax: Abgeltungssteuer 26.375%, €1,000 Freibetrag, optional church tax
- Tax harvesting suggestions
- Forex service: yfinance rates + DB cache
- Mutual fund service: mfapi.in NAV fetch, scheme search
- Dividend service: DRIP handling, yield calculation, monthly calendar
- Currency field added to Holding model + Alembic migration
- 3 new frontend pages: Tax, Mutual Funds, Dividends

### Added — Phase 5: Broker Integration & ML/AI
- Broker framework: abstract `BrokerAdapter` + Zerodha/ICICI adapters + 5 stubs (Groww, Angel One, Upstox, Deutsche Bank, Comdirect)
- Broker registry, service with Fernet-encrypted credentials, 6 API endpoints
- Technical indicators: MACD, Bollinger Bands, SMA/EMA, Support/Resistance, Fibonacci
- Risk metrics: Sharpe, Sortino, MaxDD, VaR (95%/99%), Beta, Alpha, Information Ratio, Calmar
- ML: LSTM price predictor (PyTorch), Isolation Forest anomaly detector (sklearn), FinBERT/keyword sentiment
- LLM chat: 4 providers (Ollama, OpenAI, Anthropic, Google) with fallback chain + graceful degradation
- AI chat API: sessions, insights, prediction, anomaly, sentiment endpoints
- 3 new frontend pages: AI Assistant, Risk Dashboard, Brokers

### Added — Phase 6: Advanced Features
- Goal tracking: CRUD API + SIP calculator (FV-annuity), sync from linked portfolio
- Backtesting: 3 strategies (RSI, SMA crossover, Bollinger), equity curve, metrics
- Portfolio optimizer: Mean-variance (scipy SLSQP + Monte Carlo fallback), efficient frontier
- Advanced viz page: 4 tabs (correlation heatmap, sector treemap, returns calendar, drawdown)
- Voice input: Web Speech API + waveform animation, auto-submit in AI assistant
- Onboarding wizard: 5-step overlay with confetti animation
- PWA: manifest.json, service worker, offline support
- 4 new frontend pages: Goals, Backtest, Optimizer, Analytics

### Added — Extras
- Tauri v2 desktop app (`apps/desktop/`) with shell/notification plugins, CI/CD workflow
- Playwright E2E: 32 smoke tests (auth, navigation, PWA, all pages)
- Account Aggregator: stub framework (Finvu, OneMoney, CAMS)
- CSV/PDF export service + 6 new API endpoints
- Keyboard shortcuts: Cmd+Shift+D/H/W/A/I navigation, Cmd+K command palette, `?` help dialog
- Performance: virtual scrolling table, lazy component factory

### Added — Optional Features (Final Polish)
**Backend Infrastructure:**
- Rate limiting: slowapi on auth endpoints (5/min register, 10/min login, 20/min refresh)
- Audit logging: structured log entries for auth actions
- `.env.example`: 74-line documented env template
- Seed script: demo user + 8 holdings + goals
- 2FA/TOTP: setup/verify/disable endpoints, pyotp integration

**Backend Features:**
- XIRR service: Newton-Raphson + bisection fallback
- Benchmark comparison: vs NIFTY50/SENSEX/DAX/S&P500/NASDAQ
- Stock comparison: compare up to 3 stocks side-by-side
- Stop-loss tracker: stored in `custom_fields` JSON
- Custom columns API: 13 built-in + user-defined columns
- Stock autocomplete: yfinance-based search

**Frontend UI Polish:**
- Live ticker bar with scrolling marquee animation
- Animated numbers: requestAnimationFrame count-up/down with easing
- Glassmorphism cards with backdrop blur
- Stock hover previews with price/P&L/RSI tooltip
- Table density controls (compact/comfortable/spacious)
- Mini portfolio widget: floating bottom-right expand/collapse

**Frontend Features:**
- Glossary popup: 27 financial term definitions with hover tooltips
- Contextual help: per-page help links (11 topic mappings)
- Enhanced help page: 10 topics + 6 FAQ accordion items with search
- IPO tracker page: upcoming/open/listed tabs
- Shareable snapshot page: anonymize toggle + copy-to-clipboard
- Reports & export page: HTML report, holdings CSV, transactions CSV

### Added — Enhancements
**Backend Services:**
- Net worth: multi-asset tracking (crypto, gold, FD, bonds, real estate) with live prices
- ESG scoring: yfinance sustainability data, portfolio-level aggregation
- What-if simulator: investment scenarios with benchmark comparison
- Earnings calendar: yfinance earnings dates per stock/portfolio
- F&O positions: full CRUD + P&L calculation
- 2 new models: `Asset` (multi-asset), `FnoPosition` (F&O)

**Backend Analytics:**
- Portfolio drift detection with target allocation
- Sector rotation tracking with month-over-month change
- Recurring transaction (SIP) detection with amount/interval matching
- SIP/dividend/earnings calendar aggregation
- 52-week high/low proximity via yfinance
- Data freshness with exchange-aware market hours
- Google Sheets CSV export with 3 sections
- 8 analytics endpoints (drift, sector rotation, calendar, recurring, 52week, freshness, sheets)

**Frontend Pages:**
- Net worth: Recharts donut, asset cards, add asset modal
- ESG: SVG semicircular gauges, traffic-light scores
- What-if simulator: simulation form + benchmark comparison bars
- Earnings calendar: month grid with urgency badges
- Market heatmap: CSS grid treemap with sector grouping
- F&O positions: table + add form + summary cards
- SIP calendar: monthly grid with color-coded dots

**Frontend Components:**
- Bulk edit panel: floating toolbar for bulk holding actions
- 52-week bar: horizontal proximity bar with gradient
- Freshness badge: Live/Recent/Stale pill with auto-refresh
- Holdings page: bulk edit mode with checkboxes
- Reports page: Google Sheets export card
- Alerts page: allocation drift alerts section

### Fixed — Audit Rounds 1–13 (126 fixes total)

**Data Integrity (Rounds 1–4):**
- Average price recalculation on transaction delete
- Dividend DRIP reinvest_price/reinvest_shares validation (must be > 0 when is_reinvested)
- Net worth stock items: added missing `current_value`, `asset_type`, `id`, `currency`, `purchase_price` fields
- Tax service LTCG exemption calculation for Indian jurisdiction
- Goal progress sync from linked portfolio

**API & Validation (Rounds 5–8):**
- Pydantic schema field constraints (min/max values, enums)
- Missing ownership checks in API endpoints
- Proper HTTP status codes (201 for creation, 204 for deletion)
- Rate limit configuration per endpoint group
- Import/export error handling improvements

**Frontend (Rounds 9–12):**
- WebSocket reconnection: skip codes 1000 (normal close), 1001 (going away), 4001 (auth failure)
- F&O form: strike_price conditionally required (not required for FUT)
- Chart component memory leak cleanup on unmount
- XSS fix: html.escape in export_service.py for user-generated content in HTML reports
- React 19 useRef compatibility fixes
- Zustand store hydration edge cases

**Infrastructure (Rounds 12–13):**
- passlib/bcrypt 5.0 compatibility monkey-patch
- Rate limiter disabled in test environment to prevent cross-test interference
- SQLAlchemy model import order in `models/__init__.py`

---

## Current Stats

| Metric | Count |
|---|---|
| REST API endpoints | 171 |
| WebSocket channels | 2 |
| Backend tests passing | 352 |
| Frontend routes (`page.tsx`) | 39 (32 dashboard) |
| Alembic migrations | 7 (head `e3f4a5b6c7d8`) |
| E2E tests | 32 |
| SQLAlchemy models | 21 |
| Sidebar nav items | 33 |
