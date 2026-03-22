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
7. [Setting Up Notifications](#setting-up-notifications)
8. [Connecting Your Broker](#connecting-your-broker)
9. [Using the AI Assistant](#using-the-ai-assistant)
10. [Tax Features](#tax-features)
11. [Goal-Based Investing](#goal-based-investing)
12. [Mutual Funds and Dividends](#mutual-funds-and-dividends)
13. [Watchlist](#watchlist)
14. [Net Worth Tracking](#net-worth-tracking)
15. [ESG Scoring](#esg-scoring)
16. [What-If Simulator](#what-if-simulator)
17. [Earnings Calendar](#earnings-calendar)
18. [Market Heatmap](#market-heatmap)
19. [Futures & Options (F&O)](#futures--options-fo)
20. [SIP Calendar](#sip-calendar)
21. [Settings and Configuration](#settings-and-configuration)

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

The column names do not need to match exactly -- the app will try to map them automatically and let you confirm.

### Step 2: Upload

1. Go to **Import** from the sidebar
2. Drag and drop your file onto the upload area, or click to browse
3. Wait for the file to be parsed

### Step 3: Review and Confirm

1. A preview table shows all the data the app found in your file
2. Any errors are highlighted in red (for example, an invalid price format)
3. Fix any issues or accept the preview
4. Click **Confirm Import**

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

---

## Understanding the Dashboard

The dashboard is the main page you see after logging in. It has several sections:

### Summary Cards (Top)

At the top, you see cards showing:
- **Total Portfolio Value** -- The current market value of all your holdings
- **Day's P&L** -- How much your portfolio gained or lost today (in amount and percentage)
- **Top Gainer** -- Your best-performing stock today
- **Top Loser** -- Your worst-performing stock today

These numbers update in real-time with animated transitions.

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

### Alert Routing

You can choose which alert types go to which channels. For example:
- Critical alerts (dark red/dark green) go to all channels
- Routine alerts (light red/light green) go to email and in-app only

---

## Connecting Your Broker

Connecting a broker lets the app automatically sync your holdings and get real-time prices.

### Supported Brokers

**India**: Zerodha, ICICI Direct, Angel One, Upstox, 5Paisa
**Germany**: Deutsche Bank, comdirect

### How to Connect

1. Go to **Settings** then **Brokers**
2. Click **Connect** next to your broker
3. Enter your API credentials (API key and secret)
4. You will be redirected to your broker's login page
5. Log in and grant access
6. You will be redirected back to FinanceTracker

### After Connecting

- Your holdings are automatically imported
- Current prices update in real-time via your broker's feed
- New transactions appear automatically
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

### If AI Is Offline

If no AI provider is available, you will see an "AI assistant offline" message. This does not affect any other part of the app -- everything else works normally.

---

## Tax Features

### Indian Tax Tracking

FinanceTracker automatically classifies your gains:
- **STCG (Short-Term Capital Gains)**: Stocks held less than 12 months, taxed at 20%
- **LTCG (Long-Term Capital Gains)**: Stocks held over 12 months, taxed at 12.5% (amounts above 1.25 lakh are exempt per FY)
- **Dividend TDS**: Tax deducted at source on dividends above 5,000

### German Tax Tracking

- **Abgeltungssteuer**: 26.375% flat tax on capital gains
- **Freistellungsauftrag**: 1,000 EUR annual exemption (2,000 EUR for couples)
- **Vorabpauschale**: Pre-tax on accumulating ETFs

### Tax Dashboard

Go to **Tax** in the sidebar to see:
- Year-wise summary of gains and losses
- STCG vs LTCG breakdown
- Tax harvesting suggestions ("sell these losing stocks to save on tax")
- Holding period timer ("stock X becomes LTCG eligible in 45 days")
- Export tax report as PDF or Excel for your accountant

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

---

## Mutual Funds and Dividends

### Mutual Funds

- Add mutual fund holdings manually or import from your CAS (Consolidated Account Statement)
- NAV (Net Asset Value) updates daily from AMFI
- XIRR returns calculated automatically

### Dividends

- Record dividends received on each holding
- Track if dividends were reinvested (DRIP)
- Dividend calendar shows upcoming dividend dates
- Tax implications shown for each dividend

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

The page shows a donut chart breakdown by asset type and a total net worth figure.

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
5. Summary cards show total P&L, margin used, and open position count

---

## SIP Calendar

View all your recurring investments (SIPs), dividends, and earnings in one calendar.

1. Go to **SIP Calendar** from the sidebar
2. A monthly grid shows color-coded dots for each event type
3. SIP dates are auto-detected from recurring transaction patterns

---

## Settings and Configuration

### Display Settings

- **Theme**: Dark, Light, or System (follows your OS)
- **Currency**: INR, EUR, or USD
- **Table Density**: Compact, Comfortable, or Spacious
- **Default Chart Period**: 7 days, 30 days, 90 days, or 1 year

### Custom Columns

1. Go to **Settings** then **Display** then **Customize Columns**
2. Toggle built-in columns on/off (Sector, P&L Amount, Volume, Dividend Yield, etc.)
3. Click **+ Add Custom Column** to create your own (name and type: text, number, or date)
4. Drag columns to reorder them

### Data Backup

- **Export All Data**: Settings then Advanced then Export (creates a full backup)
- **Import Data**: Settings then Advanced then Import (restore from a backup)

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
