# API Reference

> FinanceTracker REST API & WebSocket Documentation

**Base URL**: `http://localhost:8420/api/v1`
**Interactive Docs**: `http://localhost:8420/docs` (Swagger) | `http://localhost:8420/redoc` (ReDoc)

All endpoints require JWT authentication unless marked as **Public**. Include the token in the `Authorization` header:

```
Authorization: Bearer <access_token>
```

---

## Table of Contents

1. [Authentication](#authentication)
2. [Portfolios](#portfolios)
3. [Holdings](#holdings)
4. [Transactions](#transactions)
5. [Market Data & Charts](#market-data--charts)
6. [Alerts & Notifications](#alerts--notifications)
7. [Watchlist](#watchlist)
8. [Tax](#tax)
9. [Goals](#goals)
10. [Mutual Funds](#mutual-funds)
11. [Dividends](#dividends)
12. [Broker Connections](#broker-connections)
13. [AI / ML](#ai--ml)
14. [Import / Export](#import--export)
15. [Custom Columns](#custom-columns)
16. [Net Worth](#net-worth)
17. [ESG Scoring](#esg-scoring)
18. [What-If Simulator](#what-if-simulator)
19. [Earnings Calendar](#earnings-calendar)
20. [F&O Positions](#fo-positions)
21. [Analytics](#analytics)
22. [IPO Tracker](#ipo-tracker)
23. [Benchmark & Comparison](#benchmark--comparison)
24. [Stop-Loss Tracker](#stop-loss-tracker)
25. [Settings & Configuration](#settings--configuration)
26. [WebSocket Channels](#websocket-channels)
27. [Corporate Actions](#corporate-actions)
28. [Additional Endpoints](#additional-endpoints)
29. [Common Response Formats](#common-response-formats)
30. [Error Handling](#error-handling)

---

## Authentication

### Register

**Public** -- Create a new user account.

```
POST /auth/register
```

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "securePassword123!",
  "display_name": "Ankit"
}
```

**Response** `201 Created`:
```json
{
  "id": 1,
  "email": "user@example.com",
  "display_name": "Ankit",
  "preferred_currency": "INR",
  "theme_preference": "dark",
  "is_active": true,
  "created_at": "2025-01-15T10:30:00Z",
  "totp_enabled": false,
  "phone": null,
  "telegram_chat_id": null
}
```

### Login

**Public** -- Authenticate and receive JWT tokens.

```
POST /auth/login
```

**Request Body:**
```json
{
  "email": "user@example.com",
  "password": "securePassword123!",
  "totp_code": "123456"
}
```

The `totp_code` field is only required if the user has 2FA enabled. A one-time backup code may be supplied in the `totp_code` field instead of an authenticator code — it is verified as a TOTP fallback and consumed on use (single-use).

**Response** `200 OK`:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer"
}
```

If 2FA is enabled and no `totp_code` was provided, the response is instead:
```json
{
  "requires_2fa": true,
  "message": "Please provide TOTP code"
}
```
Re-submit the login request with the `totp_code` field to receive tokens.

### Refresh Token

**Public** -- Exchange a refresh token for a new access token.

```
POST /auth/refresh
```

**Request Body:**
```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

**Response** `200 OK`:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer"
}
```

### Forgot Password

**Public** -- Start a password reset. Always returns a generic `200` (even for unknown emails) so the endpoint never reveals whether an account exists. If the account exists, a single-use, 1-hour token is stored (hashed) and a reset link is emailed (best-effort — silently degrades if SendGrid is unconfigured).

```
POST /auth/forgot-password
```

**Request Body:**
```json
{
  "email": "user@example.com"
}
```

**Response** `200 OK`:
```json
{
  "message": "If that email exists, a reset link has been sent."
}
```

### Reset Password

**Public** -- Complete a password reset using the single-use token from the reset email. Returns `400` if the token is invalid, already used, or expired. On success the user's other outstanding reset tokens are also invalidated.

```
POST /auth/reset-password
```

**Request Body:**
```json
{
  "token": "raw-token-from-email",
  "new_password": "newPassword456!"
}
```

**Response** `200 OK`:
```json
{
  "message": "Password has been reset successfully"
}
```

### Change Password

Change the current user's password (requires the current password).

```
POST /auth/change-password
```

**Request Body:**
```json
{
  "current_password": "oldPassword123!",
  "new_password": "newPassword456!"
}
```

**Response** `200 OK`:
```json
{
  "message": "Password updated successfully"
}
```

### Setup 2FA

Enable TOTP-based two-factor authentication. The secret is NOT persisted yet — call `/auth/2fa/verify` with the secret and a valid code to activate it. Returns `400` if 2FA is already enabled.

```
POST /auth/2fa/setup
```

**Response** `200 OK`:
```json
{
  "totp_secret": "JBSWY3DPEHPK3PXP",
  "totp_uri": "otpauth://totp/FinanceTracker:user@example.com?secret=JBSWY3DPEHPK3PXP&issuer=FinanceTracker"
}
```

### Verify 2FA

Confirm 2FA setup by verifying a TOTP code against the secret from `/auth/2fa/setup`. The secret is only persisted on success. Returns `400` if 2FA is already enabled (disable it first).

```
POST /auth/2fa/verify
```

**Request Body:**
```json
{
  "secret": "JBSWY3DPEHPK3PXP",
  "code": "123456"
}
```

**Response** `200 OK`:
```json
{
  "verified": true,
  "message": "2FA is now active",
  "backup_codes": [
    "3f8a-1c2d", "9b0e-4a7f", "2d5c-8e1b", "6a3f-0c9d", "7e2b-5f4a",
    "1c8d-3b6e", "0f4a-9d2c", "8b7e-1a5f", "5d3c-6e0b", "4a9f-2c8d"
  ]
}
```

On activation, 10 one-time backup (recovery) codes are returned **exactly once** — store them now, as they are never shown again. Each code is `xxxx-xxxx` formatted, works a single time in place of a TOTP code (at login), and matching is case- and separator-insensitive. Only SHA-256 hashes are persisted server-side.

### Backup Codes Status

Return how many unused 2FA backup codes remain. The codes themselves are never returned.

```
GET /auth/2fa/backup-codes/status
```

**Response** `200 OK`:
```json
{
  "remaining": 8
}
```

### Regenerate Backup Codes

Generate a fresh set of 10 backup codes, invalidating any previous ones. Requires a current TOTP code (`400` if 2FA is not enabled or the code is invalid). The raw codes are returned exactly once.

```
POST /auth/2fa/backup-codes/regenerate
```

**Request Body:**
```json
{
  "code": "123456"
}
```

**Response** `200 OK`:
```json
{
  "backup_codes": [
    "3f8a-1c2d", "9b0e-4a7f", "2d5c-8e1b", "6a3f-0c9d", "7e2b-5f4a",
    "1c8d-3b6e", "0f4a-9d2c", "8b7e-1a5f", "5d3c-6e0b", "4a9f-2c8d"
  ],
  "message": "Save these backup codes now — each works once and they will not be shown again."
}
```

Disabling 2FA (`POST /auth/2fa/disable`) clears any stored backup codes.

---

## Portfolios

### List Portfolios

```
GET /portfolios
```

**Response** `200 OK`:
```json
[
  {
    "id": 1,
    "user_id": 1,
    "name": "Indian Stocks",
    "description": "NSE/BSE equity portfolio",
    "currency": "INR",
    "is_default": true,
    "created_at": "2025-01-15T10:30:00Z",
    "updated_at": null
  }
]
```

### Create Portfolio

```
POST /portfolios
```

**Request Body:**
```json
{
  "name": "German ETFs",
  "description": "XETRA-listed ETF portfolio",
  "currency": "EUR",
  "is_default": false
}
```

### Get Portfolio Summary

Returns the main output table data with color-coded action states.

```
GET /portfolios/{portfolio_id}/summary
```

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `display_currency` | string | *(native currency)* | Optional target currency (e.g. `INR`/`EUR`/`USD`). When set and different from the native currency, additive `*_display` convenience fields are layered on top — existing native fields are never altered. |

**Response** `200 OK`:
```json
{
  "portfolio_id": 1,
  "portfolio_name": "Indian Stocks",
  "currency": "INR",
  "total_invested": 1162500.00,
  "total_current_value": 1250000.00,
  "total_pnl_percent": 7.53,
  "holdings": [
    {
      "holding_id": 1,
      "stock_symbol": "RELIANCE",
      "stock_name": "Reliance Industries Ltd",
      "exchange": "NSE",
      "currency": "INR",
      "quantity": 50,
      "avg_price": 2450.00,
      "current_price": 2680.50,
      "action_needed": "N",
      "rsi": 62.3,
      "pnl_percent": 9.41,
      "sector": "Energy"
    },
    {
      "holding_id": 2,
      "stock_symbol": "HDFCBANK",
      "stock_name": "HDFC Bank Ltd",
      "exchange": "NSE",
      "currency": "INR",
      "quantity": 30,
      "avg_price": 1650.00,
      "current_price": 1580.00,
      "action_needed": "Y_LOWER_MID",
      "rsi": 28.5,
      "pnl_percent": -4.24,
      "sector": "Banking"
    }
  ]
}
```

**Action Needed Values:**
| Value | Meaning | Visual |
|---|---|---|
| `N` | Price not in any alert range | No highlight |
| `Y_LOWER_MID` | Price in lower mid range (LMR2 to LMR1) | Light red background pulse |
| `Y_UPPER_MID` | Price in upper mid range (UMR1 to UMR2) | Light green background pulse |
| `Y_DARK_RED` | Price at/below base level | Dark red with warning icon |
| `Y_DARK_GREEN` | Price at/above top level | Dark green with celebration icon |

### Update Portfolio

```
PUT /portfolios/{portfolio_id}
```

### Delete Portfolio

```
DELETE /portfolios/{portfolio_id}
```

---

## Holdings

### Get Holding Detail

```
GET /holdings/{holding_id}
```

Returns full holding data including all range levels, transactions summary, and custom fields.

### Create Holding

Add a stock manually from the dashboard.

```
POST /holdings
```

**Request Body:**
```json
{
  "portfolio_id": 1,
  "stock_symbol": "TCS.NS",
  "stock_name": "Tata Consultancy Services",
  "exchange": "NSE",
  "lower_mid_range_1": 3800.00,
  "lower_mid_range_2": 3600.00,
  "upper_mid_range_1": 4200.00,
  "upper_mid_range_2": 4400.00,
  "base_level": 3400.00,
  "top_level": 4600.00,
  "sector": "IT",
  "notes": "Core long-term holding"
}
```

### Update Holding

Inline edit any field including range levels.

```
PATCH /holdings/{holding_id}
```

**Request Body** (partial update):
```json
{
  "base_level": 3200.00,
  "top_level": 4800.00,
  "notes": "Updated ranges based on Q3 results"
}
```

### Delete Holding

```
DELETE /holdings/{holding_id}
```

---

## Transactions

### List Transactions

```
GET /transactions/
```

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `holding_id` | int | - | Filter by holding |
| `skip` | int | 0 | Number of records to skip |
| `limit` | int | 200 | Max records to return (1–1000) |

### Create Transaction

```
POST /transactions/
```

**Request Body:**
```json
{
  "holding_id": 1,
  "transaction_type": "BUY",
  "date": "2025-01-15",
  "quantity": 10,
  "price": 2450.00,
  "brokerage": 25.00,
  "notes": "Added on dip",
  "source": "MANUAL"
}
```

After creating a transaction, the holding's `cumulative_quantity` and `average_price` are automatically recalculated.

### Delete Transaction

```
DELETE /transactions/{transaction_id}
```

Recalculates holding's cumulative quantity and average price.

---

## Market Data & Charts

### Get Current Quote

```
GET /market/quote/{symbol}
```

**Example**: `GET /market/quote/RELIANCE.NS`

**Response** `200 OK`:
```json
{
  "symbol": "RELIANCE.NS",
  "name": "Reliance Industries Ltd",
  "exchange": "NSE",
  "current_price": 2680.50,
  "previous_close": 2665.00,
  "open": 2670.00,
  "day_high": 2695.00,
  "day_low": 2660.00,
  "volume": 8542300,
  "market_cap": 18150000000000,
  "pe_ratio": 28.5,
  "fifty_two_week_high": 3024.90,
  "fifty_two_week_low": 2220.30,
  "last_updated": "2025-01-20T14:30:00Z",
  "data_source": "yfinance",
  "is_stale": false
}
```

### Get Historical OHLCV

```
GET /market/history/{symbol}
```

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `exchange` | string | `NSE` | Exchange: NSE, BSE, XETRA, etc. |
| `days` | int | 30 | Number of trading days (1–730) |

**Response** `200 OK`:
```json
{
  "symbol": "RELIANCE.NS",
  "exchange": "NSE",
  "data": [
    {
      "date": "2025-01-20",
      "open": 2670.00,
      "high": 2695.00,
      "low": 2660.00,
      "close": 2680.50,
      "volume": 8542300
    }
  ]
}
```

### Get Price Chart Data

OHLCV data for candlestick charts.

```
GET /charts/price/{symbol}?exchange=NSE&days=30
```

**Response** `200 OK`:
```json
{
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "data": [
    {
      "date": "2024-12-21",
      "open": 2610.00,
      "high": 2635.00,
      "low": 2600.00,
      "close": 2625.00,
      "volume": 7823400
    }
  ]
}
```

### Get RSI Chart Data

```
GET /charts/rsi/{symbol}?exchange=NSE&days=30&period=14
```

**Response** `200 OK`:
```json
{
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "period": 14,
  "data": [
    {"date": "2024-12-21", "close": 2625.00, "rsi": 55.2},
    {"date": "2024-12-22", "close": 2641.50, "rsi": 57.8}
  ]
}
```

### Get Technical Indicators

Computes all indicators in one call (no per-indicator selection).

```
GET /indicators/technical/{symbol}
```

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `exchange` | string | `NSE` | Exchange |
| `days` | int | 90 | Data window (7–365) |

**Response** `200 OK`:
```json
{
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "dates": ["2025-01-20"],
  "rsi": [62.3],
  "macd": {"macd_line": [15.2], "signal_line": [12.8], "histogram": [2.4]},
  "bollinger_bands": {"upper": [2750.0], "middle": [2650.0], "lower": [2550.0], "bandwidth": [7.5]},
  "sma": {"sma_20": [2648.0], "sma_50": [2610.0]},
  "ema": {"ema_20": [2652.0], "ema_50": [2620.0]},
  "support_resistance": {"supports": [2600.0, 2450.0], "resistances": [2700.0, 2850.0]},
  "fibonacci": {"high": 3024.0, "low": 2220.0, "levels": {"0.236": 2410.0, "0.382": 2527.0, "0.5": 2622.0, "0.618": 2717.0}}
}
```

### Refresh Prices

```
POST /market/refresh
```

Triggers a price refresh for all holdings belonging to the authenticated user. Updates `current_price`, `current_rsi`, and `action_needed` for every holding.

**Response** `200 OK`:
```json
{
  "status": "completed",
  "updated": 8,
  "failed": 0,
  "duration_ms": 3200
}
```

### Search Stocks

```
GET /market/search
```

Search for stocks by name or symbol using Yahoo Finance search API.

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `q` | string | *(required)* | Search query (1–50 chars) |
| `exchange` | string | `NSE` | Exchange filter |
| `limit` | int | 10 | Max results (1–50) |

**Response** `200 OK`:
```json
{
  "results": [
    {
      "symbol": "RELIANCE.NS",
      "name": "Reliance Industries Limited",
      "exchange": "NSE",
      "type": "EQUITY"
    }
  ]
}
```

### Stock Screener

```
GET /market/screener
```

Screens a curated, liquid per-exchange universe (plus any explicit `symbols`) against the given filters — not the whole market, which keeps every scan fast without a paid screener API. Each symbol is fetched from yfinance with bounded concurrency and a per-symbol timeout; unreachable symbols are skipped.

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `exchange` | string | `NSE` | Exchange for the default universe: `NSE`, `XETRA` |
| `symbols` | string | - | Optional comma-separated symbols to add to the curated universe |
| `market_cap_min` / `market_cap_max` | float | - | Market-cap bounds |
| `pe_min` / `pe_max` | float | - | P/E bounds |
| `dividend_yield_min` | float | - | Minimum dividend yield (%) |
| `price_min` / `price_max` | float | - | Price bounds |
| `sector` | string | - | Sector substring match |
| `rsi_min` / `rsi_max` | float | - | RSI bounds (0–100) |
| `week52_min` / `week52_max` | float | - | 52-week range position bounds (0–100 %) |
| `day_change_min` / `day_change_max` | float | - | Day-change % bounds |

All filters are optional; only the provided ones are applied.

### Get Portfolio Allocation

```
GET /charts/portfolio/allocation/{portfolio_id}
```

Returns data for donut/treemap chart (`by_stock` and `by_sector` breakdowns with percentages).

### Get Portfolio Performance

```
GET /charts/portfolio/performance/{portfolio_id}?days=90
```

Returns portfolio value over time for a line chart.

---

## Alerts & Notifications

### List Alerts

```
GET /alerts
```

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `skip` | int | 0 | Number of records to skip |
| `limit` | int | 200 | Max records to return (1–1000) |

### Create Alert

```
POST /alerts
```

**Request Body:**
```json
{
  "holding_id": 1,
  "alert_type": "PRICE_RANGE",
  "condition": {
    "price_above": 3000.00,
    "price_below": 2200.00
  },
  "channels": ["email", "telegram", "in_app"],
  "is_active": true
}
```

Valid channels are `in_app`, `email`, `telegram`, `whatsapp`, and `sms`. When omitted, `channels` defaults to `["in_app"]`.

### Update Alert Channels

```
PUT /alerts/{alert_id}/channels
```

Replaces the alert's notification channels. An unrecognized channel returns `400`.

**Request Body:**
```json
{
  "channels": ["email", "whatsapp", "telegram", "sms", "in_app"]
}
```

### Delete Alert

```
DELETE /alerts/{alert_id}
```

### Get Alert / Notification History

```
GET /alerts/history
```

Returns all previously triggered alerts (most recent first) and also runs a live check of all current alerts.

---

## Watchlist

### List Watchlist Items

```
GET /watchlist
```

### Add to Watchlist

```
POST /watchlist
```

**Request Body:**
```json
{
  "stock_symbol": "BAJFINANCE",
  "stock_name": "Bajaj Finance Ltd",
  "exchange": "NSE",
  "target_buy_price": 6800.00,
  "lower_mid_range_1": 7000.00,
  "lower_mid_range_2": 6500.00,
  "upper_mid_range_1": 7500.00,
  "upper_mid_range_2": 8000.00,
  "base_level": 6000.00,
  "top_level": 8500.00,
  "notes": "Waiting for dip below 7000"
}
```

### Remove from Watchlist

```
DELETE /watchlist/{item_id}
```

---

## Tax

### Get Tax Summary

```
GET /tax/summary
```

**Query Parameters:**
| Parameter | Type | Required | Description |
|---|---|---|---|
| `financial_year` | string | Yes | e.g., `2024-25` (India) or `2024` (Germany) |
| `jurisdiction` | string | Yes | `IN` or `DE` |

**Response** `200 OK`:
```json
{
  "financial_year": "2024-25",
  "jurisdiction": "IN",
  "summary": {
    "total_stcg": 45000.00,
    "stcg_tax": 9000.00,
    "total_ltcg": 185000.00,
    "ltcg_exempt": 125000.00,
    "ltcg_taxable": 60000.00,
    "ltcg_tax": 7500.00,
    "dividend_income": 12000.00,
    "dividend_tds": 1200.00,
    "total_tax_liability": 17700.00
  },
  "transactions": [...]
}
```

### Get Tax Harvesting Suggestions

```
GET /tax/harvesting
```

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `jurisdiction` | string | `IN` | `IN` or `DE` |

**Response** `200 OK`:
```json
[
  {
    "holding_id": 3,
    "stock_symbol": "INFY",
    "unrealized_loss": -15000.00,
    "potential_tax_saving": 3000.00,
    "gain_type": "STCG"
  }
]
```

### Download Tax Report

Download a consolidated, ITR-ready capital-gains statement (per-record rows plus a totals summary) scoped to the current user, as a downloadable CSV or a self-contained printable HTML file.

```
GET /tax/report/{financial_year}
```

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `jurisdiction` | string | `IN` | `IN` or `DE` |
| `format` | string | `csv` | `csv` or `html` (any other value → `400`) |

Returns the file with a `Content-Disposition: attachment` header (`text/csv` or `text/html`).

### German Saver's Allowance (Sparer-Pauschbetrag)

```
GET /tax/allowance
```

Returns Sparer-Pauschbetrag usage for a German calendar year: `{ total_allowance, used, remaining, filing }`. The allowance is EUR 1000 (single) / EUR 2000 (joint), read from the user's tax settings. Only Germany is supported — a non-`DE` jurisdiction returns `400`.

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `jurisdiction` | string | `DE` | Only `DE` is supported |
| `financial_year` | string | *(current year)* | Calendar year, e.g. `2024` |

### German Vorabpauschale Estimate

```
GET /tax/vorabpauschale/{portfolio_id}
```

Estimated German Vorabpauschale (advance lump-sum tax) per German fund holding in a portfolio, using the Basiszins table. Because exact fund start/end values are not stored, current holding values are used as a proxy, so the result is flagged `is_estimate: true`.

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `year` | int | *(current year)* | Tax year |

### LTCG Holding-Period Timer

```
GET /tax/holding-period/{portfolio_id}
```

Per-FIFO-lot countdown to Indian LTCG eligibility. For every still-open FIFO buy lot of each Indian (NSE/BSE) holding, reports when the lot crosses the 12-calendar-month mark and becomes LTCG-eligible (taxed at 12.5% instead of the 20% STCG rate). `days_remaining` counts down to `ltcg_date` (0 or negative = already LTCG). German / other-jurisdiction holdings are skipped — the short-/long-term split is India-specific. Where a live price is available, STCG lots within 30 days of eligibility carry a best-effort `potential_tax_saving` = unrealized gain × (20% − 12.5%). Lots are sorted soonest-to-eligible first. Returns `404` if the portfolio does not belong to the user.

**Response** `200 OK`:
```json
{
  "portfolio_id": 1,
  "lots": [
    {
      "stock_symbol": "RELIANCE",
      "purchase_date": "2024-08-20",
      "quantity": 50,
      "ltcg_date": "2025-08-20",
      "days_remaining": 24,
      "status": "STCG",
      "potential_tax_saving": 1725.00
    }
  ],
  "summary": {
    "stcg_lots": 1,
    "ltcg_lots": 3,
    "next_eligible_date": "2025-08-20"
  }
}
```

`potential_tax_saving` is `null` for lots outside the 30-day window, without a live price, or with no unrealized gain. `next_eligible_date` is `null` when there are no STCG lots.

### Update Tax Settings

```
PUT /tax/settings
```

Updates the German filing election / church-tax flag stored in `user_preferences.tax_settings`. Only the provided fields change; others are preserved.

**Request Body** (partial update):
```json
{
  "filing": "joint",
  "church_tax": false
}
```

`filing` is `single` or `joint`. Returns the merged `{ "tax_settings": {...} }`.

### Set Holding Fund Type

```
PUT /tax/fund-type/{holding_id}
```

Sets a holding's fund class, used for German Teilfreistellung (partial exemption). Pass `null` to clear it.

**Request Body:**
```json
{
  "fund_type": "EQUITY_ETF"
}
```

`fund_type` is one of `STOCK`, `EQUITY_ETF`, `MIXED_ETF`, `BOND_ETF`, `REAL_ESTATE_ETF`, or `null`.

---

## Goals

### List Goals

```
GET /goals
```

### Create Goal

```
POST /goals
```

**Request Body:**
```json
{
  "name": "House Down Payment",
  "target_amount": 2500000.00,
  "target_date": "2027-12-31",
  "category": "HOUSE",
  "linked_portfolio_id": 1
}
```

**Response** includes calculated `monthly_sip_needed`.

### FIRE Projection

Project a path to FIRE (financial independence / early retirement). This is a pure calculator — nothing is persisted.

```
GET /goals/fire
```

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `monthly_contribution` | float | *(required)* | Monthly investment (≥ 0) |
| `annual_return_pct` | float | *(required)* | Expected annual return % |
| `annual_expenses` | float | *(required)* | Annual expenses (> 0) |
| `current_net_worth` | float | *(user's net worth)* | Starting corpus; sourced from the user's aggregated net worth when omitted |
| `withdrawal_rate_pct` | float | 4.0 | Safe withdrawal rate % (> 0) |
| `step_up_pct` | float | 0.0 | Annual contribution step-up % (≥ 0) |

Returns the projected FIRE number, years/date to reach it, and the `current_net_worth` used.

### SIP Projection

Project a SIP's corpus with vs. without an annual step-up. Pure calculator.

```
GET /goals/sip-projection
```

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `monthly_sip` | float | *(required)* | Monthly SIP amount (≥ 0) |
| `annual_return_pct` | float | *(required)* | Expected annual return % |
| `years` | int | *(required)* | Investment horizon (1–100) |
| `current_amount` | float | 0.0 | Existing corpus (≥ 0) |
| `step_up_pct` | float | 0.0 | Annual SIP step-up % (≥ 0) |

### Update Goal Progress

```
PUT /goals/{goal_id}
```

### Delete Goal

```
DELETE /goals/{goal_id}
```

---

## Mutual Funds

### List Mutual Fund Holdings

```
GET /mutual-funds
```

### Add Mutual Fund

```
POST /mutual-funds
```

**Request Body:**
```json
{
  "portfolio_id": 1,
  "scheme_code": "119551",
  "scheme_name": "Axis Bluechip Fund - Direct Growth",
  "folio_number": "1234567890",
  "units": 250.5,
  "invested_amount": 100000.00
}
```

### Import Mutual Funds from CSV

Bulk import via CSV upload:

```
POST /import-export/csv/mutual-funds?portfolio_id={id}
```

**Request Body**: Multipart form with `.csv` file (template available at `GET /import-export/export/template/mutual-funds`).

Mutual-fund holdings can also be imported from a CAMS/KFintech CAS PDF — see [Import CAS PDF](#import-cas-pdf) in the Import / Export section.

### Portfolio Overlap X-Ray

```
GET /mutual-funds/overlap
```

Best-effort overlap analysis across the user's mutual fund holdings. Attempts to fetch each fund's underlying constituents (via yfinance when a scheme maps to a fund/ETF ticker) and returns a pairwise overlap matrix plus look-through single-stock concentration. Funds without constituent data are flagged; the response degrades gracefully and never fabricates holdings.

### Expense / Fee Analysis

```
GET /mutual-funds/expense-analysis
```

Value-weighted expense ratio and a multi-year fee-drag projection. Reads expense ratios from yfinance for schemes that map to a ticker; unknown ratios are surfaced and excluded from the weighted average and projection.

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `assumed_return` | float | 0.10 | Assumed gross annual return used to project fee drag (0.0–0.5) |

---

## Broker Connections

All broker routes live under the `/broker` prefix (singular).

### List Connected Brokers

```
GET /broker/
```

### List Available Brokers

```
GET /broker/available
```

Returns each registered broker's name, display name, and status (`available` or `coming_soon`).

### Connect Broker

```
POST /broker/connect
```

**Request Body:**
```json
{
  "broker_name": "zerodha",
  "api_key": "your_api_key",
  "api_secret": "your_api_secret",
  "additional_params": null
}
```

API keys are encrypted with Fernet before storage.

**Response** `201 Created` includes an optional `login_url` field. For OAuth brokers (e.g. Zerodha), `login_url` is set — open it in a browser, authorize, then complete the connection by re-POSTing `/broker/connect` with `"additional_params": {"request_token": "token_from_redirect"}`. There are no separate auth-url/callback endpoints.

### Check Connection Status

```
GET /broker/{connection_id}/status
```

### Sync Holdings from Broker

```
POST /broker/{connection_id}/sync
```

Fetches latest holdings from the broker into the local portfolio. Returns `holdings_synced`, `new_holdings`, `updated_holdings`, and `errors`.

### Disconnect Broker

```
DELETE /broker/{connection_id}
```

---

## AI / ML

### Chat with AI Assistant

```
POST /ai/chat
```

**Request Body:**
```json
{
  "message": "Which of my stocks are underperforming the Nifty 50 this month?",
  "session_id": null
}
```

Pass an existing integer `session_id` to continue a conversation, or `null` to start a new session.

**Response** `200 OK`:
```json
{
  "session_id": 1,
  "response": "Based on your portfolio, 3 stocks are underperforming Nifty 50 this month:\n\n1. **INFY.NS** (-3.2% vs Nifty +1.8%)\n2. **HDFCBANK.NS** (-0.75% vs Nifty +1.8%)\n3. **WIPRO.NS** (-1.5% vs Nifty +1.8%)\n\nInfosys has the widest gap. Its RSI is at 35, approaching oversold territory.",
  "provider": "ollama",
  "model": "llama3.2"
}
```

### Get AI-Generated Insights

```
GET /ai/insights
```

**Response** `200 OK`:
```json
{
  "insights": [
    {
      "type": "alert_summary",
      "title": "3 stocks approaching upper mid range",
      "description": "TCS, Infosys, and Wipro are within 5% of your upper mid range 1.",
      "priority": "medium"
    },
    {
      "type": "risk",
      "title": "Portfolio Sharpe ratio improved",
      "description": "Your Sharpe ratio improved from 1.2 to 1.8 this month.",
      "priority": "low"
    }
  ],
  "provider_status": "online"
}
```

### Get Price Prediction

```
GET /ai/prediction/{symbol}
```

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `exchange` | string | `NSE` | Exchange |
| `days_ahead` | int | 5 | Prediction horizon in days (1–30) |

**Response** `200 OK`:
```json
{
  "symbol": "RELIANCE.NS",
  "current_price": 2680.50,
  "predictions": [
    {"date": "2025-01-21", "predicted_price": 2695.00, "confidence": 0.72}
  ],
  "model_accuracy": 0.81,
  "direction": "up",
  "confidence": 0.72
}
```

### Get News Sentiment

```
GET /ai/sentiment/{symbol}
```

**Response** `200 OK`:
```json
{
  "symbol": "RELIANCE.NS",
  "overall_sentiment": "bullish",
  "sentiment_score": 0.65,
  "news_items": [
    {
      "title": "Reliance Jio Adds 5M Subscribers in December",
      "source": "Economic Times",
      "date": "2025-01-19",
      "sentiment": "positive",
      "score": 0.82,
      "url": "https://..."
    }
  ],
  "analysis_method": "keyword"
}
```

### Get Portfolio Risk Metrics

```
GET /indicators/risk/{portfolio_id}
```

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `days` | int | 252 | Lookback window (30–1000) |
| `benchmark` | string | `^NSEI` | Benchmark symbol |

**Response** `200 OK`:
```json
{
  "sharpe_ratio": 1.82,
  "sortino_ratio": 2.15,
  "max_drawdown": -12.5,
  "max_drawdown_duration_days": 14,
  "value_at_risk_95": -45000.00,
  "value_at_risk_99": -68000.00,
  "volatility_annual": 18.7,
  "beta": 0.92,
  "alpha": 2.1,
  "information_ratio": 0.45,
  "calmar_ratio": 1.1
}
```

### Portfolio Hedge Estimate

```
GET /indicators/hedge/{portfolio_id}
```

A rough, **informational** estimate of the cost of hedging portfolio downside with index puts. This is NOT an options quote or trade advice — the premium is a crude heuristic, not a real option price. Portfolio value is summed from holdings (`quantity × current_price`, falling back to average price); beta reuses the risk calculator's portfolio beta when available (else defaults to `1.0`). Returns `404` if the portfolio does not belong to the user.

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `protection_pct` | float | 80.0 | Share of notional to protect (0–100) |
| `months` | float | 3.0 | Hedge horizon in months (>0, ≤24) |
| `implied_vol_pct` | float | 20.0 | Assumed implied volatility % (0–200) |
| `index_price` | float | 0.0 | Hedging index level; `0` (or omitted) uses the service default |

**Response** `200 OK`:
```json
{
  "portfolio_value": 1250000.00,
  "beta": 0.92,
  "notional_hedged": 920000.00,
  "index_price": 22000.00,
  "puts_needed": 41.8182,
  "est_premium_per_put": 440.00,
  "est_total_cost": 18400.00,
  "cost_pct_of_portfolio": 1.472,
  "assumptions": {
    "implied_vol_pct": 20.0,
    "months": 3.0,
    "protection_pct": 80.0
  },
  "disclaimer": "..."
}
```

---

## Import / Export

### Import from Excel

```
POST /import-export/excel?portfolio_id={id}
```

**Request**: Multipart form data with `.xlsx` file. The import is one-shot — holdings and transactions are created immediately (no preview/confirm step).

**Expected Excel Columns:**
| Column | Required | Description |
|---|---|---|
| Stock Name | Yes | Stock name or symbol |
| Date of Purchase | Yes | Purchase date |
| Purchase Quantity | Yes | Number of shares bought |
| Purchase Price | Yes | Price per share |
| Lower Mid Range 1 | No | Upper bound of lower caution zone |
| Lower Mid Range 2 | No | Lower bound of lower caution zone |
| Upper Mid Range 1 | No | Lower bound of upper opportunity zone |
| Upper Mid Range 2 | No | Upper bound of upper opportunity zone |
| Base Level | No | Critical support level |
| Top Level | No | Target price level |
| Sale Quantity | No | Number of shares sold |
| Sale Price | No | Sale price per share |
| Sale Date | No | Date of sale |

**Response** `200 OK`:
```json
{
  "status": "success",
  "rows_parsed": 15,
  "holdings_created": 14,
  "transactions_created": 15,
  "holdings_updated": 1
}
```

### Import from OFX / QFX

```
POST /import-export/import/ofx?portfolio_id={id}
```

**Request**: Multipart form data with an `.ofx` or `.qfx` broker/bank statement. Investment `BUY` / `SELL` transactions are parsed; if none are present, bank statement transactions are imported as a fallback.

### Import from QIF

```
POST /import-export/import/qif?portfolio_id={id}
```

**Request**: Multipart form data with a `.qif` (Quicken Interchange Format) file. Both investment and bank account types are supported.

### Import CAS PDF

```
POST /import-export/import/cas?portfolio_id={id}&password={optional}
```

**Request**: Multipart form data with a CAMS/KFintech Consolidated Account Statement `.pdf`. Imports mutual-fund holdings from the statement. `password` is optional (supply it for password-protected statements). Requires the optional `casparser` package (the `cas` extra: `uv sync --extra cas`); returns `501` with an install hint if it is not installed.

### Export to Excel

```
GET /import-export/export/excel/{portfolio_id}
```

Returns a downloadable single-sheet `.xlsx` file.

### Export to Excel Workbook (multi-sheet)

```
GET /import-export/export/xlsx/{portfolio_id}
```

Returns a downloadable multi-sheet `.xlsx` workbook with **Holdings**, **Transactions**, **Dividends**, and **Summary** sheets.

### Export Everything (ZIP bundle)

```
GET /import-export/export/bundle/{portfolio_id}
```

Returns a single `.zip` containing `holdings.csv`, `transactions.csv`, `portfolio_backup.json`, `report.html`, `portfolio_workbook.xlsx`, `portfolio_report.pdf`, and a `README.txt`.

---

## Custom Columns

### List Columns

```
GET /columns
```

**Response** `200 OK`:
```json
{
  "builtin_columns": [
    {"name": "stock_name", "label": "Stock", "visible": true, "order": 0},
    {"name": "cumulative_quantity", "label": "Quantity", "visible": true, "order": 1},
    {"name": "average_price", "label": "Avg Price", "visible": true, "order": 2},
    {"name": "current_price", "label": "Current Price", "visible": true, "order": 3},
    {"name": "action_needed", "label": "Action Needed", "visible": true, "order": 4},
    {"name": "current_rsi", "label": "RSI", "visible": true, "order": 5},
    {"name": "pnl_percent", "label": "P&L %", "visible": false, "order": 6},
    {"name": "sector", "label": "Sector", "visible": false, "order": 7},
    {"name": "day_change", "label": "Day Change", "visible": false, "order": 8},
    {"name": "volume", "label": "Volume", "visible": false, "order": 9},
    {"name": "dividend_yield", "label": "Div Yield", "visible": false, "order": 10},
    {"name": "notes", "label": "Notes", "visible": false, "order": 11}
  ],
  "custom_columns": [
    {"name": "target_pe", "label": "Target PE", "type": "number", "visible": true, "order": 12}
  ]
}
```

### Create Custom Column

```
POST /columns
```

**Request Body:**
```json
{
  "name": "target_pe",
  "label": "Target PE",
  "type": "number",
  "default_value": null
}
```

### Reorder Columns

```
PUT /columns/order
```

**Request Body:**
```json
{
  "order": ["stock_name", "current_price", "action_needed", "current_rsi", "pnl_percent", "target_pe"]
}
```

### Delete Custom Column

```
DELETE /columns/{name}
```

---

## Settings & Configuration

### Get All Settings

```
GET /settings
```

Returns all settings for the current user grouped into four categories: `display`, `notifications`, `market`, and `integrations`.

**Response** `200 OK`:
```json
{
  "display": {
    "preferred_currency": "INR",
    "theme_preference": "dark",
    "display_name": "Ankit"
  },
  "notifications": {
    "email_enabled": true,
    "telegram_enabled": true,
    "whatsapp_enabled": false,
    "sms_enabled": false,
    "in_app_enabled": true,
    "alert_check_interval": 60
  },
  "market": {
    "price_refresh_interval": 5,
    "default_chart_days": 30
  },
  "integrations": {
    "llm_provider": "ollama",
    "ollama_url": "http://localhost:11434",
    "ollama_model": "llama3.2",
    "has_sendgrid_key": false,
    "has_telegram_bot": false
  }
}
```

### Update Settings

```
PUT /settings
```

The update body is a flat set of optional keys — only the fields you send are changed. Notification toggles (including `sms_enabled`) are merged into `notification_preferences`.

**Request Body** (partial update):
```json
{
  "preferred_currency": "EUR",
  "theme_preference": "light",
  "display_name": "Ankit",
  "phone": "+491700000000",
  "telegram_chat_id": "123456789",
  "notification_preferences": {
    "email_enabled": true,
    "telegram_enabled": true,
    "whatsapp_enabled": false,
    "sms_enabled": false,
    "in_app_enabled": true
  }
}
```

`theme_preference` must be `dark`, `light`, or `system`. Returns `{ "status": "updated" }`.

### Test Notification Channel

```
POST /settings/test/email
POST /settings/test/telegram
```

Sends a test notification and returns success/failure. (There are no test endpoints for WhatsApp or SMS.)

### Test LLM Provider

```
POST /settings/test/llm
```

**Request Body:**
```json
{
  "provider": "ollama"
}
```

### Service Health Dashboard

```
GET /settings/health
```

Returns a flat status string per dependent service. `broker` is `configured` / `not_configured`; `ollama` reports `disabled` or `using_<provider>` when a non-Ollama LLM provider is active; `overall` is `healthy` only when the database is healthy.

**Response** `200 OK`:
```json
{
  "database": "healthy",
  "redis": "unavailable",
  "ollama": "healthy",
  "broker": "not_configured",
  "overall": "healthy"
}
```

---

## WebSocket Channels

There are two WebSocket channels: `/ws/prices` and `/ws/alerts`. Both authenticate via a `token` query parameter carrying the JWT access token; an invalid token closes the connection with code `4001`.

### Price Stream

```
WS /ws/prices?token=<access_token>
```

**Subscribe** (client sends):
```json
{
  "action": "subscribe",
  "symbols": ["RELIANCE", "TCS", "SAP"]
}
```

Server confirms with `{"type": "subscribed", "symbols": [...]}`.

**Price Update** (server sends):
```json
{
  "type": "price_update",
  "symbol": "RELIANCE",
  "data": {
    "price": 2681.00,
    "change": 16.00,
    "change_percent": 0.60
  }
}
```

**Unsubscribe** (client sends):
```json
{
  "action": "unsubscribe",
  "symbols": ["SAP"]
}
```

Server confirms with `{"type": "unsubscribed", "symbols": [...]}`.

### Alert Stream

```
WS /ws/alerts?token=<access_token>
```

**Alert Triggered** (server sends):
```json
{
  "type": "alert",
  "alert_id": 1,
  "alert_type": "PRICE_RANGE",
  "stock_symbol": "HDFCBANK",
  "message": "HDFC Bank has dropped below base level (1400.00). Current price: 1395.00",
  "channels": ["in_app"],
  "triggered_at": "2025-01-20T14:31:00Z"
}
```

**Acknowledge** (client sends):
```json
{"action": "ack", "alert_id": 1}
```

Server confirms with `{"type": "ack_confirmed", "alert_id": 1}`.

---

## Dividends

### List Dividends

```
GET /dividends
```

Returns all dividend records for the current user's holdings.

### Get Dividend Summary

```
GET /dividends/summary
```

Returns total dividends received, dividend yield, portfolio-wide yield-on-cost, total reinvested, count, and monthly calendar.

### Forecast Dividend Income

```
GET /dividends/forecast
```

Best-effort forecast of the next 12 months of dividend income (driven by yfinance dividend history and rate data). Returns a month-by-month projection, the forward yield, the total forward 12-month income, and a per-holding breakdown with yield and yield-on-cost.

### Add Dividend

```
POST /dividends
```

**Request Body:**
```json
{
  "holding_id": 1,
  "ex_date": "2025-01-15",
  "payment_date": "2025-02-01",
  "amount_per_share": 5.50,
  "total_amount": 550.00,
  "is_reinvested": false
}
```

When `is_reinvested` is `true`, `reinvest_price` (> 0) and `reinvest_shares` (> 0) are required.

### Delete Dividend

```
DELETE /dividends/{dividend_id}
```

---

## Net Worth

### Get Net Worth

```
GET /net-worth
```

Returns total net worth with breakdown by asset type (STOCK, CRYPTO, GOLD, FIXED_DEPOSIT, BOND, REAL_ESTATE). Stock values are aggregated from portfolio holdings. Crypto and gold fetch live prices via yfinance.

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `display_currency` | string | *(stored preference)* | Optional currency override (e.g. `INR`/`EUR`/`USD`). When set, totals are converted into this currency for this response only; the stored `preferred_currency` is left unchanged. |

### Emergency Fund

```
GET /net-worth/emergency-fund
```

Liquid-asset runway indicator — how many months of expenses your liquid assets cover. Liquidity classes: **liquid** (`FIXED_DEPOSIT`, `CRYPTO`, `GOLD`), **semi-liquid** (`STOCK`, reported separately via the `*_incl_stocks` fields), **illiquid** (`BOND`, `REAL_ESTATE`, excluded). `status` is derived from core liquid coverage (excluding stocks): `critical` < 3 months, `adequate` 3–6 months, `strong` > 6 months. When `monthly_expenses` ≤ 0, `status` is `"unknown"` and the `months_covered` fields are `null` (so the UI can prompt for input). Values are in the base currency (or `display_currency` when supplied).

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `monthly_expenses` | float | *(required)* | Estimated monthly living expenses in the base currency |
| `display_currency` | string | *(stored preference)* | Optional currency override; converts figures for this response only, same semantics as `GET /net-worth` |

**Response** `200 OK`:
```json
{
  "liquid_value": 480000.00,
  "liquid_incl_stocks": 1730000.00,
  "monthly_expenses": 80000.00,
  "months_covered": 6.0,
  "months_covered_incl_stocks": 21.63,
  "status": "adequate",
  "currency": "INR",
  "breakdown": [
    {"asset_type": "FIXED_DEPOSIT", "value": 300000.00, "liquid": true},
    {"asset_type": "STOCK", "value": 1250000.00, "liquid": false}
  ]
}
```

### Add Asset

```
POST /net-worth/assets
```

**Request Body:**
```json
{
  "asset_type": "CRYPTO",
  "name": "Bitcoin",
  "symbol": "BTC-USD",
  "quantity": 0.5,
  "purchase_price": 30000.00,
  "current_value": 35000.00,
  "currency": "USD"
}
```

### Delete Asset

```
DELETE /net-worth/assets/{asset_id}
```

(There is no update endpoint — delete and re-add an asset to change it.)

---

## ESG Scoring

### Get Portfolio ESG

```
GET /esg/{portfolio_id}
```

Returns ESG (Environmental, Social, Governance) scores for all holdings using yfinance sustainability data, with a portfolio-level weighted average.

### Get Stock ESG

```
GET /esg/stock/{symbol}
```

Returns individual stock ESG scores.

---

## What-If Simulator

### Run Simulation

```
POST /whatif/simulate
```

**Request Body:**
```json
{
  "symbol": "RELIANCE.NS",
  "investment_amount": 100000,
  "start_date": "2024-01-01",
  "end_date": "2025-01-01"
}
```

Returns simulated returns with benchmark comparison.

---

## Earnings Calendar

### Get Portfolio Earnings

```
GET /earnings/{portfolio_id}
```

Returns upcoming earnings dates for all stocks in the portfolio.

### Get Stock Earnings

```
GET /earnings/stock/{symbol}
```

Returns earnings dates for a specific stock.

---

## F&O Positions

### List Positions

```
GET /fno/positions/{portfolio_id}
```

Returns all futures & options positions for the portfolio.

### Get P&L Summary

```
GET /fno/pnl/{portfolio_id}
```

Returns total realized/unrealized P&L and open/closed position counts.

### Add Position

```
POST /fno/positions
```

**Request Body:**
```json
{
  "portfolio_id": 1,
  "symbol": "NIFTY",
  "exchange": "NSE",
  "instrument_type": "CE",
  "strike_price": 22000.0,
  "expiry_date": "2025-02-27",
  "lot_size": 50,
  "quantity": 1,
  "entry_price": 150.00,
  "side": "BUY"
}
```

`side` is `BUY` or `SELL`. For `instrument_type: "FUT"`, `strike_price` is optional (null).

### Update Position

```
PUT /fno/positions/{position_id}
```

### Close Position

```
DELETE /fno/positions/{position_id}
```

---

## Analytics

### Portfolio Drift

```
GET /analytics/drift/{portfolio_id}
```

Detects allocation drift from target weights stored in holdings' `custom_fields`.

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `threshold` | float | 5.0 | Drift threshold in percentage points |

### Set Target Allocation

```
PUT /analytics/drift/{holding_id}
```

Sets the target allocation percentage for a specific holding (stored in the holding's `custom_fields` under `target_allocation_pct`).

**Body:** `{ "target_allocation_pct": 25.0 }` (0–100)

### Concentration & Diversification

```
GET /analytics/concentration/{portfolio_id}
```

Analyzes portfolio concentration and diversification. Returns per-holding weights (flagged when over `single_name_threshold`), sector / market-cap / exchange breakdowns, an overall 0–100 diversification score with an A–F grade (anchored on the Herfindahl-Hirschman Index), and human-readable warnings for each flagged concentration.

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `single_name_threshold` | float | 15.0 | Flag any single holding above this weight % (0–100) |
| `sector_threshold` | float | 40.0 | Flag any sector above this weight % (0–100) |

### Sector Rotation

```
GET /analytics/sector-rotation/{portfolio_id}
```

Returns month-over-month sector weight changes.

### Calendar

```
GET /analytics/calendar/{portfolio_id}
```

Aggregated SIP, dividend, and earnings calendar.

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `month` | int | *(current)* | Month (1–12) |
| `year` | int | *(current)* | Year |

### Recurring Transactions

```
GET /analytics/recurring/{portfolio_id}
```

Detects recurring SIP-like transactions by amount/interval pattern matching.

### 52-Week High/Low

```
GET /analytics/52week/{portfolio_id}
```

Returns proximity to 52-week high and low for each holding via yfinance.

### Data Freshness

```
GET /analytics/freshness/{portfolio_id}
```

Returns staleness status for each holding with exchange-aware market hours.

### Google Sheets Export

```
GET /analytics/export/sheets/{portfolio_id}
```

Returns CSV content with 3 sections (summary, holdings, transactions) for Google Sheets import.

### Correlation Matrix

```
GET /analytics/correlation/{portfolio_id}
```

Computes pairwise correlation matrix for all holdings using daily close returns. Requires numpy.

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `days` | int | 90 | Lookback period (30–365) |

**Response:**
```json
{
  "symbols": ["RELIANCE", "TCS", "INFY"],
  "matrix": [[1.0, 0.65, 0.72], [0.65, 1.0, 0.88], [0.72, 0.88, 1.0]]
}
```

### Monthly Returns

```
GET /analytics/monthly-returns/{portfolio_id}
```

Computes weighted monthly portfolio return percentages for the last 12 months.

**Response:**
```json
{
  "returns": [
    {"month": "Jan", "return_pct": 2.3},
    {"month": "Feb", "return_pct": -1.5}
  ]
}
```

### Drawdown

```
GET /analytics/drawdown/{portfolio_id}
```

Computes daily drawdown from peak for the portfolio over the specified period.

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `days` | int | 365 | Lookback period (30–730) |

**Response:**
```json
{
  "drawdown": [
    {"date": "2025-01-15", "drawdown": -3.42},
    {"date": "2025-01-16", "drawdown": -2.18}
  ]
}
```

### Cash Flow

```
GET /analytics/cash-flow/{portfolio_id}
```

Monthly money-in / money-out timeline plus a running cumulative, aggregated per calendar month (`YYYY-MM`) across a contiguous month range. Money out (negative): `invested_out` = BUY transactions, `-(quantity × price + brokerage)`. Money in (positive): `realized_in` = SELL transactions net of brokerage, and `dividends_in` = dividend cash (booked on payment date, falling back to ex-date). `net` is the sum of the three per month. All amounts are in the portfolio's currency. Returns `404` if the portfolio does not belong to the user.

**Response** `200 OK`:
```json
{
  "portfolio_id": 1,
  "currency": "INR",
  "monthly": [
    {
      "month": "2024-11",
      "invested_out": -122500.00,
      "realized_in": 0.00,
      "dividends_in": 550.00,
      "net": -121950.00
    }
  ],
  "totals": {
    "total_invested": -122500.00,
    "total_realized": 0.00,
    "total_dividends": 550.00,
    "net_cash_flow": -121950.00
  },
  "cumulative": [
    {"month": "2024-11", "cumulative_net": -121950.00}
  ]
}
```

### Economic / Macro Calendar

```
GET /analytics/economic-calendar/{portfolio_id}
```

Unified upcoming-catalysts feed for a portfolio over a forward ~3-month window, merging: upcoming **earnings** dates for held symbols (yfinance), upcoming **ex-dividend** dates (yfinance, best-effort), and a curated static set of key **macro** events (RBI / ECB rate decisions, US / India CPI prints, US jobs report). Each event is tagged with a `type` (`EARNINGS` / `EX_DIV` / `MACRO`) and a `region`; macro events also carry an `importance`. Events are sorted by date and yfinance failures degrade gracefully.

---

## IPO Tracker

### List IPOs

```
GET /ipo
```

Returns IPO listings from public market data sources. Currently supports Indian markets (NSE/BSE). Returns an empty list if upstream data is unavailable.

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `status` | string | *(all)* | Filter by `upcoming`, `open`, or `listed` |
| `exchange` | string | `NSE` | Exchange: `NSE`, `BSE`, `XETRA` |

**Response:**
```json
{
  "ipos": [
    {
      "name": "Company Name",
      "symbol": "SYMBOL",
      "exchange": "NSE",
      "price_range": "₹520-₹548",
      "lot_size": 27,
      "open_date": "2026-02-10",
      "close_date": "2026-02-12",
      "listing_date": null,
      "listing_price": null,
      "issue_price": null,
      "current_price": null,
      "status": "upcoming",
      "subscription_times": null
    }
  ],
  "count": 1
}
```

---

## Benchmark & Comparison

### Benchmark Comparison

```
GET /portfolios/{portfolio_id}/benchmark
```

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `benchmark` | string | `NIFTY50` | `NIFTY50`, `SENSEX`, `DAX`, `SP500`, `NASDAQ` |
| `days` | int | 90 | Comparison period (7–365) |

### Stock Comparison

```
GET /comparison/compare
```

**Query Parameters:**
| Parameter | Type | Required | Description |
|---|---|---|---|
| `symbols` | string | Yes | Comma-separated (up to 3): `RELIANCE,TCS,INFY` |
| `exchanges` | string | No | Comma-separated exchanges (default `NSE`) |
| `days` | int | No | Comparison period (default 90, 7–365) |

### Peer Comparison

```
GET /comparison/peers/{symbol}
```

Compares a single stock against a curated set of sector peers. Returns the target stock's `sector`, its own metrics (`target`), and a list of peer metrics, plus a `coverage_note` describing the peer set. Any metric that could not be fetched comes back `null`.

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `exchange` | string | `NSE` | Exchange for the symbol |

**Response** `200 OK`:
```json
{
  "symbol": "HDFCBANK",
  "sector": "Banking",
  "target": {
    "symbol": "HDFCBANK",
    "name": "HDFC Bank Ltd",
    "current_price": 1580.00,
    "day_change_pct": -0.75,
    "pe_ratio": 18.4,
    "market_cap": 12000000000000,
    "dividend_yield": 1.2,
    "week_52_high": 1750.00,
    "week_52_low": 1360.00,
    "week_52_position": 56.3,
    "beta": 0.95
  },
  "peers": [
    {
      "symbol": "ICICIBANK",
      "name": "ICICI Bank Ltd",
      "current_price": 1080.00,
      "day_change_pct": 0.42,
      "pe_ratio": 17.1,
      "market_cap": 7600000000000,
      "dividend_yield": 0.8,
      "week_52_high": 1150.00,
      "week_52_low": 900.00,
      "week_52_position": 72.0,
      "beta": 0.88
    }
  ],
  "coverage_note": "..."
}
```

`target` is `null` when the target symbol's metrics cannot be fetched. `week_52_position` is the price's 0–100% position within its 52-week range.

### XIRR Calculation

```
GET /portfolios/{portfolio_id}/xirr
```

Returns the XIRR (Extended Internal Rate of Return) for the whole portfolio based on all buy/sell transactions plus current value.

**Response** `200 OK`:
```json
{
  "portfolio_id": 1,
  "xirr": 14.32,
  "xirr_decimal": 0.1432,
  "total_current_value": 1250000.00,
  "num_cash_flows": 12,
  "used_stale_prices": false,
  "status": "calculated"
}
```

`used_stale_prices` is `true` when a holding had no fetched current price and its average price was used as the terminal value.

---

## Stop-Loss Tracker

### Get Stop-Losses

```
GET /comparison/stop-loss/{portfolio_id}
```

Returns stop-loss levels for all holdings in the portfolio (stored in `custom_fields` JSON), plus a `triggered_count`.

### Set Stop-Loss

```
PUT /comparison/stop-loss/{holding_id}?price=2200.00
```

The stop-loss price is passed as the `price` query parameter (must be > 0).

### Remove Stop-Loss

```
DELETE /comparison/stop-loss/{holding_id}
```

---

## Corporate Actions

Detect and apply stock splits and bonus issues. All routes live under the `/corporate-actions` prefix and are auth-scoped (ownership is verified via holding → portfolio → user).

### Detect Corporate Actions

```
POST /corporate-actions/detect
```

Scans all of the user's holdings for new splits/bonuses via yfinance, records any newly found action with status `DETECTED`, and returns the full pending (`DETECTED`) list. Best-effort — unreachable tickers are skipped silently.

**Response** `200 OK`:
```json
{
  "count": 1,
  "actions": [
    {
      "id": 1,
      "holding_id": 3,
      "stock_symbol": "IRCTC",
      "action_type": "SPLIT",
      "ratio": "5:1",
      "ex_date": "2024-10-28",
      "status": "DETECTED"
    }
  ]
}
```

### List Corporate Actions

```
GET /corporate-actions/
```

Lists the user's corporate actions, optionally filtered by status.

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `status` | string | *(all)* | Filter by `DETECTED`, `APPLIED`, or `DISMISSED` |

Returns `{ "count": n, "actions": [...] }`.

### Apply Corporate Action

```
POST /corporate-actions/{action_id}/apply
```

Applies a detected split/bonus, adjusting the holding's quantity and average price. Idempotent — applying an already-applied action does not double-adjust. Returns `404` if the action is not found, `400` on an invalid state.

### Dismiss Corporate Action

```
POST /corporate-actions/{action_id}/dismiss
```

Dismisses a detected corporate action without adjusting the holding.

---

## Additional Endpoints

Endpoints not covered in detail above, one line each:

### Auth
- `GET /auth/me` — get the current authenticated user (includes `totp_enabled`, `phone`, `telegram_chat_id`)
- `POST /auth/2fa/disable` — disable 2FA after verifying a current TOTP code (`{"code": "123456"}`); also clears any stored backup codes
- `GET /auth/2fa/backup-codes/status` — count of unused 2FA backup codes remaining (see [Authentication](#authentication))
- `POST /auth/2fa/backup-codes/regenerate` — regenerate 2FA backup codes; requires a current TOTP code (see [Authentication](#authentication))

### Portfolios & Holdings
- `GET /portfolios/{portfolio_id}` — get a single portfolio
- `GET /holdings/` — list holdings (`portfolio_id`, `skip`, `limit` query params)

### Transactions
- `GET /transactions/{transaction_id}` — get a single transaction
- `PATCH /transactions/{transaction_id}` — update a transaction (recalculates the holding)
- `POST /transactions/backfill?holding_id={id}` — seed a BUY transaction for a pre-existing holding with no transactions (idempotent)

### Tax
- `GET /tax/` — list tax records (`financial_year`, `jurisdiction` filters)
- `POST /tax/compute/{transaction_id}` — compute per-lot FIFO tax for a SELL transaction and create tax records; returns a **list** (a single SELL can straddle the STCG/LTCG boundary and yield multiple records). Idempotent recompute.
- `DELETE /tax/{record_id}` — delete a tax record

### Goals
- `GET /goals/{goal_id}` — get a single goal
- `POST /goals/{goal_id}/sync` — sync goal progress from its linked portfolio

### Mutual Funds
- `PUT /mutual-funds/{fund_id}` — update a mutual fund holding
- `DELETE /mutual-funds/{fund_id}` — delete a mutual fund holding
- `GET /mutual-funds/summary` — aggregate summary of all mutual fund holdings (total invested/current value, gain %, and real portfolio `xirr`)
- `GET /mutual-funds/overlap` — portfolio overlap X-ray across mutual fund holdings (see [Mutual Funds](#mutual-funds))
- `GET /mutual-funds/expense-analysis` — value-weighted expense ratio and fee-drag projection (see [Mutual Funds](#mutual-funds))
- `POST /mutual-funds/refresh` — refresh NAVs from mfapi.in
- `GET /mutual-funds/search?q=` — search schemes by name on mfapi.in

### Forex
- `GET /forex/rate?from_currency=&to_currency=` — current exchange rate
- `POST /forex/convert` — convert an amount between currencies
- `GET /forex/history` — historical exchange rates

### Backtesting & Optimization
- `POST /backtest/` — run a backtest (RSI, SMA crossover, or Bollinger strategy)
- `GET /backtest/strategies` — list available strategies and their parameters
- `POST /backtest/optimize/{portfolio_id}` — run mean-variance portfolio optimization
- `GET /backtest/optimize/{portfolio_id}/suggestions` — rebalancing suggestions from the optimizer

### Indicators & Risk
- `GET /indicators/risk/{portfolio_id}/holdings` — per-holding risk metrics (beta, correlation, volatility, weight)

### AI Sessions & ML
- `GET /ai/sessions` — list chat sessions
- `GET /ai/sessions/{session_id}` — get a session with all messages
- `DELETE /ai/sessions/{session_id}` — delete a chat session
- `GET /ai/status` — AI provider availability (Ollama, OpenAI, Anthropic, Google)
- `GET /ai/anomalies/{symbol}` — Isolation Forest price/volume anomaly detection
- `GET /ai/insights` — AI-generated portfolio insights

### Import / Export
- `POST /import-export/excel?portfolio_id=` — import holdings/transactions from an `.xlsx` file
- `POST /import-export/csv?portfolio_id=` — import holdings/transactions from CSV
- `GET /import-export/export/csv/{portfolio_id}` — export holdings as CSV
- `GET /import-export/export/csv/{portfolio_id}/transactions` — export transactions as CSV
- `POST /import-export/csv/dividends?portfolio_id=` — import dividends from CSV
- `POST /import-export/csv/mutual-funds?portfolio_id=` — import mutual funds from CSV
- `POST /import-export/csv/tax-records` — import tax records from CSV (user-level)
- `POST /import-export/import/ofx?portfolio_id=` — import an `.ofx`/`.qfx` broker or bank statement (investment BUY/SELL, bank fallback)
- `POST /import-export/import/qif?portfolio_id=` — import a `.qif` (Quicken) investment or bank file
- `POST /import-export/import/cas?portfolio_id=&password=` — import mutual-fund holdings from a CAMS/KFintech CAS PDF (needs the `cas` extra; `501` if `casparser` missing)
- `GET /import-export/export/template` — blank Excel import template
- `GET /import-export/export/template/csv` — blank CSV import template
- `GET /import-export/export/template/dividends` — dividend CSV template
- `GET /import-export/export/template/mutual-funds` — mutual fund CSV template
- `GET /import-export/export/template/tax-records` — tax record CSV template
- `GET /import-export/export/excel/{portfolio_id}` — export holdings as a single-sheet `.xlsx`
- `GET /import-export/export/xlsx/{portfolio_id}` — export a multi-sheet `.xlsx` workbook (Holdings, Transactions, Dividends, Summary)
- `GET /import-export/export/json/{portfolio_id}` — full portfolio backup as JSON
- `POST /import-export/json` — restore a portfolio from a JSON backup
- `GET /import-export/export/pdf/{portfolio_id}` — PDF report (requires xhtml2pdf, else `501`)
- `GET /import-export/export/report/{portfolio_id}` — styled HTML report
- `GET /import-export/export/bundle/{portfolio_id}` — "Export Everything" `.zip` (CSVs, JSON, HTML report, XLSX workbook, PDF report, README)
- `GET /import-export/export/backup/sqlite` — download the raw SQLite database (instance owner only; `501` on PostgreSQL)
- `GET /import-export/aa/providers` — list Account Aggregator providers (stubs)
- `POST /import-export/aa/consent` — initiate AA consent (`501` — coming soon)
- `GET /import-export/aa/consent/{consent_id}/status` — AA consent status (`501` — coming soon)

### Misc
- `GET /health` — public health check at the server root (not under `/api/v1`); returns `{"status", "app", "version"}`

---

## Common Response Formats

### Pagination

There is no pagination envelope — list endpoints return bare JSON arrays. Endpoints that support paging (holdings, transactions, alerts) take `skip` and `limit` query parameters:

```
GET /transactions/?skip=0&limit=200
```

```json
[
  { "id": 1, ... },
  { "id": 2, ... }
]
```

### Timestamps

All timestamps are in ISO 8601 format with UTC timezone: `2025-01-20T14:30:00Z`

---

## Error Handling

All errors follow a consistent format:

```json
{
  "detail": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid input data",
    "errors": [
      {"field": "email", "message": "Invalid email format"}
    ]
  }
}
```

### HTTP Status Codes

| Code | Meaning |
|---|---|
| `200` | Success |
| `201` | Created |
| `204` | No Content (successful delete) |
| `400` | Bad Request (validation error) |
| `401` | Unauthorized (invalid/expired token) |
| `403` | Forbidden (insufficient permissions) |
| `404` | Not Found |
| `409` | Conflict (duplicate resource) |
| `422` | Unprocessable Entity (Pydantic validation failure) |
| `429` | Too Many Requests (rate limit exceeded) |
| `500` | Internal Server Error |
| `503` | Service Unavailable (external service down) |

### Rate Limits

Rate limiting applies only to the auth endpoints:

| Endpoint | Limit |
|---|---|
| Register | 5 requests/minute |
| Login | 10 requests/minute |
| Token Refresh | 20 requests/minute |
