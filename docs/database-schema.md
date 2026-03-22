# Database Schema

> FinanceTracker -- Full Database Schema Documentation

## Overview

FinanceTracker uses **SQLAlchemy 2.0** in async mode with **Alembic** for migrations. The schema is database-agnostic:

- **Development**: SQLite via `aiosqlite`
- **Production**: PostgreSQL via `asyncpg`

The database currently has **19 tables**. All tables use UUID/integer primary keys and include `created_at`/`updated_at` timestamps.

---

## Entity Relationship Diagram

```
  users
  +---+                               portfolios
  | 1 |------------------------------<| * |
  +---+          |                     +---+
    |            |                       |
    |            |                       |
    | 1          | 1                     | 1
    |            |                       |
    v *          v *                     v *
  user_       alerts                  holdings
  preferences +---+                   +---+
  +---+         |                       |
                |                       |
                |                       | 1
                |                       |
                |                       v *
                |                     transactions
                |                     +---+
                |                       |
    | 1         |                       | 1
    |           |                       |
    v *         |                       v 0..1
  app_          |                     tax_records
  settings      |                     +---+
                |
  +---+         |
  watchlist_    |                     dividends
  items         |                     +---+ (belongs to holding)
  +---+         |
  (belongs      |                     mutual_fund_holdings
   to user)     |                     +---+ (belongs to portfolio)
                |
  goals         |                     broker_connections
  +---+         |                     +---+ (belongs to user)
  (belongs      |
   to user,     |                     forex_rates
   links to     |                     +---+ (standalone)
   portfolio)   |
                |                     price_history
  chat_         |                     +---+ (by symbol)
  sessions      |
  +---+         |                     notification_log
  (belongs      |                     +---+ (belongs to user)
   to user)     |
```

---

## Core Tables

### users

The central user account table.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK, default uuid4 | Unique user identifier |
| `email` | VARCHAR(255) | UNIQUE, NOT NULL, INDEX | Login email address |
| `password_hash` | VARCHAR(255) | NOT NULL | bcrypt-hashed password |
| `totp_secret` | VARCHAR(255) | NULLABLE | TOTP 2FA secret (encrypted) |
| `display_name` | VARCHAR(100) | NOT NULL | Name shown in UI |
| `preferred_currency` | VARCHAR(3) | NOT NULL, DEFAULT 'INR' | INR, EUR, or USD |
| `theme_preference` | VARCHAR(10) | NOT NULL, DEFAULT 'dark' | dark, light, system |
| `notification_preferences` | JSON | NOT NULL, DEFAULT '{}' | Channel preferences as JSON |
| `is_active` | BOOLEAN | NOT NULL, DEFAULT true | Soft delete flag |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() | Account creation time |
| `updated_at` | TIMESTAMP | NOT NULL, auto-update | Last modification time |

**Indexes:**
- `ix_users_email` (UNIQUE) on `email`

---

### portfolios

Groups holdings into named portfolios. Each user can have multiple portfolios (e.g., "Indian Stocks", "German ETFs").

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK | Unique portfolio identifier |
| `user_id` | UUID | FK -> users.id, NOT NULL, INDEX | Owner |
| `name` | VARCHAR(100) | NOT NULL | Portfolio display name |
| `description` | TEXT | NULLABLE | User-provided description |
| `currency` | VARCHAR(3) | NOT NULL, DEFAULT 'INR' | Portfolio base currency |
| `is_default` | BOOLEAN | NOT NULL, DEFAULT false | Only one default per user |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() | Creation time |
| `updated_at` | TIMESTAMP | NOT NULL, auto-update | Last modification time |

**Indexes:**
- `ix_portfolios_user_id` on `user_id`

**Constraints:**
- FK `user_id` REFERENCES `users(id)` ON DELETE CASCADE

---

### holdings

The central table representing a stock position within a portfolio. Contains all range levels for the color-coded alert system.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK | Unique holding identifier |
| `portfolio_id` | UUID | FK -> portfolios.id, NOT NULL, INDEX | Parent portfolio |
| `stock_symbol` | VARCHAR(20) | NOT NULL, INDEX | Exchange-qualified symbol (e.g., RELIANCE.NS, SAP.DE) |
| `stock_name` | VARCHAR(200) | NOT NULL | Full company name |
| `exchange` | VARCHAR(10) | NOT NULL | NSE, BSE, XETRA, FRA, etc. |
| `cumulative_quantity` | DECIMAL(15,4) | NOT NULL, DEFAULT 0 | Net shares held (auto-calculated from transactions) |
| `average_price` | DECIMAL(15,4) | NOT NULL, DEFAULT 0 | Weighted average purchase price |
| `current_price` | DECIMAL(15,4) | NULLABLE | Latest market price |
| `current_rsi` | DECIMAL(5,2) | NULLABLE | Latest RSI-14 value (0-100) |
| `lower_mid_range_1` | DECIMAL(15,4) | NULLABLE | Upper bound of lower caution zone |
| `lower_mid_range_2` | DECIMAL(15,4) | NULLABLE | Lower bound of lower caution zone |
| `upper_mid_range_1` | DECIMAL(15,4) | NULLABLE | Lower bound of upper opportunity zone |
| `upper_mid_range_2` | DECIMAL(15,4) | NULLABLE | Upper bound of upper opportunity zone |
| `base_level` | DECIMAL(15,4) | NULLABLE | Critical support / floor price |
| `top_level` | DECIMAL(15,4) | NULLABLE | Target price / ceiling |
| `action_needed` | VARCHAR(20) | NOT NULL, DEFAULT 'N' | N, Y_LOWER_MID, Y_UPPER_MID, Y_DARK_RED, Y_DARK_GREEN |
| `sector` | VARCHAR(100) | NULLABLE | Industry sector classification |
| `notes` | TEXT | NULLABLE | User notes on this holding |
| `custom_fields` | JSON | NOT NULL, DEFAULT '{}' | User-defined custom column values |
| `last_price_update` | TIMESTAMP | NULLABLE | When price was last refreshed |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() | When holding was first added |
| `updated_at` | TIMESTAMP | NOT NULL, auto-update | Last modification time |

**Indexes:**
- `ix_holdings_portfolio_id` on `portfolio_id`
- `ix_holdings_stock_symbol` on `stock_symbol`
- `ix_holdings_action_needed` on `action_needed`

**Constraints:**
- FK `portfolio_id` REFERENCES `portfolios(id)` ON DELETE CASCADE
- UNIQUE(`portfolio_id`, `stock_symbol`) -- One holding per stock per portfolio

**Action Needed Values:**

| Value | Color | Meaning |
|---|---|---|
| `N` | None | Price outside all alert ranges |
| `Y_LOWER_MID` | Light Red | Price between lower_mid_range_2 and lower_mid_range_1 |
| `Y_UPPER_MID` | Light Green | Price between upper_mid_range_1 and upper_mid_range_2 |
| `Y_DARK_RED` | Dark Red | Price at or below base_level (or between base and lower_mid_range_2) |
| `Y_DARK_GREEN` | Dark Green | Price at or above top_level (or between upper_mid_range_2 and top) |

---

### transactions

Records individual buy/sell actions for holdings.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK | Unique transaction identifier |
| `holding_id` | UUID | FK -> holdings.id, NOT NULL, INDEX | Parent holding |
| `type` | VARCHAR(4) | NOT NULL | BUY or SELL |
| `date` | DATE | NOT NULL | Transaction date |
| `quantity` | DECIMAL(15,4) | NOT NULL | Number of shares |
| `price` | DECIMAL(15,4) | NOT NULL | Price per share |
| `brokerage` | DECIMAL(10,2) | NOT NULL, DEFAULT 0 | Brokerage/commission fees |
| `notes` | TEXT | NULLABLE | Transaction notes |
| `source` | VARCHAR(10) | NOT NULL, DEFAULT 'MANUAL' | MANUAL, EXCEL, or BROKER |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() | Record creation time |

**Indexes:**
- `ix_transactions_holding_id` on `holding_id`
- `ix_transactions_date` on `date`
- `ix_transactions_type` on `type`

**Constraints:**
- FK `holding_id` REFERENCES `holdings(id)` ON DELETE CASCADE
- CHECK `type IN ('BUY', 'SELL')`
- CHECK `quantity > 0`
- CHECK `price > 0`

**Trigger Logic** (application-level):
After any INSERT or DELETE on transactions, the parent holding's `cumulative_quantity` and `average_price` are recalculated:
- `cumulative_quantity = SUM(BUY quantities) - SUM(SELL quantities)`
- `average_price = weighted average of BUY transactions for remaining shares (FIFO)`

---

### price_history

Stores historical OHLCV data for charting and technical analysis.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK | Unique record identifier |
| `stock_symbol` | VARCHAR(20) | NOT NULL, INDEX | Exchange-qualified symbol |
| `exchange` | VARCHAR(10) | NOT NULL | Exchange code |
| `date` | DATE | NOT NULL | Trading date |
| `open` | DECIMAL(15,4) | NOT NULL | Opening price |
| `high` | DECIMAL(15,4) | NOT NULL | Day's high |
| `low` | DECIMAL(15,4) | NOT NULL | Day's low |
| `close` | DECIMAL(15,4) | NOT NULL | Closing price |
| `volume` | BIGINT | NOT NULL | Trading volume |
| `rsi_14` | DECIMAL(5,2) | NULLABLE | Calculated RSI-14 at close |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() | Record creation time |

**Indexes:**
- `ix_price_history_symbol_date` (UNIQUE) on (`stock_symbol`, `date`)
- `ix_price_history_date` on `date`

---

### alerts

User-configured alert rules.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK | Unique alert identifier |
| `user_id` | UUID | FK -> users.id, NOT NULL, INDEX | Alert owner |
| `holding_id` | UUID | FK -> holdings.id, NULLABLE | Linked holding (null for watchlist/custom) |
| `watchlist_item_id` | UUID | FK -> watchlist_items.id, NULLABLE | Linked watchlist item |
| `alert_type` | VARCHAR(20) | NOT NULL | PRICE_RANGE, RSI, CUSTOM |
| `condition` | JSON | NOT NULL | Alert condition rules (see below) |
| `is_active` | BOOLEAN | NOT NULL, DEFAULT true | Whether alert is enabled |
| `last_triggered` | TIMESTAMP | NULLABLE | When last triggered |
| `cooldown_minutes` | INTEGER | NOT NULL, DEFAULT 60 | Min time between re-triggers |
| `channels` | JSON | NOT NULL | List of notification channels |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() | Creation time |
| `updated_at` | TIMESTAMP | NOT NULL, auto-update | Last modification time |

**Condition JSON Examples:**

Price range alert:
```json
{
  "price_above": 3000.00,
  "price_below": 2200.00
}
```

RSI alert:
```json
{
  "rsi_above": 70,
  "rsi_below": 30
}
```

Custom alert:
```json
{
  "metric": "day_change_percent",
  "operator": "greater_than",
  "value": 5.0
}
```

**Channels JSON Example:**
```json
["email", "whatsapp", "telegram", "push", "in_app"]
```

---

### watchlist_items

Stocks the user is watching but does not own. Uses the same range-level alert system as holdings.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK | Unique item identifier |
| `user_id` | UUID | FK -> users.id, NOT NULL, INDEX | Owner |
| `stock_symbol` | VARCHAR(20) | NOT NULL | Exchange-qualified symbol |
| `exchange` | VARCHAR(10) | NOT NULL | Exchange code |
| `target_buy_price` | DECIMAL(15,4) | NULLABLE | Desired entry price |
| `current_price` | DECIMAL(15,4) | NULLABLE | Latest market price |
| `current_rsi` | DECIMAL(5,2) | NULLABLE | Latest RSI-14 |
| `lower_mid_range_1` | DECIMAL(15,4) | NULLABLE | Same range system as holdings |
| `lower_mid_range_2` | DECIMAL(15,4) | NULLABLE | |
| `upper_mid_range_1` | DECIMAL(15,4) | NULLABLE | |
| `upper_mid_range_2` | DECIMAL(15,4) | NULLABLE | |
| `base_level` | DECIMAL(15,4) | NULLABLE | |
| `top_level` | DECIMAL(15,4) | NULLABLE | |
| `notes` | TEXT | NULLABLE | User notes |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() | Creation time |
| `updated_at` | TIMESTAMP | NOT NULL, auto-update | Last modification |

**Indexes:**
- `ix_watchlist_user_id` on `user_id`
- UNIQUE(`user_id`, `stock_symbol`)

---

## Extended Tables

### mutual_fund_holdings

Tracks mutual fund investments.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK | Unique identifier |
| `portfolio_id` | UUID | FK -> portfolios.id, NOT NULL | Parent portfolio |
| `scheme_code` | VARCHAR(20) | NOT NULL | AMFI scheme code |
| `scheme_name` | VARCHAR(300) | NOT NULL | Full scheme name |
| `folio_number` | VARCHAR(30) | NULLABLE | Folio number from fund house |
| `units` | DECIMAL(15,4) | NOT NULL, DEFAULT 0 | Total units held |
| `nav` | DECIMAL(15,4) | NULLABLE | Latest NAV |
| `invested_amount` | DECIMAL(15,2) | NOT NULL, DEFAULT 0 | Total money invested |
| `current_value` | DECIMAL(15,2) | NULLABLE | units * nav |
| `xirr` | DECIMAL(8,4) | NULLABLE | Calculated XIRR return |
| `last_updated` | TIMESTAMP | NULLABLE | When NAV was last fetched |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() | Creation time |
| `updated_at` | TIMESTAMP | NOT NULL, auto-update | Last modification |

---

### dividends

Records dividend payments received on holdings.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK | Unique identifier |
| `holding_id` | UUID | FK -> holdings.id, NOT NULL, INDEX | Parent holding |
| `ex_date` | DATE | NOT NULL | Ex-dividend date |
| `payment_date` | DATE | NULLABLE | Actual payment date |
| `amount_per_share` | DECIMAL(10,4) | NOT NULL | Dividend per share |
| `total_amount` | DECIMAL(15,2) | NOT NULL | Total dividend received |
| `currency` | VARCHAR(3) | NOT NULL, DEFAULT 'INR' | Dividend currency |
| `is_reinvested` | BOOLEAN | NOT NULL, DEFAULT false | DRIP flag |
| `reinvest_price` | DECIMAL(15,4) | NULLABLE | Price at which dividend was reinvested |
| `reinvest_shares` | DECIMAL(15,4) | NULLABLE | Shares acquired through reinvestment |
| `tds_amount` | DECIMAL(10,2) | NOT NULL, DEFAULT 0 | Tax deducted at source |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() | Record creation time |

---

### tax_records

Computed tax records for each realized gain/loss transaction.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK | Unique identifier |
| `user_id` | UUID | FK -> users.id, NOT NULL, INDEX | Tax record owner |
| `transaction_id` | UUID | FK -> transactions.id, NULLABLE | Linked sell transaction |
| `financial_year` | VARCHAR(10) | NOT NULL | e.g., "2024-25" (India) or "2024" (Germany) |
| `tax_jurisdiction` | VARCHAR(2) | NOT NULL | IN (India) or DE (Germany) |
| `gain_type` | VARCHAR(30) | NOT NULL | STCG, LTCG, ABGELTUNGSSTEUER, VORABPAUSCHALE |
| `stock_symbol` | VARCHAR(20) | NOT NULL | Stock involved |
| `purchase_date` | DATE | NOT NULL | When shares were acquired |
| `sale_date` | DATE | NOT NULL | When shares were sold |
| `purchase_price` | DECIMAL(15,4) | NOT NULL | Price at purchase |
| `sale_price` | DECIMAL(15,4) | NOT NULL | Price at sale |
| `quantity` | DECIMAL(15,4) | NOT NULL | Shares sold |
| `gain_amount` | DECIMAL(15,2) | NOT NULL | Profit or loss amount |
| `tax_amount` | DECIMAL(15,2) | NOT NULL | Calculated tax liability |
| `holding_period_days` | INTEGER | NOT NULL | Days between purchase and sale |
| `forex_rate` | DECIMAL(10,4) | NULLABLE | Exchange rate at time of sale (for cross-currency) |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() | Record creation time |

**Indexes:**
- `ix_tax_records_user_fy` on (`user_id`, `financial_year`)
- `ix_tax_records_jurisdiction` on `tax_jurisdiction`

---

### goals

User-defined financial goals with progress tracking.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK | Unique identifier |
| `user_id` | UUID | FK -> users.id, NOT NULL, INDEX | Goal owner |
| `name` | VARCHAR(200) | NOT NULL | Goal name (e.g., "House Down Payment") |
| `target_amount` | DECIMAL(15,2) | NOT NULL | Target amount to reach |
| `current_amount` | DECIMAL(15,2) | NOT NULL, DEFAULT 0 | Current progress amount |
| `target_date` | DATE | NOT NULL | Deadline for the goal |
| `category` | VARCHAR(20) | NOT NULL | RETIREMENT, HOUSE, EDUCATION, TRAVEL, EMERGENCY, CUSTOM |
| `linked_portfolio_id` | UUID | FK -> portfolios.id, NULLABLE | Linked portfolio |
| `monthly_sip_needed` | DECIMAL(15,2) | NULLABLE | Calculated monthly SIP required |
| `is_achieved` | BOOLEAN | NOT NULL, DEFAULT false | Whether goal is reached |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() | Creation time |
| `updated_at` | TIMESTAMP | NOT NULL, auto-update | Last modification |

---

### broker_connections

Stores encrypted credentials for connected brokers.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK | Unique identifier |
| `user_id` | UUID | FK -> users.id, NOT NULL, INDEX | Connection owner |
| `broker_name` | VARCHAR(30) | NOT NULL | zerodha, icici_direct, groww, angel_one, upstox, fivepaisa, deutsche_bank, comdirect |
| `encrypted_api_key` | TEXT | NULLABLE | Fernet-encrypted API key |
| `encrypted_api_secret` | TEXT | NULLABLE | Fernet-encrypted API secret |
| `access_token_encrypted` | TEXT | NULLABLE | Fernet-encrypted access/session token |
| `token_expiry` | TIMESTAMP | NULLABLE | When access token expires |
| `is_active` | BOOLEAN | NOT NULL, DEFAULT true | Connection status |
| `last_synced` | TIMESTAMP | NULLABLE | Last successful data sync |
| `sync_error` | TEXT | NULLABLE | Last sync error message |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() | Connection creation time |
| `updated_at` | TIMESTAMP | NOT NULL, auto-update | Last modification |

**Constraints:**
- UNIQUE(`user_id`, `broker_name`) -- One connection per broker per user

---

### forex_rates

Daily foreign exchange rates for multi-currency support.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK | Unique identifier |
| `from_currency` | VARCHAR(3) | NOT NULL | Source currency (e.g., EUR) |
| `to_currency` | VARCHAR(3) | NOT NULL | Target currency (e.g., INR) |
| `rate` | DECIMAL(15,6) | NOT NULL | Exchange rate |
| `date` | DATE | NOT NULL | Rate date |
| `source` | VARCHAR(30) | NOT NULL | ECB, exchangerate-api, yfinance |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() | Record creation time |

**Indexes:**
- `ix_forex_rates_pair_date` (UNIQUE) on (`from_currency`, `to_currency`, `date`)

---

### chat_sessions

Stores AI assistant conversation history.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK | Unique session identifier |
| `user_id` | UUID | FK -> users.id, NOT NULL, INDEX | Session owner |
| `title` | VARCHAR(200) | NULLABLE | Auto-generated session title |
| `messages` | JSON | NOT NULL, DEFAULT '[]' | Array of message objects |
| `context` | JSON | NOT NULL, DEFAULT '{}' | Session context (portfolio data, etc.) |
| `provider` | VARCHAR(20) | NULLABLE | LLM provider used (ollama, openai, claude, gemini) |
| `model` | VARCHAR(50) | NULLABLE | Model name (llama3.2, gpt-4, etc.) |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() | Session start time |
| `updated_at` | TIMESTAMP | NOT NULL, auto-update | Last message time |

**Messages JSON Structure:**
```json
[
  {
    "role": "user",
    "content": "Which stocks should I consider selling?",
    "timestamp": "2025-01-20T14:30:00Z"
  },
  {
    "role": "assistant",
    "content": "Based on your portfolio analysis...",
    "timestamp": "2025-01-20T14:30:05Z",
    "tools_used": ["portfolio_data", "risk_calculator"]
  }
]
```

---

### notification_log

Audit trail for all sent notifications.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK | Unique identifier |
| `user_id` | UUID | FK -> users.id, NOT NULL, INDEX | Notification recipient |
| `alert_id` | UUID | FK -> alerts.id, NULLABLE | Triggering alert |
| `channel` | VARCHAR(20) | NOT NULL | email, whatsapp, telegram, sms, push, in_app |
| `subject` | VARCHAR(200) | NULLABLE | Notification subject/title |
| `body` | TEXT | NOT NULL | Notification body content |
| `status` | VARCHAR(10) | NOT NULL, DEFAULT 'QUEUED' | QUEUED, SENT, FAILED |
| `error_message` | TEXT | NULLABLE | Failure reason if status is FAILED |
| `sent_at` | TIMESTAMP | NULLABLE | When notification was delivered |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() | When notification was created |

**Indexes:**
- `ix_notification_log_user_status` on (`user_id`, `status`)
- `ix_notification_log_channel` on `channel`

---

### user_preferences

Stores UI preferences for the holdings table and dashboard layout.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK | Unique identifier |
| `user_id` | UUID | FK -> users.id, UNIQUE, NOT NULL | Preference owner |
| `column_order` | JSON | NOT NULL, DEFAULT '[]' | Ordered list of visible column names |
| `custom_columns` | JSON | NOT NULL, DEFAULT '[]' | Custom column definitions |
| `table_density` | VARCHAR(15) | NOT NULL, DEFAULT 'comfortable' | compact, comfortable, spacious |
| `default_chart_days` | INTEGER | NOT NULL, DEFAULT 30 | Default chart period |
| `theme` | VARCHAR(10) | NOT NULL, DEFAULT 'dark' | dark, light, system |
| `sidebar_collapsed` | BOOLEAN | NOT NULL, DEFAULT false | Sidebar state |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() | Creation time |
| `updated_at` | TIMESTAMP | NOT NULL, auto-update | Last modification |

**Custom Columns JSON:**
```json
[
  {"name": "target_pe", "label": "Target PE", "type": "number", "default": null},
  {"name": "thesis", "label": "Investment Thesis", "type": "text", "default": ""}
]
```

---

### app_settings

Key-value settings store with encryption for sensitive values. Supports both user-level and system-level settings.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | UUID | PK | Unique identifier |
| `user_id` | UUID | FK -> users.id, NOT NULL, INDEX | Setting owner |
| `key` | VARCHAR(100) | NOT NULL | Setting key (e.g., SENDGRID_API_KEY) |
| `value` | TEXT | NOT NULL | Setting value (encrypted for sensitive keys) |
| `is_encrypted` | BOOLEAN | NOT NULL, DEFAULT false | Whether value is Fernet-encrypted |
| `category` | VARCHAR(30) | NOT NULL | notifications, brokers, ai, market_data, display, advanced |
| `updated_at` | TIMESTAMP | NOT NULL, auto-update | Last modification |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() | Creation time |

**Constraints:**
- UNIQUE(`user_id`, `key`) -- One value per key per user

**Setting Priority:**
1. `app_settings` table (user-specific, highest priority)
2. `.env` file (environment variables, deployment-level)
3. Default values in code (lowest priority)

---

### assets

Multi-asset tracking for net worth calculation (crypto, gold, fixed deposits, bonds, real estate).

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | INTEGER | PK, autoincrement | Unique identifier |
| `user_id` | INTEGER | FK -> users.id, NOT NULL, INDEX | Asset owner |
| `asset_type` | VARCHAR(20) | NOT NULL | CRYPTO, GOLD, FIXED_DEPOSIT, BOND, REAL_ESTATE |
| `name` | VARCHAR(200) | NOT NULL | Asset display name |
| `symbol` | VARCHAR(20) | NULLABLE | Ticker symbol (e.g., BTC-USD, GC=F) for live pricing |
| `quantity` | DECIMAL(15,4) | NOT NULL, DEFAULT 0 | Units/quantity held |
| `purchase_price` | DECIMAL(15,4) | NOT NULL, DEFAULT 0 | Total purchase cost |
| `current_value` | DECIMAL(15,2) | NOT NULL, DEFAULT 0 | Current market value |
| `currency` | VARCHAR(3) | NOT NULL, DEFAULT 'INR' | Asset currency |
| `interest_rate` | DECIMAL(5,2) | NULLABLE | Interest rate (for FD/bonds) |
| `maturity_date` | DATE | NULLABLE | Maturity date (for FD/bonds) |
| `notes` | TEXT | NULLABLE | User notes |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() | Creation time |
| `updated_at` | TIMESTAMP | NOT NULL, auto-update | Last modification |

**Indexes:**
- `ix_assets_user_id` on `user_id`
- `ix_assets_asset_type` on `asset_type`

---

### fno_positions

Futures & Options position tracking with P&L calculation.

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | INTEGER | PK, autoincrement | Unique identifier |
| `user_id` | INTEGER | FK -> users.id, NOT NULL, INDEX | Position owner |
| `symbol` | VARCHAR(20) | NOT NULL | Underlying symbol (e.g., NIFTY, RELIANCE) |
| `exchange` | VARCHAR(10) | NOT NULL | Exchange code (NSE, BSE) |
| `instrument_type` | VARCHAR(5) | NOT NULL | FUT, CE (Call), PE (Put) |
| `strike_price` | DECIMAL(15,4) | NULLABLE | Strike price (null for futures) |
| `expiry_date` | DATE | NOT NULL | Contract expiry date |
| `lot_size` | INTEGER | NOT NULL | Contract lot size |
| `quantity` | INTEGER | NOT NULL | Number of lots |
| `entry_price` | DECIMAL(15,4) | NOT NULL | Entry price per unit |
| `exit_price` | DECIMAL(15,4) | NULLABLE | Exit price (null if open) |
| `position_type` | VARCHAR(5) | NOT NULL | LONG or SHORT |
| `status` | VARCHAR(10) | NOT NULL, DEFAULT 'OPEN' | OPEN or CLOSED |
| `pnl` | DECIMAL(15,2) | NULLABLE | Realized P&L (set on close) |
| `created_at` | TIMESTAMP | NOT NULL, DEFAULT now() | Creation time |
| `updated_at` | TIMESTAMP | NOT NULL, auto-update | Last modification |

**Indexes:**
- `ix_fno_positions_user_id` on `user_id`
- `ix_fno_positions_expiry` on `expiry_date`
- `ix_fno_positions_status` on `status`

---

## Migration Strategy

All schema changes are managed through Alembic migrations:

```bash
# Create a new migration after model changes
cd backend && uv run alembic revision --autogenerate -m "description"

# Apply pending migrations
cd backend && uv run alembic upgrade head

# Rollback one migration
cd backend && uv run alembic downgrade -1

# View migration history
cd backend && uv run alembic history
```

### Naming Convention

Migration files follow the pattern: `YYYY_MM_DD_HHMM_description.py`

Example: `2025_01_15_1030_create_initial_tables.py`

---

## Data Integrity Rules

1. **Cascade Deletes**: Deleting a user cascades to all their portfolios, holdings, transactions, alerts, etc.
2. **Orphan Prevention**: Holdings cannot exist without a portfolio. Transactions cannot exist without a holding.
3. **Recalculation Triggers**: After any transaction INSERT/DELETE, the parent holding's `cumulative_quantity` and `average_price` are recalculated at the application level.
4. **Unique Constraints**: One holding per stock per portfolio. One broker connection per broker per user. One forex rate per currency pair per date.
5. **Soft Deletes**: Users have an `is_active` flag rather than hard deletion.
6. **Encrypted Fields**: All API keys, tokens, and TOTP secrets are Fernet-encrypted at rest. The `is_encrypted` flag in `app_settings` identifies which values are encrypted.
