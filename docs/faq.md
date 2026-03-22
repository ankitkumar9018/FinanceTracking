# Frequently Asked Questions

> FinanceTracker -- Common Questions Answered

---

### 1. Do I need to be a programmer to use FinanceTracker?

No. FinanceTracker is designed for non-technical users. You can import your portfolio from Excel, add stocks manually from the dashboard, and configure everything through the visual Settings page. No command line or coding is required for day-to-day use. The only technical step is the initial installation, which is covered by a setup script.

---

### 2. Is my financial data safe?

Yes. All your data is stored locally on your machine by default (in a SQLite database file). Sensitive information like broker API keys is encrypted using Fernet symmetric encryption. Passwords are hashed with bcrypt and cannot be reversed. If you deploy to a server, all data is transmitted over HTTPS. See [security.md](security.md) for full details.

---

### 3. Does the app work without an internet connection?

Partially. The desktop app caches your last known portfolio state, so you can view your holdings and transaction history offline. However, real-time prices, news, and broker syncing require an internet connection. When you come back online, data syncs automatically. You can also add manual transactions and edit range levels while offline.

---

### 4. Which brokers are supported?

**Indian brokers**: Zerodha (Kite Connect), ICICI Direct (Breeze API), Angel One (SmartAPI), Upstox, 5Paisa.
**German brokers**: Deutsche Bank and comdirect via PSD2/Open Banking.
**Groww**: Does not offer a public API; you can export your Groww data as CSV and import it.

Broker connections are optional. The app works fully without any broker by using manual entry and yfinance for price data.

---

### 5. How does the app get real-time stock prices?

There are two methods, used in priority order:

1. **Broker WebSocket** (if connected): Real-time streaming with less than 1 second latency. Available with Zerodha, ICICI Direct, Angel One, and Upstox.
2. **yfinance** (free, no API key): Polls prices every 5 minutes. NSE prices may have a 15-minute delay. XETRA prices are typically delayed as well.

If both fail, the app shows the last cached price with a "stale" indicator and the timestamp of the last update.

---

### 6. What do the colors in the portfolio table mean?

| Color | Meaning |
|---|---|
| No color | Price is in the normal range. No action needed. |
| Light red | Price entered the lower mid range (between your lower mid range 2 and lower mid range 1). This is a caution zone. |
| Dark red | Price is at or below your base level. This is a critical zone. |
| Light green | Price entered the upper mid range (between your upper mid range 1 and upper mid range 2). This is an opportunity zone. |
| Dark green | Price is at or above your top level. Your target has been reached. |

See [help/understanding-alerts.md](help/understanding-alerts.md) for a detailed explanation.

---

### 7. What is RSI and why should I care about it?

RSI (Relative Strength Index) is a momentum indicator that measures how fast and how much a stock's price has been moving. It ranges from 0 to 100:

- **Below 30**: The stock may be "oversold" (it has fallen a lot recently and might bounce back)
- **Above 70**: The stock may be "overbought" (it has risen a lot recently and might pull back)
- **Between 30 and 70**: Normal range

FinanceTracker calculates RSI-14 (14-day RSI) for every holding and displays it in the portfolio table. Click the RSI value to see a chart of how it has moved over time.

---

### 8. Can I track both Indian and German stocks in the same portfolio?

Yes, but it is recommended to create separate portfolios for each market (e.g., "Indian Stocks" in INR and "German Stocks" in EUR). This keeps the currency and tax calculations clean. The dashboard shows a consolidated view across all portfolios, automatically converting to your preferred currency using live forex rates.

---

### 9. How does tax tracking work?

FinanceTracker automatically classifies your gains based on holding period and jurisdiction:

- **India**: STCG (< 12 months, taxed at 20%) vs LTCG (>= 12 months, taxed at 12.5% above 1.25 lakh exemption)
- **Germany**: Abgeltungssteuer (26.375% flat tax with 1,000 EUR annual exemption)

The app also suggests tax harvesting opportunities and warns you when a stock is close to becoming eligible for lower long-term tax rates. See [tax-guide.md](tax-guide.md) for full details.

---

### 10. Do I need Redis installed?

No. Redis is optional. It is used for the background task queue (Celery) which handles periodic price fetching and alert checking. If Redis is not installed, the app falls back to running these tasks inside the main process using asyncio. This works perfectly for personal use. Redis is recommended if you want reliable background processing or if you plan to run the app on a server.

---

### 11. Do I need Ollama for the AI features?

No. Ollama is optional. Without it, the AI chat assistant and AI-powered insights are disabled (you will see an "AI offline" banner). All other features -- portfolio tracking, charts, alerts, tax tracking, import/export -- work perfectly without any AI provider. If you want AI features, install Ollama (free, runs locally) and pull the Llama 3.2 model. You can also use OpenAI, Claude, or Gemini instead by entering your API key in Settings.

---

### 12. Can I import data from my existing Excel spreadsheet?

Yes. The import feature accepts .xlsx files and automatically maps columns. Your spreadsheet should have columns for stock name, purchase date, quantity, and price. Range levels (base, mid ranges, top) and sale data are optional. The app shows a preview of the parsed data before importing, so you can verify everything is correct. You can re-import updated spreadsheets; the app merges new data with existing holdings.

---

### 13. How often are prices updated?

| Source | Update Frequency |
|---|---|
| Broker WebSocket (connected) | Real-time (< 1 second) |
| yfinance (no broker) | Every 5 minutes during market hours |
| RSI calculation | After every price update |
| Mutual fund NAV | Daily after 11 PM IST |
| Forex rates | Daily from ECB |

You can configure the price refresh interval in Settings under Market Data.

---

### 14. Can I use the app on my phone?

FinanceTracker is a Progressive Web App (PWA). When you access it from a mobile browser, you can "Add to Home Screen" to use it like a native app. It is fully responsive and works on screens from tablets to 4K monitors. A dedicated mobile app (iOS/Android) is not currently available, but the PWA provides a comparable experience.

---

### 15. What happens if I accidentally delete a holding?

Deleting a holding removes it and all its transactions from the database. This action cannot be undone from the UI. To protect against accidental data loss:

1. **Regular backups**: Use Settings -> Advanced -> Export to create a full backup
2. **Confirmation dialog**: The app asks you to confirm before any deletion
3. **Audit log**: All deletions are logged internally

If you have a recent backup, you can restore it from Settings -> Advanced -> Import.

---

### 16. Can I add custom columns to the holdings table?

Yes. Go to Settings -> Display -> Customize Columns. You can:
- Toggle built-in optional columns on/off (Sector, P&L Amount, 52-Week High/Low, Market Cap, Volume, Dividend Yield, Notes)
- Add your own custom columns with a name and type (text, number, or date)
- Drag and drop columns to reorder them

Custom column values are stored per holding in a JSON field and are preserved across imports.

---

### 17. How do I set up WhatsApp or Telegram notifications?

**WhatsApp**: Requires a Twilio account (they offer a free trial with WhatsApp). Enter your Twilio Account SID, Auth Token, and WhatsApp-enabled phone number in Settings -> Notifications -> WhatsApp.

**Telegram**: Create a bot using @BotFather on Telegram (free). Enter the bot token in Settings -> Notifications -> Telegram. Message your bot once, and the app will auto-detect your Chat ID.

Both channels offer a "Test" button to verify the setup before enabling alerts.

---

### 18. Is there a limit to how many stocks I can track?

There is no hard limit. The app is designed to handle hundreds of holdings per portfolio efficiently. The portfolio table uses virtual scrolling for large lists, and the backend is async for concurrent data fetching. Performance will depend on your machine and the number of concurrent price fetches.

---

### 19. Can I use the app for mutual funds?

Yes. You can add mutual fund holdings manually (with scheme code, units, and invested amount) or import your Consolidated Account Statement (CAS) from CAMS or KFintech. NAV data is fetched daily from AMFI. The app calculates XIRR returns and tracks SIP investments.

---

### 20. What data sources are used for stock prices?

| Data | Primary Source | Fallback |
|---|---|---|
| Current prices | Broker API (if connected) | yfinance (free) |
| Historical OHLCV | yfinance (20+ years) | Broker API |
| RSI and indicators | Calculated locally with pandas_ta | - |
| Mutual fund NAV | AMFI via mftool | MFapi.in |
| Forex rates | ECB (free) | yfinance (EURINR=X) |
| News/sentiment | RSS feeds (free) | - |

All price data is cached locally, so the app continues to work even if an external source is temporarily unavailable.

---

### 21. Is there a desktop app?

Yes. FinanceTracker ships as a native desktop app for macOS, Windows, and Linux built with Tauri v2. Pre-built installers are available on the GitHub Releases page:

| Platform | Format |
|---|---|
| macOS (Apple Silicon + Intel) | `.dmg` |
| Windows (x64 + ARM64) | `.msi` or `.exe` |
| Linux (x64) | `.AppImage` or `.deb` |

The desktop app bundles everything — no Python, Node.js, or other dependencies needed on the target machine. It stores data locally in a SQLite database and works offline for viewing your portfolio. See [desktop-app.md](desktop-app.md) for build instructions if you want to build from source.

---

### 22. Can I build the desktop app on Windows?

Yes. Run `build-installer.bat` from the project root. It checks prerequisites (Node.js 20+, pnpm, Python 3.12+, uv, Rust), installs dependencies, builds the PyInstaller sidecar binary, exports the static frontend, and produces a `.msi` + `.exe` installer. The full process takes 5-15 minutes depending on your machine. See [desktop-app.md](desktop-app.md) for the detailed step-by-step guide.

---

### 23. Where does the desktop app store my data?

The SQLite database is stored in your OS app data directory:

| Platform | Path |
|---|---|
| macOS | `~/Library/Application Support/com.financetracker.app/finance.db` |
| Windows | `C:\Users\<user>\AppData\Local\com.financetracker.app\finance.db` |
| Linux | `~/.local/share/com.financetracker.app/finance.db` |

You can back up this file at any time by copying it.

---

## Still Have Questions?

- Check the [Troubleshooting Guide](troubleshooting.md) for common issues
- Visit the in-app Help Center (click the ? button in the header)
- Open a GitHub issue for bugs or feature requests
