# API Reference

> FinanceTracker REST API & WebSocket Documentation

**Base URL**: `http://localhost:8000/api/v1`
**Interactive Docs**: `http://localhost:8000/docs` (Swagger) | `http://localhost:8000/redoc` (ReDoc)

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
27. [Common Response Formats](#common-response-formats)
28. [Error Handling](#error-handling)

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
  "id": "uuid",
  "email": "user@example.com",
  "display_name": "Ankit",
  "preferred_currency": "INR",
  "created_at": "2025-01-15T10:30:00Z"
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

The `totp_code` field is only required if the user has 2FA enabled.

**Response** `200 OK`:
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 900
}
```

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
  "token_type": "bearer",
  "expires_in": 900
}
```

### Setup 2FA

Enable TOTP-based two-factor authentication.

```
POST /auth/2fa/setup
```

**Response** `200 OK`:
```json
{
  "secret": "JBSWY3DPEHPK3PXP",
  "provisioning_uri": "otpauth://totp/FinanceTracker:user@example.com?secret=JBSWY3DPEHPK3PXP&issuer=FinanceTracker",
  "qr_code_base64": "data:image/png;base64,..."
}
```

### Verify 2FA

Confirm 2FA setup by verifying a TOTP code.

```
POST /auth/2fa/verify
```

**Request Body:**
```json
{
  "totp_code": "123456"
}
```

**Response** `200 OK`:
```json
{
  "two_factor_enabled": true,
  "backup_codes": ["abc123", "def456", "ghi789", "jkl012", "mno345"]
}
```

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
    "id": "uuid",
    "name": "Indian Stocks",
    "description": "NSE/BSE equity portfolio",
    "currency": "INR",
    "is_default": true,
    "total_value": 1250000.00,
    "total_pnl": 87500.00,
    "total_pnl_percent": 7.53,
    "holdings_count": 15,
    "created_at": "2025-01-15T10:30:00Z"
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
| `sort_by` | string | `stock_name` | Column to sort by |
| `sort_order` | string | `asc` | `asc` or `desc` |
| `filter_action` | string | `all` | `all`, `Y`, `N`, `DARK_RED`, `DARK_GREEN` |

**Response** `200 OK`:
```json
{
  "portfolio_id": "uuid",
  "portfolio_name": "Indian Stocks",
  "currency": "INR",
  "summary": {
    "total_value": 1250000.00,
    "total_invested": 1162500.00,
    "total_pnl": 87500.00,
    "total_pnl_percent": 7.53,
    "day_pnl": 3200.00,
    "day_pnl_percent": 0.26,
    "top_gainer": {"symbol": "TCS.NS", "pnl_percent": 12.5},
    "top_loser": {"symbol": "INFY.NS", "pnl_percent": -3.2}
  },
  "holdings": [
    {
      "id": "uuid",
      "stock_symbol": "RELIANCE.NS",
      "stock_name": "Reliance Industries Ltd",
      "exchange": "NSE",
      "cumulative_quantity": 50,
      "average_price": 2450.00,
      "current_price": 2680.50,
      "current_rsi": 62.3,
      "pnl_amount": 11525.00,
      "pnl_percent": 9.41,
      "day_change": 15.50,
      "day_change_percent": 0.58,
      "action_needed": "N",
      "action_color": null,
      "lower_mid_range_1": 2400.00,
      "lower_mid_range_2": 2200.00,
      "upper_mid_range_1": 2800.00,
      "upper_mid_range_2": 2950.00,
      "base_level": 2000.00,
      "top_level": 3100.00,
      "sector": "Energy",
      "custom_fields": {"target_pe": 25},
      "last_updated": "2025-01-20T14:30:00Z"
    },
    {
      "id": "uuid",
      "stock_symbol": "HDFCBANK.NS",
      "stock_name": "HDFC Bank Ltd",
      "exchange": "NSE",
      "cumulative_quantity": 30,
      "average_price": 1650.00,
      "current_price": 1580.00,
      "current_rsi": 28.5,
      "pnl_amount": -2100.00,
      "pnl_percent": -4.24,
      "day_change": -12.00,
      "day_change_percent": -0.75,
      "action_needed": "Y",
      "action_color": "LIGHT_RED",
      "lower_mid_range_1": 1600.00,
      "lower_mid_range_2": 1500.00,
      "upper_mid_range_1": 1800.00,
      "upper_mid_range_2": 1900.00,
      "base_level": 1400.00,
      "top_level": 2000.00,
      "sector": "Banking",
      "custom_fields": {},
      "last_updated": "2025-01-20T14:30:00Z"
    }
  ]
}
```

**Action Color Values:**
| Value | Meaning | Visual |
|---|---|---|
| `null` | Price not in any alert range | No highlight |
| `LIGHT_RED` | Price in lower mid range (LMR2 to LMR1) | Light red background pulse |
| `LIGHT_GREEN` | Price in upper mid range (UMR1 to UMR2) | Light green background pulse |
| `DARK_RED` | Price at/below base level | Dark red with warning icon |
| `DARK_GREEN` | Price at/above top level | Dark green with celebration icon |

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
  "portfolio_id": "uuid",
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

### List Transactions for a Holding

```
GET /holdings/{holding_id}/transactions
```

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `type` | string | `all` | `all`, `BUY`, `SELL` |
| `start_date` | date | - | Filter from this date |
| `end_date` | date | - | Filter until this date |
| `page` | int | 1 | Page number |
| `per_page` | int | 50 | Items per page |

### Create Transaction

```
POST /holdings/{holding_id}/transactions
```

**Request Body:**
```json
{
  "type": "BUY",
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
| `days` | int | 30 | Number of days of history |
| `interval` | string | `1d` | `1d`, `1wk`, `1mo`, `1h`, `5m` |

**Response** `200 OK`:
```json
{
  "symbol": "RELIANCE.NS",
  "interval": "1d",
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

TradingView Lightweight Charts compatible format.

```
GET /charts/price/{symbol}?days=30
```

**Response** `200 OK`:
```json
{
  "symbol": "RELIANCE.NS",
  "chart_data": [
    {
      "time": "2024-12-21",
      "open": 2610.00,
      "high": 2635.00,
      "low": 2600.00,
      "close": 2625.00
    }
  ],
  "volume_data": [
    {
      "time": "2024-12-21",
      "value": 7823400,
      "color": "#26a69a"
    }
  ],
  "range_lines": {
    "base_level": 2000.00,
    "lower_mid_range_2": 2200.00,
    "lower_mid_range_1": 2400.00,
    "upper_mid_range_1": 2800.00,
    "upper_mid_range_2": 2950.00,
    "top_level": 3100.00
  }
}
```

### Get RSI Chart Data

```
GET /charts/rsi/{symbol}?days=30
```

**Response** `200 OK`:
```json
{
  "symbol": "RELIANCE.NS",
  "rsi_data": [
    {"time": "2024-12-21", "value": 55.2},
    {"time": "2024-12-22", "value": 57.8}
  ],
  "overbought_level": 70,
  "oversold_level": 30
}
```

### Get Technical Indicators

```
GET /charts/indicators/{symbol}
```

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `days` | int | 90 | Data window |
| `indicators` | string | `all` | Comma-separated: `rsi,macd,bbands,sma,ema,fibonacci` |

**Response** `200 OK`:
```json
{
  "symbol": "RELIANCE.NS",
  "indicators": {
    "rsi_14": [{"time": "2025-01-20", "value": 62.3}],
    "macd": [{"time": "2025-01-20", "macd": 15.2, "signal": 12.8, "histogram": 2.4}],
    "bollinger_bands": [{"time": "2025-01-20", "upper": 2750.0, "middle": 2650.0, "lower": 2550.0}],
    "sma_20": [{"time": "2025-01-20", "value": 2648.0}],
    "ema_50": [{"time": "2025-01-20", "value": 2620.0}],
    "support_levels": [2600.0, 2450.0, 2300.0],
    "resistance_levels": [2700.0, 2850.0, 3000.0],
    "fibonacci": {"0.0": 2220.0, "0.236": 2410.0, "0.382": 2527.0, "0.5": 2622.0, "0.618": 2717.0, "1.0": 3024.0}
  }
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

### Get Portfolio Allocation

```
GET /charts/portfolio/allocation?portfolio_id={id}
```

Returns data for donut/treemap chart.

### Get Portfolio Performance

```
GET /charts/portfolio/performance?portfolio_id={id}&days=90
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
| `is_active` | bool | `true` | Filter active/inactive alerts |
| `alert_type` | string | `all` | `all`, `PRICE_RANGE`, `RSI`, `CUSTOM` |

### Create Alert

```
POST /alerts
```

**Request Body:**
```json
{
  "holding_id": "uuid",
  "alert_type": "PRICE_RANGE",
  "condition": {
    "price_above": 3000.00,
    "price_below": 2200.00
  },
  "channels": ["email", "telegram", "push"],
  "is_active": true
}
```

### Update Alert Channels

```
PUT /alerts/{alert_id}/channels
```

**Request Body:**
```json
{
  "channels": ["email", "whatsapp", "telegram", "sms", "push"]
}
```

### Delete Alert

```
DELETE /alerts/{alert_id}
```

### Get Notification History

```
GET /notifications/history
```

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `channel` | string | `all` | `all`, `email`, `whatsapp`, `telegram`, `sms`, `push`, `in_app` |
| `status` | string | `all` | `all`, `SENT`, `FAILED`, `QUEUED` |
| `page` | int | 1 | Page number |
| `per_page` | int | 50 | Items per page |

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
  "stock_symbol": "BAJFINANCE.NS",
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
GET /tax/harvesting-suggestions
```

**Response** `200 OK`:
```json
{
  "suggestions": [
    {
      "holding": "INFY.NS",
      "unrealized_loss": -15000.00,
      "gain_type": "STCG",
      "potential_tax_saving": 3000.00,
      "recommendation": "Consider selling before March 31 to offset STCG gains"
    }
  ]
}
```

### Export Tax Report

```
GET /export/tax-report/{financial_year}
```

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `jurisdiction` | string | `IN` | `IN` or `DE` |
| `format` | string | `pdf` | `pdf` or `xlsx` |

Returns a downloadable file.

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
  "linked_portfolio_id": "uuid"
}
```

**Response** includes calculated `monthly_sip_needed`.

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
  "portfolio_id": "uuid",
  "scheme_code": "119551",
  "scheme_name": "Axis Bluechip Fund - Direct Growth",
  "folio_number": "1234567890",
  "units": 250.5,
  "invested_amount": 100000.00
}
```

### Import CAS Statement

```
POST /mutual-funds/import-cas
```

**Request Body**: Multipart form with PDF file.

---

## Broker Connections

### List Connected Brokers

```
GET /brokers
```

### Connect Broker

```
POST /brokers/connect
```

**Request Body:**
```json
{
  "broker_name": "zerodha",
  "api_key": "your_api_key",
  "api_secret": "your_api_secret"
}
```

API keys are encrypted with Fernet before storage.

### Start OAuth Flow

```
GET /brokers/{broker_name}/auth-url
```

Returns the OAuth redirect URL for the broker.

### Complete OAuth Callback

```
POST /brokers/{broker_name}/callback
```

**Request Body:**
```json
{
  "request_token": "token_from_redirect"
}
```

### Sync Holdings from Broker

```
POST /brokers/{broker_name}/sync
```

Fetches latest holdings, positions, and transactions from the broker.

### Disconnect Broker

```
DELETE /brokers/{broker_name}
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
  "session_id": "uuid-or-null-for-new"
}
```

**Response** `200 OK`:
```json
{
  "session_id": "uuid",
  "response": "Based on your portfolio, 3 stocks are underperforming Nifty 50 this month:\n\n1. **INFY.NS** (-3.2% vs Nifty +1.8%)\n2. **HDFCBANK.NS** (-0.75% vs Nifty +1.8%)\n3. **WIPRO.NS** (-1.5% vs Nifty +1.8%)\n\nInfosys has the widest gap. Its RSI is at 35, approaching oversold territory.",
  "provider": "ollama",
  "model": "llama3.2",
  "tools_used": ["portfolio_data", "market_data"]
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
GET /ml/prediction/{symbol}
```

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `horizon` | int | 5 | Prediction horizon in days (1, 5, 10) |

**Response** `200 OK`:
```json
{
  "symbol": "RELIANCE.NS",
  "current_price": 2680.50,
  "predictions": [
    {"day": 1, "predicted_price": 2695.00, "confidence": 0.72},
    {"day": 5, "predicted_price": 2720.00, "confidence": 0.58}
  ],
  "model": "lstm_v1",
  "last_trained": "2025-01-20T02:00:00Z"
}
```

### Get News Sentiment

```
GET /ml/sentiment/{symbol}
```

**Response** `200 OK`:
```json
{
  "symbol": "RELIANCE.NS",
  "overall_sentiment": "bullish",
  "sentiment_score": 0.65,
  "articles_analyzed": 12,
  "recent_articles": [
    {
      "title": "Reliance Jio Adds 5M Subscribers in December",
      "source": "Economic Times",
      "sentiment": "positive",
      "score": 0.82,
      "published_at": "2025-01-19T08:00:00Z"
    }
  ]
}
```

### Get Portfolio Risk Metrics

```
GET /ml/risk
```

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `portfolio_id` | uuid | default | Portfolio to analyze |

**Response** `200 OK`:
```json
{
  "portfolio_id": "uuid",
  "metrics": {
    "sharpe_ratio": 1.82,
    "sortino_ratio": 2.15,
    "max_drawdown": -12.5,
    "max_drawdown_period": "2024-10-01 to 2024-10-15",
    "value_at_risk_95": -45000.00,
    "beta": 0.92,
    "annualized_return": 14.3,
    "annualized_volatility": 18.7
  },
  "concentration_warnings": [
    "RELIANCE.NS represents 22% of portfolio (threshold: 20%)"
  ]
}
```

---

## Import / Export

### Import from Excel

```
POST /import/excel
```

**Request**: Multipart form data with `.xlsx` file.

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

**Response** `200 OK` (preview mode):
```json
{
  "parsed_rows": 15,
  "valid_rows": 14,
  "errors": [
    {"row": 7, "column": "Purchase Price", "error": "Invalid number format"}
  ],
  "preview": [...],
  "import_token": "temp_token_for_confirm"
}
```

### Confirm Import

```
POST /import/excel/confirm
```

**Request Body:**
```json
{
  "import_token": "temp_token_for_confirm",
  "portfolio_id": "uuid"
}
```

### Export to Excel

```
GET /export/excel/{portfolio_id}
```

Returns downloadable `.xlsx` file.

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

Returns all settings for the current user grouped by category.

**Response** `200 OK`:
```json
{
  "profile": {
    "display_name": "Ankit",
    "email": "user@example.com",
    "two_factor_enabled": true
  },
  "display": {
    "theme": "dark",
    "preferred_currency": "INR",
    "table_density": "comfortable",
    "default_chart_days": 30
  },
  "notifications": {
    "email_enabled": true,
    "email_from": "alerts@financetracker.app",
    "whatsapp_enabled": false,
    "telegram_enabled": true,
    "telegram_chat_id": "123456789",
    "sms_enabled": false,
    "push_enabled": true
  },
  "brokers": {
    "zerodha": {"connected": true, "last_synced": "2025-01-20T09:15:00Z"},
    "icici_direct": {"connected": false}
  },
  "ai": {
    "active_provider": "ollama",
    "ollama_url": "http://localhost:11434",
    "ollama_model": "llama3.2",
    "openai_configured": false,
    "claude_configured": false,
    "gemini_configured": false,
    "ai_features_enabled": true
  },
  "market_data": {
    "price_refresh_interval": 5,
    "market_hours_in": "09:15-15:30 IST",
    "market_hours_de": "09:00-17:30 CET"
  }
}
```

### Update Settings

```
PUT /settings
```

**Request Body** (partial update):
```json
{
  "display": {
    "theme": "light",
    "default_chart_days": 90
  },
  "ai": {
    "active_provider": "openai",
    "openai_api_key": "sk-..."
  }
}
```

Sensitive values (API keys) are encrypted with Fernet before storage.

### Test Notification Channel

```
POST /settings/test/email
POST /settings/test/whatsapp
POST /settings/test/telegram
POST /settings/test/sms
```

Sends a test notification and returns success/failure.

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

**Response** `200 OK`:
```json
{
  "database": {"status": "healthy", "type": "sqlite", "size_mb": 12.5},
  "redis": {"status": "unavailable", "fallback": "asyncio"},
  "ollama": {"status": "healthy", "model": "llama3.2", "url": "http://localhost:11434"},
  "yfinance": {"status": "healthy", "last_fetch": "2025-01-20T14:25:00Z"},
  "email": {"status": "not_configured"},
  "whatsapp": {"status": "not_configured"},
  "telegram": {"status": "healthy", "bot_name": "@FinanceTrackerBot"}
}
```

---

## WebSocket Channels

### Price Stream

```
WS /ws/prices
```

**Subscribe** (client sends):
```json
{
  "action": "subscribe",
  "symbols": ["RELIANCE.NS", "TCS.NS", "SAP.DE"]
}
```

**Price Update** (server sends):
```json
{
  "type": "price_update",
  "symbol": "RELIANCE.NS",
  "price": 2681.00,
  "change": 16.00,
  "change_percent": 0.60,
  "volume": 8543200,
  "timestamp": "2025-01-20T14:30:05Z"
}
```

**Unsubscribe** (client sends):
```json
{
  "action": "unsubscribe",
  "symbols": ["SAP.DE"]
}
```

### Alert Stream

```
WS /ws/alerts
```

**Alert Triggered** (server sends):
```json
{
  "type": "alert_triggered",
  "holding_id": "uuid",
  "stock_symbol": "HDFCBANK.NS",
  "stock_name": "HDFC Bank Ltd",
  "alert_type": "PRICE_RANGE",
  "action_needed": "Y",
  "action_color": "DARK_RED",
  "current_price": 1395.00,
  "base_level": 1400.00,
  "message": "HDFC Bank has dropped below base level (1400.00). Current price: 1395.00",
  "timestamp": "2025-01-20T14:31:00Z"
}
```

### Chat Stream

```
WS /ws/chat
```

Used for streaming LLM responses token by token.

**Client sends:**
```json
{
  "action": "message",
  "session_id": "uuid",
  "content": "What is the RSI trend for Reliance?"
}
```

**Server streams:**
```json
{"type": "chat_token", "token": "Based"}
{"type": "chat_token", "token": " on"}
{"type": "chat_token", "token": " the"}
...
{"type": "chat_complete", "session_id": "uuid"}
```

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

Returns total dividends received, dividend yield, total reinvested, count, and monthly calendar.

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

### Update Asset

```
PUT /net-worth/assets/{asset_id}
```

### Delete Asset

```
DELETE /net-worth/assets/{asset_id}
```

---

## ESG Scoring

### Get Portfolio ESG

```
GET /esg
```

Returns ESG (Environmental, Social, Governance) scores for all holdings using yfinance sustainability data, with a portfolio-level weighted average.

### Get Stock ESG

```
GET /esg/{symbol}
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
GET /earnings
```

Returns upcoming earnings dates for all stocks in the user's portfolios.

### Get Stock Earnings

```
GET /earnings/{symbol}
```

Returns earnings dates for a specific stock.

---

## F&O Positions

### List Positions

```
GET /fno/positions
```

Returns all futures & options positions for the current user.

### Get Position Summary

```
GET /fno/summary
```

Returns total P&L, margin used, and position counts.

### Add Position

```
POST /fno/positions
```

**Request Body:**
```json
{
  "symbol": "NIFTY",
  "exchange": "NSE",
  "instrument_type": "CE",
  "strike_price": 22000.0,
  "expiry_date": "2025-02-27",
  "lot_size": 50,
  "quantity": 1,
  "entry_price": 150.00,
  "position_type": "LONG"
}
```

For `instrument_type: "FUT"`, `strike_price` is optional (null).

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
POST /analytics/drift/{portfolio_id}/holding/{holding_id}/target
```

Sets the target allocation percentage for a specific holding.

**Body:** `{ "target_allocation_pct": 25.0 }`

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
GET /analytics/sheets-export/{portfolio_id}
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
GET /benchmark
```

**Query Parameters:**
| Parameter | Type | Default | Description |
|---|---|---|---|
| `benchmark` | string | `NIFTY50` | `NIFTY50`, `SENSEX`, `DAX`, `SP500`, `NASDAQ` |
| `days` | int | 90 | Comparison period |

### Stock Comparison

```
GET /comparison
```

**Query Parameters:**
| Parameter | Type | Required | Description |
|---|---|---|---|
| `symbols` | string | Yes | Comma-separated (up to 3): `RELIANCE.NS,TCS.NS,INFY.NS` |
| `days` | int | No | Comparison period (default 90) |

### XIRR Calculation

```
GET /xirr/{holding_id}
```

Returns the XIRR (Extended Internal Rate of Return) for a holding based on its transactions.

---

## Stop-Loss Tracker

### Get Stop-Losses

```
GET /stop-loss
```

Returns stop-loss levels for all holdings (stored in `custom_fields` JSON).

### Set Stop-Loss

```
PUT /stop-loss/{holding_id}
```

**Request Body:**
```json
{
  "stop_loss_price": 2200.00,
  "stop_loss_type": "FIXED"
}
```

---

## Common Response Formats

### Pagination

All list endpoints support pagination:

```json
{
  "items": [...],
  "total": 150,
  "page": 1,
  "per_page": 50,
  "pages": 3
}
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

| Endpoint Group | Limit |
|---|---|
| General API | 100 requests/minute |
| Register | 5 requests/minute |
| Login | 10 requests/minute |
| Token Refresh | 20 requests/minute |
| Import/Export | 5 requests/minute |
| AI/Chat | 30 requests/minute |
| WebSocket | 5 connections per user |
