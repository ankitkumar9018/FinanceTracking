# User Guide

> FinanceTracker -- Complete Guide for Users

This guide walks you through everything you need to know to use FinanceTracker effectively. It is written for non-technical users -- no programming knowledge required.

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Importing Your Portfolio from Excel](#importing-your-portfolio-from-excel)
3. [Adding Stocks Manually](#adding-stocks-manually)
4. [Understanding the Dashboard](#understanding-the-dashboard)
5. [Understanding Colors and Alerts](#understanding-colors-and-alerts)
6. [Reading Charts](#reading-charts)
7. [Comparing Stocks](#comparing-stocks)
8. [Stock Screener](#stock-screener)
9. [Setting Up Notifications](#setting-up-notifications)
10. [Connecting Your Broker](#connecting-your-broker)
11. [Using the AI Assistant](#using-the-ai-assistant)
12. [Risk Dashboard](#risk-dashboard)
13. [Tax Features](#tax-features)
14. [Corporate Actions](#corporate-actions)
15. [Goal-Based Investing](#goal-based-investing)
16. [Mutual Funds and Dividends](#mutual-funds-and-dividends)
17. [Watchlist](#watchlist)
18. [Net Worth Tracking](#net-worth-tracking)
19. [ESG Scoring](#esg-scoring)
20. [What-If Simulator](#what-if-simulator)
21. [Earnings Calendar](#earnings-calendar)
22. [Economic Calendar](#economic-calendar)
23. [Market Heatmap](#market-heatmap)
24. [Futures & Options (F&O)](#futures--options-fo)
25. [SIP Calendar](#sip-calendar)
26. [Cash Flow Timeline](#cash-flow-timeline)
27. [Settings and Configuration](#settings-and-configuration)

---

## Getting Started

### Creating Your Account

1. Open FinanceTracker in your browser (http://localhost:3000) or launch the desktop app
2. Click **Register** on the login page
3. Enter your email address, choose a strong password, and set your display name
4. Choose your preferred currency: **INR** (Indian Rupees) or **EUR** (Euros)
5. Click **Create Account**

### First-Time Setup Wizard

After your first login, you will see a guided setup wizard that walks you through:

1. **Welcome** -- A brief introduction to the app
2. **Import Your Portfolio** -- Upload your existing Excel file, or skip to add stocks manually later
3. **Set Your Preferences** -- Choose your preferred theme (dark or light), chart period, and table layout
4. **Configure Notifications** -- Connect your email, WhatsApp, or Telegram for alerts (optional)
5. **Connect a Broker** -- Link your Zerodha, ICICI Direct, or other broker account (optional)

You can skip any step and come back to it later from the Settings page.

### Forgot Your Password?

If you cannot log in:

1. On the login page, click **Forgot password?**
2. Enter your account email and click **Send reset link**
3. Open the reset link from the email you receive
4. Choose a new password (at least 8 characters) and confirm it
5. Log in with your new password

For your security, the app always responds with "if that email exists, a reset link was sent" -- it never reveals whether an email is registered.

If you have Two-Factor Authentication enabled, you will also be asked for your 6-digit authenticator code when logging in -- or one of your one-time backup codes if you cannot reach your authenticator (see [Settings and Configuration](#settings-and-configuration)).

---

## Importing Your Portfolio from Excel

If you already track your investments in Excel, you can import everything in one go.

### Step 1: Prepare Your Excel File

Your Excel file (.xlsx) should have these columns:

| Column | Required? | Example |
|---|---|---|
| Stock Name | Yes | Reliance Industries |
| Date of Purchase | Yes | 2024-01-15 |
| Purchase Quantity | Yes | 50 |
| Purchase Price | Yes | 2450.00 |
| Lower Mid Range 1 | No | 2400.00 |
| Lower Mid Range 2 | No | 2200.00 |
| Upper Mid Range 1 | No | 2800.00 |
| Upper Mid Range 2 | No | 2950.00 |
| Base Level | No | 2000.00 |
| Top Level | No | 3100.00 |
| Sale Quantity | No | 10 |
| Sale Price | No | 2700.00 |
| Sale Date | No | 2024-06-20 |

The column names do not need to match exactly -- the app will try to map them automatically.

### Step 2: Upload

1. Go to **Import** from the sidebar
2. Choose the portfolio to import into
3. Drag and drop your file onto the upload area, or click to browse
4. The file is parsed and imported in one step -- there is no separate preview/confirm screen
5. A summary shows how many rows were parsed and how many holdings/transactions were created

After import, your dashboard will show all your holdings with current prices fetched automatically.

### Re-Importing

If you update your Excel file later, you can import it again. The app will:
- Update existing holdings with new transactions
- Add any new stocks
- Recalculate cumulative quantities and average prices

---

## Adding Stocks Manually

You do not need Excel to use the app. You can add stocks directly from the dashboard.

### Adding a New Stock

1. Click the **+ Add Stock** button on the portfolio page
2. Start typing the stock name or symbol -- a search dropdown will appear
3. Select your stock (e.g., "Reliance Industries -- NSE")
4. Fill in the purchase details: date, quantity, and price
5. Optionally set your range levels (base, mid ranges, top)
6. Click **Add**

### Adding a Transaction to an Existing Stock

1. Find the stock in your portfolio table
2. Click the stock row to open the detail view
3. Click **+ Add Transaction**
4. Choose BUY or SELL
5. Enter the date, quantity, and price
6. Click **Save**

The app automatically recalculates your cumulative quantity and average price.

### Editing Range Levels

You can click directly on any range value in the table (base level, mid ranges, top level) to edit it inline. Press Enter to save.

The **Edit Holding** dialog (on the Holdings page) also has a **Target %** field -- set a target allocation percentage there and the Alerts page will warn you when the holding drifts away from it.

The same dialog has a **Stop-Loss** field. Set a price and the holding shows a stop-loss pill in the table that turns red when the current price falls to or below it. Clear the field to remove the stop-loss.

---

## Understanding the Dashboard

The dashboard is the main page you see after logging in. It has several sections:

### Summary Cards (Top)

At the top, you see cards showing:
- **Total Portfolio Value** -- The current market value of all your holdings
- **Day's P&L** -- How much your portfolio gained or lost today (in amount and percentage)
- **Top Gainer** -- Your best-performing stock today
- **Top Loser** -- Your worst-performing stock today

Below these, **XIRR** and **Benchmark** cards show your portfolio's annualized return (XIRR) and how it compares against an index such as NIFTY50.

These numbers update with animated transitions. Where live streaming is available, prices update automatically over a WebSocket connection; otherwise they refresh on a short polling interval. Use the **refresh** button in the top bar to fetch the latest prices on demand.

### Switching and Creating Portfolios

The portfolio selector in the top bar lets you switch between portfolios. Click the **New portfolio** button (the **+**) next to it to create another portfolio (e.g., separate Indian and German portfolios) without leaving the page -- give it a name and currency, and optionally mark it as your default.

Next to the selector is a **display-currency** dropdown (INR / EUR / USD). Pick one to convert the totals shown across the dashboard and Net Worth pages into that currency for viewing. This is a viewing preference only -- it does not change how your holdings are stored or your account's base currency.

### Holdings Table (Center)

This is the main table showing all your stocks. The default columns are:

| Column | What It Means |
|---|---|
| **Stock** | Company name and exchange |
| **Quantity** | How many shares you hold |
| **Avg Price** | Your weighted average purchase price |
| **Current Price** | The latest market price (updates automatically) |
| **P&L %** | Your profit or loss percentage |
| **Action Needed** | Whether the stock needs your attention (Y or N) -- see Colors section |
| **RSI** | Relative Strength Index -- a momentum indicator (see Glossary) |

You can customize which columns appear and their order in Settings.

### Heatmap (Below Table)

A visual map of your portfolio where each stock is a rectangle:
- **Size** of the rectangle = how much of your portfolio it represents
- **Color** = performance (green for profit, red for loss)

---

## Understanding Colors and Alerts

The color system is the heart of FinanceTracker. It tells you at a glance which stocks need your attention.

### How It Works

For each stock, you set price ranges:
- **Base Level**: The lowest price you are comfortable with (critical support)
- **Lower Mid Range 2**: Start of the caution zone
- **Lower Mid Range 1**: End of the caution zone (closer to your average)
- **Upper Mid Range 1**: Start of the opportunity zone
- **Upper Mid Range 2**: End of the opportunity zone
- **Top Level**: Your target price (where you might consider selling)

### What the Colors Mean

| Color | What It Means | What You Might Do |
|---|---|---|
| **No color** (Action: N) | Price is in the normal range -- no action needed | Nothing, relax |
| **Light Red** (Action: Y) | Price has entered the lower mid range -- caution zone | Watch closely, consider buying the dip |
| **Dark Red** (Action: Y) | Price is at or below your base level -- critical zone | Serious attention needed, evaluate position |
| **Light Green** (Action: Y) | Price has entered the upper mid range -- opportunity zone | Consider booking partial profits |
| **Dark Green** (Action: Y) | Price is at or above your top level -- target reached | Consider selling, target met |

### Visual Indicators

- Light red and light green cells have a gentle pulsing animation to catch your attention
- Dark red cells show a warning icon
- Dark green cells show a celebration icon

### How Alerts Work

When a stock's price enters any of these zones, FinanceTracker:
1. Changes the color in the table immediately
2. Sends you a notification (if configured) via email, WhatsApp, Telegram, SMS, or desktop push
3. Logs the alert in your notification history

---

## Reading Charts

### Price Charts

Click on any stock's **Action Needed** cell or the stock name to open a price chart.

The chart shows:
- **Candlestick bars** -- Each bar represents one day
  - Green candle: price went up that day (close > open)
  - Red candle: price went down that day (close < open)
  - The thick part (body) shows the open-to-close range
  - The thin lines (wicks) show the high and low
- **Volume bars** at the bottom -- How many shares were traded each day
- **Horizontal lines** showing your range levels (base, mid ranges, top)

### RSI Chart

Click on the **RSI** cell to open the RSI chart.

- The RSI line moves between 0 and 100
- **Above 70** (red zone): The stock may be overbought (price might come down)
- **Below 30** (green zone): The stock may be oversold (price might go up)
- **Between 30 and 70**: Normal range

### Chart Time Periods

Use the buttons at the top of any chart to change the time period:
- **7d** -- Last 7 days
- **30d** -- Last 30 days (default)
- **90d** -- Last 3 months
- **1Y** -- Last 1 year
- **All** -- All available history

### Technical Indicator Overlays

If you want more analysis, you can toggle these overlays on the chart:
- **Moving Averages** (SMA/EMA) -- Shows the average price over time
- **Bollinger Bands** -- Shows the normal price range (2 standard deviations)
- **MACD** -- A momentum indicator that shows trend changes
- **Fibonacci** -- Shows mathematical support/resistance levels

---

## Comparing Stocks

The Compare page puts 2-3 stocks side by side.

1. Go to **Compare** from the sidebar
2. Enter 2 or 3 symbols and choose each stock's exchange (NSE, BSE, or XETRA)
3. Pick a period (30 days, 90 days, 180 days, or 1 year)
4. Click **Compare**

You get a metrics table (current price, day change, 52-week high/low, P/E ratio, market cap, volume, dividend yield, and beta) plus a normalized price chart where each stock's price is rebased to 100 at the start of the period, for an apples-to-apples comparison.

### Peer Comparison

The Compare page can also stack a stock up against its **sector peers**. Pick a stock and the app pulls a curated set of same-sector names -- for NSE these cover Banking, IT, Energy, FMCG, Auto, Pharma, and Metals (a few XETRA sectors are covered too) -- and lays them out in a side-by-side metrics table, so you can see how your stock ranks within its industry.

---

## Stock Screener

The Screener filters a curated universe of liquid stocks (major NSE and XETRA names) by fundamentals and technicals. It screens this hand-picked list, not the entire market.

1. Go to **Screener** from the sidebar
2. Choose an exchange (NSE or XETRA) and, optionally, a sector
3. Set any combination of min/max filters: market cap, P/E ratio, dividend yield, price, RSI (14), 52-week position, and day change
4. Optionally add extra symbols to include in the scan
5. Click **Run Screen**

Results appear in a sortable table -- click any column header to sort. A summary line shows how many stocks were scanned and how many matched your filters.

---

## Setting Up Notifications

FinanceTracker can alert you through multiple channels when your stocks need attention.

### Email

1. Go to **Settings** then **Notifications** then **Email**
2. Enter your SendGrid API key (get one free at sendgrid.com)
3. Set the "From" email address
4. Click **Test** to send a test email
5. Enable/disable email notifications with the toggle

### WhatsApp

1. Go to **Settings** then **Notifications** then **WhatsApp**
2. Enter your Twilio Account SID, Auth Token, and WhatsApp number
3. Click **Test** to receive a test WhatsApp message

### Telegram

1. Go to **Settings** then **Notifications** then **Telegram**
2. Enter the Telegram Bot Token (create one via @BotFather on Telegram)
3. The app will detect your Chat ID automatically when you message the bot
4. Click **Test** to send a test message

### Desktop Push Notifications

Enable from Settings -- these work in both the browser and the desktop app. No external service needed.

### In-App Notification Center

The bell icon in the top bar is your in-app notification center. It lists your recently triggered alerts and shows an unread badge counting the alerts you have not looked at yet. Open the panel to read them -- opening it marks everything as seen and clears the badge.

### Alert Routing

You can choose which alert types go to which channels. For example:
- Critical alerts (dark red/dark green) go to all channels
- Routine alerts (light red/light green) go to email and in-app only

---

## Connecting Your Broker

Connecting a broker lets the app sync your holdings automatically.

### Supported Brokers

**India**: Zerodha, ICICI Direct (Angel One, Groww, Upstox, and 5Paisa are listed as "coming soon")
**Germany**: Deutsche Bank, comdirect (coming soon)

### How to Connect

1. Go to **Brokers** in the sidebar
2. Click **Connect** next to your broker
3. Enter your API credentials (API key and secret)
4. For Zerodha, the app then shows a broker login link -- open it, log in, and copy the `request_token` from the page you are redirected to
5. Paste the `request_token` back into the connect form to finish

### After Connecting

- Your holdings can be synced into your portfolio with the **Sync** button
- Prices still come from yfinance (there is no real-time broker price feed)
- You still set range levels manually -- the broker does not control those

---

## Using the AI Assistant

The AI assistant lets you ask questions about your portfolio in plain language.

### How to Open

Click the **AI Assistant** button in the sidebar, or click the chat icon in the bottom-right corner.

### Example Questions

- "Which of my stocks are underperforming?"
- "What is the RSI trend for Reliance?"
- "How much tax will I owe this year?"
- "Should I consider selling any stocks based on their RSI?"
- "What is my portfolio's Sharpe ratio?"
- "Show me stocks where action is needed"

### AI Providers

By default, the AI runs locally using Ollama (free, private, no internet needed). You can optionally connect:
- **OpenAI (GPT-4)** -- Requires API key
- **Claude** -- Requires API key
- **Gemini** -- Requires API key

Configure these in **Settings** then **AI Assistant**.

### Market Insights

Click **Insights** in the AI Assistant to open the insights panel. Enter a symbol and switch between three tabs:

- **Prediction** -- a short-term price forecast (next few days) with a mini chart
- **Anomalies** -- unusual price/volume days flagged over the recent period
- **Sentiment** -- an overall bullish, bearish, or neutral read from recent news

These use the built-in ML models and, like the chat, degrade gracefully if a model or data source is unavailable.

### If AI Is Offline

If no AI provider is available, you will see an "AI assistant offline" message. This does not affect any other part of the app -- everything else works normally.

---

## Risk Dashboard

Go to **Risk** from the sidebar to see risk metrics for the selected portfolio.

### Risk Metrics

Colour-coded summary cards show:

- **Sharpe Ratio** and **Sortino Ratio** -- risk-adjusted return (higher is better)
- **Max Drawdown** -- the largest peak-to-trough decline
- **VaR (95%)** -- the maximum expected daily loss at 95% confidence
- **Volatility** -- annualized standard deviation

### Diversification Score

A diversification card grades how well spread out your portfolio is, based on how much weight sits in single stocks and in individual sectors (a concentration measure). It flags any names or sectors that exceed the concentration thresholds.

### Per-Holding Risk

A table breaks down each holding's beta, correlation, volatility, weight, and contribution to your overall portfolio risk.

### Portfolio Hedge Calculator

This panel gives an **informational estimate** of what it would cost to protect your portfolio's downside using index put options -- roughly how much buying protective puts against a market index would cost for a portfolio your size. It is a rough guide to help you think about hedging costs, **not investment advice**, and the app does not place any trades on your behalf.

---

## Tax Features

### Indian Tax Tracking

FinanceTracker automatically classifies your gains:
- **STCG (Short-Term Capital Gains)**: Stocks held less than 12 months, taxed at 20%
- **LTCG (Long-Term Capital Gains)**: Stocks held over 12 months, taxed at 12.5% (amounts above 1.25 lakh are exempt per FY)

Gains are matched lot by lot on a **FIFO** (first-in, first-out) basis, and long-term gains apply the **31-January-2018 grandfathered cost basis** where it results in a lower taxable gain.

### German Tax Tracking

- **Abgeltungssteuer**: 26.375% flat tax on capital gains
- **Freistellungsauftrag / Sparer-Pauschbetrag**: 1,000 EUR annual exemption (2,000 EUR for couples filing jointly)
- **Teilfreistellung**: partial exemption for fund holdings (equity, mixed, or real-estate funds), applied automatically once you set a **fund type** on a holding
- **Vorabpauschale**: advance lump-sum tax on accumulating funds

### German Advanced Tax

On the Tax page, switch to the **Germany** tab to see two extra panels:
- **Sparer-Pauschbetrag** -- a progress bar showing how much of your annual tax-free allowance is used, with a **Single / Joint** toggle that adjusts the allowance
- **Estimated Vorabpauschale** -- an estimate of the advance lump-sum tax across your German fund holdings (set a fund type on your XETRA holdings to see it)

### Tax Dashboard

Go to **Tax** in the sidebar to see:
- India / Germany tabs and a financial-year selector
- Year-wise summary of gains and losses
- STCG vs LTCG breakdown
- Tax harvesting suggestions ("sell these losing stocks to save on tax")

### Holding-Period Timer

For Indian holdings, the Tax page shows a per-lot countdown to **LTCG eligibility** -- the point 12 months after purchase when a lot's gains switch from short-term (20%) to long-term (12.5%). Each lot shows how long it has left to qualify and the **estimated tax saving** you unlock by holding it past that mark, so you can avoid selling just before a lot turns long-term.

### Capital Gains Tax Report

From the **Reports** page you can download a consolidated, ITR-ready **Capital Gains Tax Report** for a financial year -- per-transaction gains plus STCG/LTCG, tax, and exemption totals. Pick the financial year and jurisdiction (India or Germany) and download it as **CSV** or **HTML**.

Tax records can also be bulk-imported/exported as CSV from the Import and Reports pages.

---

## Corporate Actions

The Corporate Actions page detects stock splits and bonus issues on your holdings and adjusts them for you.

1. Go to **Corporate Actions** from the sidebar
2. Click **Detect now** to scan your holdings against market data
3. Detected actions appear under **Pending review** with the split/bonus ratio and ex-date
4. Click **Apply** to adjust the holding (quantity is multiplied and average price divided by the ratio), or **Dismiss** to ignore it

Applied and dismissed actions move to the **History** list, so you always have a record of what changed.

---

## Goal-Based Investing

### Setting Up a Goal

1. Go to **Goals** from the sidebar
2. Click **+ New Goal**
3. Fill in:
   - Goal name (e.g., "House Down Payment")
   - Target amount (e.g., 25,00,000)
   - Target date (e.g., December 2027)
   - Category (Retirement, House, Education, Travel, Emergency, Custom)
   - Link a portfolio (optional)
4. Click **Create**

### Tracking Progress

Each goal shows:
- A visual progress gauge (fills up as you get closer)
- How much you have invested vs your target
- Monthly SIP amount needed to reach your goal on time
- Time remaining

When you hit 25%, 50%, 75%, and 100% of your goal, you see a celebration animation.

### Planning Calculators

Below your goals are two planning calculators:

- **FIRE / Retirement** -- enter your current net worth (auto-filled from Net Worth), monthly contribution, expected annual return, annual retirement expenses, withdrawal rate, and an optional annual step-up. It projects your **FIRE number** (the corpus that covers your expenses), how many years until you reach it, and a year-by-year corpus table.
- **SIP Calculator** -- compare your final corpus **with vs. without** an annual step-up, so you can see how much a rising SIP adds over time.

---

## Mutual Funds and Dividends

### Mutual Funds

- Add mutual fund holdings manually or bulk-import them from a CSV file (a template is available on the Import page)
- NAV (Net Asset Value) can be refreshed from mfapi.in
- **XIRR** (money-weighted annualized return) is calculated across your funds and shown in the summary
- **Overlap X-Ray** -- shows how much your funds share the same underlying stocks (look-through), with a heatmap and a list of the top common holdings
- **Fee Analyzer** -- shows your weighted expense ratio and the projected fee drag over 5, 10, and 20 years, and flags high-fee funds

The Overlap X-Ray and Fee Analyzer are best-effort and depend on the availability of fund constituent and expense data; each panel notes how many of your funds it could cover.

### Dividends

- Record dividends received on each holding
- Track if dividends were reinvested (DRIP)
- Dividend calendar shows monthly dividend totals
- Delete a dividend record with the trash button on its row
- **Forward Income forecast** -- projects your dividend income for the next 12 months, with an estimated annual total, forward yield, and **yield on cost**, plus a per-holding breakdown. Forecasts are best-effort estimates based on dividend history and rates.

---

## Watchlist

The watchlist lets you track stocks you are interested in but do not own yet.

1. Go to **Watchlist** from the sidebar
2. Click **+ Add to Watchlist**
3. Search for a stock and set your desired buy price and range levels
4. The same color-coded alert system applies to watchlist items
5. Click **Add to Portfolio** when you are ready to buy

---

## Net Worth Tracking

Track your total net worth across all asset types, not just stocks.

### Supported Asset Types

- **Stocks** -- Automatically included from your portfolio holdings
- **Crypto** -- Bitcoin, Ethereum, etc. with live price updates
- **Gold** -- Physical gold or gold ETFs with live pricing
- **Fixed Deposits** -- Bank FDs with interest rate and maturity tracking
- **Bonds** -- Government and corporate bonds
- **Real Estate** -- Property investments with manual valuation

### How to Use

1. Go to **Net Worth** from the sidebar
2. Your stock holdings are automatically included
3. Click **+ Add Asset** to add other assets (crypto, gold, FD, bonds, real estate)
4. For crypto and gold with a ticker symbol, prices update automatically
5. For fixed deposits and real estate, update values manually
6. Remove an asset with the delete button on its card

The page shows a donut chart breakdown by asset type and a total net worth figure.

### Emergency-Fund Indicator

Enter your **monthly expenses** on the Net Worth page to see how many months your **liquid assets** (fixed deposits, crypto, and gold) would cover if your income stopped. Stocks are counted separately, since they are less readily accessible in an emergency. The indicator shows a **critical**, **adequate**, or **strong** status so you can tell at a glance whether your safety net is large enough.

---

## ESG Scoring

View Environmental, Social, and Governance (ESG) scores for your holdings.

1. Go to **ESG** from the sidebar
2. Each stock shows individual E, S, and G scores as semicircular gauges
3. A portfolio-level weighted average ESG score is calculated
4. Scores use traffic-light colors (green = good, yellow = average, red = poor)

ESG data is fetched from yfinance sustainability data. Not all stocks have ESG scores available.

---

## What-If Simulator

Test hypothetical investment scenarios before committing real money.

1. Go to **What-If** from the sidebar
2. Enter a stock symbol, investment amount, and date range
3. Click **Simulate** to see what your returns would have been
4. Compare against benchmarks (NIFTY50, S&P500, etc.)

---

## Earnings Calendar

Stay on top of upcoming earnings announcements.

1. Go to **Earnings** from the sidebar
2. A monthly calendar grid shows earnings dates for all your holdings
3. Urgency badges indicate how soon each earnings date is
4. Click any date to see which stocks report that day

---

## Economic Calendar

The Economic Calendar gathers upcoming catalysts for the selected portfolio into a single chronological agenda.

1. Go to **Economic Calendar** from the sidebar
2. Events are grouped by date and tagged as **Earnings**, **Ex-Dividend**, or **Macro** (each with a region flag)
3. Use the filter pills at the top to show only one event type
4. Macro events show an importance indicator (low, medium, or high)

---

## Market Heatmap

A visual treemap of market sectors showing relative performance.

1. Go to **Market Heatmap** from the sidebar
2. Each rectangle represents a stock, grouped by sector
3. Rectangle size = weight in your portfolio
4. Color = performance (green for gains, red for losses)

---

## Futures & Options (F&O)

Track your derivatives positions alongside your equity holdings.

1. Go to **F&O** from the sidebar
2. Click **+ Add Position** to enter a new position
3. Choose instrument type: **FUT** (futures), **CE** (call option), or **PE** (put option)
4. For options, enter the strike price and expiry date
5. Summary cards show realized and unrealized P&L and open position count

---

## SIP Calendar

View all your recurring investments (SIPs), dividends, and earnings in one calendar.

1. Go to **SIP Calendar** from the sidebar
2. A monthly grid shows color-coded dots for each event type
3. SIP dates are auto-detected from recurring transaction patterns

---

## Cash Flow Timeline

The Cash Flow page shows how money has moved through your portfolio over time.

1. Go to **Cash Flow** from the sidebar (under *Analysis*)
2. Each month shows money **in** and **out** -- buys and sells, plus dividends received
3. A combined bar-and-line chart plots the monthly flows as bars and your **cumulative net** as a line
4. Totals summarise money in, money out, and net flow across the whole period

---

## Settings and Configuration

### Display Settings

- **Theme**: Dark, Light, or System (follows your OS)
- **Currency**: INR, EUR, or USD -- your account's base currency
- **Table Density**: Compact, Comfortable, or Spacious
- **Default Chart Period**: 7 days, 30 days, 90 days, or 1 year

For quick viewing in a different currency without changing your base currency, use the **display-currency** dropdown in the top bar (see [Understanding the Dashboard](#understanding-the-dashboard)).

### Custom Columns

1. Go to **Settings** then **Display** then **Customize Columns**
2. Toggle built-in columns on/off (Sector, P&L Amount, Volume, Dividend Yield, etc.)
3. Click **+ Add Custom Column** to create your own (name and type: text, number, or date)
4. Drag columns to reorder them

### Security

The **Security** section in Settings covers your account protection:

- **Change Password**: Enter your current password and a new one
- **Two-Factor Authentication (2FA)**: Set up an authenticator app (scan the QR / enter the secret, then confirm with a code). You can disable 2FA later with a current code.
- **Backup Codes**: When you enable 2FA, the app issues **10 one-time recovery codes** -- save them somewhere safe. If you ever lose access to your authenticator, you can enter one of these codes instead of the 6-digit code at login. Each code works **only once**. The Security section shows how many codes you have left and lets you **regenerate** a fresh set at any time (which invalidates the old ones).

### Data Backup

- **Export**: Go to the **Reports** page for holdings/transactions CSV, a JSON portfolio backup, an HTML report, and Google Sheets export
- **Import**: Go to the **Import** page to restore a JSON backup or import Excel/CSV files

---

## Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Cmd/Ctrl + K` | Open command palette |
| `Cmd/Ctrl + Shift + D` | Go to Dashboard |
| `Cmd/Ctrl + Shift + H` | Go to Holdings |
| `Cmd/Ctrl + Shift + W` | Go to Watchlist |
| `Cmd/Ctrl + Shift + A` | Go to Alerts |
| `Cmd/Ctrl + Shift + I` | Go to Import |
| `?` | Open help dialog |
| `Escape` | Close any open panel or modal |

---

## Getting Help

- Click the **?** button in the top-right corner of any page for contextual help
- Visit the **Help Center** from the sidebar for searchable articles
- Hover over any column header or icon for a tooltip explanation
- Financial terms are underlined -- hover or click them for simple definitions

---

## Related Documentation

- [FAQ](faq.md) -- Frequently asked questions
- [Troubleshooting](troubleshooting.md) -- Common issues and solutions
- [Tax Guide](tax-guide.md) -- Detailed tax information
- [Broker Integration](broker-integration.md) -- Technical broker details
