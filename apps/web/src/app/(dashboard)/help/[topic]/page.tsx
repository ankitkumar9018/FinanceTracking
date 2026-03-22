import { notFound } from "next/navigation";

const HELP_CONTENT: Record<string, { title: string; content: string }> = {
  "getting-started": {
    title: "Getting Started",
    content: `
## Welcome to FinanceTracker

FinanceTracker helps you monitor your investment portfolio across Indian and German markets.

### Quick Start
1. **Register** an account with your email
2. **Import** your existing portfolio from Excel, or add stocks manually
3. **Set up alerts** by configuring range levels for each holding
4. **Monitor** your dashboard for real-time price updates and action signals

### Understanding the Dashboard
The main dashboard shows your portfolio table with columns:
- **Stock**: Symbol and exchange
- **Quantity**: Cumulative holdings
- **Avg Price**: Weighted average purchase price
- **Current Price**: Real-time market price
- **P&L %**: Profit/Loss percentage
- **Action**: Color-coded signal (click for price chart)
- **RSI**: Relative Strength Index (click for RSI chart)
    `,
  },
  "understanding-alerts": {
    title: "Understanding Alerts",
    content: `
## What Do the Colors Mean?

FinanceTracker uses a 5-zone color system to signal when action may be needed:

### Neutral (Gray) — "N"
The stock price is not in any of your defined ranges. No action needed.

### Light Red — Lower Mid Range
Price is between your Lower Mid Range 1 and Lower Mid Range 2. This might be a buying opportunity as the price approaches your target zone.

### Dark Red — Below Base Level
Price has dropped below your base level. This could signal a strong buying opportunity or a stop-loss trigger, depending on your strategy.

### Light Green — Upper Mid Range
Price is between your Upper Mid Range 1 and Upper Mid Range 2. Consider taking partial profits.

### Dark Green — Above Top Level
Price has exceeded your top level target. This is typically a strong sell signal.

### Setting Up Ranges
For each holding, you can set:
- **Base Level**: Lowest acceptable price
- **Lower Mid Range 1 & 2**: Buy zone boundaries
- **Upper Mid Range 1 & 2**: Sell zone boundaries
- **Top Level**: Highest target price
    `,
  },
  "importing-data": {
    title: "Importing Your Data",
    content: `
## How to Import from Excel

### Step 1: Prepare Your File
Create an Excel file (.xlsx) with these columns:
- Stock Name, Exchange, Date, Quantity, Price, Type (BUY/SELL)
- Base Level, Top Level, Lower Mid 1, Lower Mid 2, Upper Mid 1, Upper Mid 2

### Step 2: Upload
Go to the **Import** page and drag-and-drop your file, or click to browse.

### Step 3: Review
The system will validate your data and show a preview. Fix any errors and confirm.

### Re-Importing
If you import again with the same stocks, existing holdings will be updated (not duplicated).
    `,
  },
  "reading-charts": {
    title: "Reading Charts",
    content: `
## Understanding Price Charts

### Candlestick Charts
Each "candle" represents one trading day:
- **Green candle**: Price went UP (close > open)
- **Red candle**: Price went DOWN (close < open)
- **Body**: Range between open and close
- **Wicks**: High and low of the day

### RSI (Relative Strength Index)
RSI measures momentum on a 0-100 scale:
- **Below 30**: Oversold — stock may be undervalued (potential buy)
- **30-70**: Neutral — normal trading range
- **Above 70**: Overbought — stock may be overvalued (potential sell)

### Interacting with Charts
- Click the **Action** cell in the portfolio table to see a 30-day price chart
- Click the **RSI** cell to see the RSI movement chart
- Use the time range buttons (7D, 30D, 90D, 1Y) to change the chart period
    `,
  },
  "managing-goals": {
    title: "Managing Goals",
    content: `
## Investment Goals

Set financial goals and track progress toward them.

### Creating a Goal
1. Name your goal (e.g., "Retirement Fund", "House Down Payment")
2. Set a target amount
3. Set a target date
4. Link one or more portfolios

### Tracking Progress
The dashboard shows animated progress gauges for each goal, including how much monthly SIP you need to stay on track.
    `,
  },
  "using-ai-assistant": {
    title: "Using the AI Assistant",
    content: `
## AI-Powered Portfolio Assistant

Ask questions about your portfolio in plain English.

### Example Questions
- "What's my best performing stock this month?"
- "Should I sell RELIANCE based on RSI?"
- "How much LTCG tax will I owe this year?"
- "Which stocks are near their 52-week high?"

### AI Providers
By default, FinanceTracker uses **Ollama with Llama 3.2** (local, free, private). You can optionally configure OpenAI, Claude, or Gemini in Settings.

### When AI is Offline
If no AI provider is available, the chat shows "AI assistant offline". All other features continue working normally.
    `,
  },
  "connecting-brokers": {
    title: "Connecting Brokers",
    content: `
## Broker Integration

Connect your trading account to automatically sync holdings, transactions, and live prices.

### Supported Brokers
- **Zerodha (Kite Connect)** — India's largest discount broker
- **ICICI Direct (Breeze)** — Full-service broker with rich data
- **Groww** — Popular for mutual funds and stocks
- **Angel One (SmartAPI)** — Low-cost broker
- **Upstox** — Fast execution, modern API
- **Deutsche Bank** — German market access
- **Comdirect** — German retail broker

### How to Connect
1. Go to **Brokers** in the sidebar
2. Click **Connect** next to your broker
3. Enter your API credentials (API key + secret)
4. Authorize the connection via the broker's OAuth page
5. Your holdings will sync automatically

### Where to Get API Keys
- **Zerodha**: Visit kite.trade → Developer → Create App
- **ICICI Direct**: Visit Breeze portal → API Management
- **Angel One**: Visit SmartAPI portal → Create App

### Security
- All API keys are encrypted at rest (AES-256)
- Keys are never exposed in the UI after saving
- You can disconnect at any time from the Brokers page
    `,
  },
  "tax-features": {
    title: "Tax Features",
    content: `
## Tax Tracking

FinanceTracker automatically calculates tax liability for Indian and German markets.

### Indian Tax Rules
- **STCG (Short Term Capital Gains)**: Stocks held < 12 months → taxed at 20%
- **LTCG (Long Term Capital Gains)**: Stocks held > 12 months → taxed at 12.5% (above ₹1.25 lakh exemption per financial year)
- Financial year runs April to March

### German Tax Rules
- **Abgeltungssteuer**: Flat 26.375% (25% + 5.5% solidarity surcharge)
- **Freibetrag**: €1,000 annual exemption (€2,000 for joint filing)
- Optional church tax (8-9% on top)

### Tax Harvesting
The system suggests stocks to sell before March 31 to utilize your LTCG exemption:
- Go to **Tax** page → **Harvesting Suggestions** tab
- Shows potential tax savings from strategic selling

### Tax Reports
- Go to **Reports** → **Tax Report**
- Download STCG/LTCG breakdown by financial year
- Use for ITR filing or share with your CA
    `,
  },
  "notifications-setup": {
    title: "Setting Up Notifications",
    content: `
## Notification Channels

Get alerted when your stocks hit price targets via multiple channels.

### Available Channels
- **In-App**: Toast notifications + notification history (always on)
- **Email**: Daily summaries and critical alerts via SendGrid
- **Telegram**: Instant alerts via Telegram bot
- **WhatsApp**: Alerts via Twilio WhatsApp API
- **SMS**: Critical alerts via Twilio SMS

### Setting Up Email
1. Go to **Settings** → **Notifications** → **Email**
2. Enter your SendGrid API key
3. Set your "From" email address
4. Click **Test** to send a test notification

### Setting Up Telegram
1. Go to **Settings** → **Notifications** → **Telegram**
2. Create a bot via @BotFather on Telegram
3. Enter the bot token
4. Send /start to your bot to get your chat ID
5. Click **Test** to verify

### Setting Up WhatsApp
1. Go to **Settings** → **Notifications** → **WhatsApp**
2. Enter your Twilio Account SID and Auth Token
3. Set the Twilio WhatsApp number
4. Click **Test** to send a test message

### Alert Routing
Critical alerts (base level breach, top level breach) are sent to all channels. Routine alerts (mid-range) go to email and in-app only. You can customize this in Settings.
    `,
  },
  glossary: {
    title: "Financial Glossary",
    content: `
## Key Terms Explained

### Portfolio & Holdings
- **Holding**: A stock you own in your portfolio
- **Cumulative Quantity**: Total shares held after all buys and sells
- **Average Price**: Weighted average purchase price across all buy transactions
- **P&L (Profit & Loss)**: Difference between current value and invested value

### Technical Indicators
- **RSI (Relative Strength Index)**: Momentum indicator (0-100). Below 30 = oversold (potential buy), above 70 = overbought (potential sell)
- **MACD**: Moving Average Convergence Divergence — trend-following momentum indicator
- **Bollinger Bands**: Volatility bands above and below a moving average
- **SMA/EMA**: Simple/Exponential Moving Average — smoothed price trends

### Alert Zones
- **Base Level**: Lowest acceptable price (−10% default from avg price)
- **Lower Mid Range**: Buy zone boundaries (−5% to −7.5% default)
- **Upper Mid Range**: Sell zone boundaries (+5% to +7.5% default)
- **Top Level**: Highest target price (+10% default from avg price)

### Risk Metrics
- **Sharpe Ratio**: Risk-adjusted return. Above 1.5 = excellent, 0.5-1.5 = moderate
- **Sortino Ratio**: Like Sharpe but only considers downside risk
- **Max Drawdown**: Largest peak-to-trough decline in portfolio value
- **VaR (Value at Risk)**: Maximum expected loss at 95% confidence
- **Beta**: How much a stock moves relative to the market index

### Tax Terms
- **STCG**: Short Term Capital Gains (held < 12 months in India)
- **LTCG**: Long Term Capital Gains (held > 12 months in India)
- **XIRR**: Extended Internal Rate of Return — true annualized return accounting for cash flows
- **Abgeltungssteuer**: German flat tax on capital gains (26.375%)
- **Freibetrag**: German annual tax-free allowance (€1,000)

### Other
- **NAV**: Net Asset Value — per-unit price of a mutual fund
- **DRIP**: Dividend Reinvestment Plan — automatically buy more shares with dividends
- **SIP**: Systematic Investment Plan — regular periodic investment
- **ESG**: Environmental, Social, and Governance — sustainability scoring
    `,
  },
};

export function generateStaticParams() {
  return Object.keys(HELP_CONTENT).map((topic) => ({ topic }));
}

export default async function HelpTopicPage({ params }: { params: Promise<{ topic: string }> }) {
  const { topic } = await params;
  const article = HELP_CONTENT[topic];

  if (!article) notFound();

  return (
    <div className="mx-auto max-w-3xl">
      <article className="prose prose-sm dark:prose-invert max-w-none">
        <h1>{article.title}</h1>
        <div dangerouslySetInnerHTML={{ __html: simpleMarkdown(article.content) }} />
      </article>
    </div>
  );
}

function simpleMarkdown(md: string): string {
  return md
    .replace(/^### (.+)$/gm, '<h3 class="text-lg font-semibold mt-6 mb-2">$1</h3>')
    .replace(/^## (.+)$/gm, '<h2 class="text-xl font-bold mt-8 mb-3">$1</h2>')
    .replace(/^\- \*\*(.+?)\*\*: (.+)$/gm, '<li class="ml-4 mb-1"><strong>$1</strong>: $2</li>')
    .replace(/^\- (.+)$/gm, '<li class="ml-4 mb-1">$1</li>')
    .replace(/^\d+\. \*\*(.+?)\*\* (.+)$/gm, '<li class="ml-4 mb-1"><strong>$1</strong> $2</li>')
    .replace(/^\d+\. (.+)$/gm, '<li class="ml-4 mb-1">$1</li>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\n\n/g, '<br/><br/>');
}
