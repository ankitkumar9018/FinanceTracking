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

**Connectable today**: Zerodha (Kite Connect) and ICICI Direct (Breeze API) — these two adapters are fully implemented.

**Registered but not yet built** (the adapter returns HTTP 501 and the Brokers page shows a "coming soon" badge): Angel One (SmartAPI), Upstox, 5Paisa, Groww, Deutsche Bank, comdirect. Do not sign up for an API key for these expecting them to work.

**Groww** does not offer a public API at all; export your Groww data as CSV and import it instead.

Broker connections are optional, and they are used for **holdings/transaction sync only** — prices always come from yfinance either way. See [broker-integration.md](broker-integration.md) for the authoritative status table.

---

### 5. How does the app get real-time stock prices?

There is exactly one source: **yfinance** (free, no API key). A background job polls it every `PRICE_REFRESH_INTERVAL` minutes (default 5) and also once at startup, then pushes the new prices to open browsers over the `/ws/prices` WebSocket.

The prices are **not** real-time: NSE quotes via Yahoo are typically ~15 minutes delayed, and XETRA quotes are delayed as well. There is no broker price stream — connecting a broker syncs holdings and transactions, it does not change where prices come from.

If the fetch fails, the app shows the last cached price with a "stale" indicator and the timestamp of the last successful update.

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

No. Background jobs (price refresh, alert checks, the daily AI digest) run **in-process on APScheduler by default**, whether or not Redis is installed. Redis is used only for alert de-duplication/caching, and as the Celery broker if you deliberately opt into Celery with `USE_CELERY=true` — which also means running `celery worker --beat` yourself. Installing Redis on its own changes nothing about scheduling. For personal and desktop use, leave it alone.

---

### 11. Do I need Ollama for the AI features?

No. Ollama is optional. Without it, the AI chat assistant and AI-powered insights are disabled (you will see an "AI offline" banner). All other features -- portfolio tracking, charts, alerts, tax tracking, import/export -- work perfectly without any AI provider. The **portfolio digest** is the exception among the AI features: it still works with no model at all, falling back to a version built purely from your own computed numbers. If you want the rest, install Ollama (free, runs locally) and pull the Llama 3.2 model. You can also use OpenAI, Claude, or Gemini instead by entering your API key in Settings. If a local model is slow to answer, raise the backend `OLLAMA_TIMEOUT` setting (default 300 seconds).

---

### 12. What data formats can I import and export?

**Import** (from the **Import & Export** page in the sidebar, on its **Import** tab): Excel (.xlsx), CSV (holdings, dividends, mutual funds, and tax records — each with a downloadable template), a JSON portfolio backup, OFX/QFX broker or bank statements, QIF (Quicken) files, and CAMS/KFintech CAS PDFs for mutual funds. Column headings are matched flexibly, so both the template headers (`stock_symbol`, `price`) and the human-readable ones the app's own exports write (`Stock Symbol`, `Avg Price`) are understood; your file needs the symbol, exchange, quantity, and price, while the stock name, range levels, sector, and notes are optional. The file is parsed and imported in one step, and you can re-import updated files — the app merges new data with existing holdings and skips duplicate transactions. The maximum upload size is 10 MB.

**Export** (from the **Export** tab of the **Import & Export** page, or from the **Reports** page — both show the same list): holdings and transactions CSV, an Excel export and a multi-sheet Excel workbook (.xlsx), a JSON backup, HTML and PDF reports, a Google Sheets CSV, a SQLite database backup (desktop), a Capital Gains Tax Report (CSV/HTML, on the Reports page), and an "Export Everything" ZIP bundle that packages the CSVs, JSON, HTML report, Excel workbook, and PDF together.

**Which exports can be imported back?** The **JSON backup** is the recommended full-fidelity one — it restores everything. The **Transactions CSV** and the **Excel Export** (via its *Transactions* sheet) reproduce your ledger exactly. The **Holdings CSV**, the **Holdings** sheet, and the multi-sheet **Excel Workbook** carry no transaction type or date, so every row comes back as a single opening **BUY** at the exported average price, **dated today** — the quantities and averages are right, the original buy/sell history is not. Re-importing the same snapshot on the same day is de-duplicated; importing it on a later day adds a second opening BUY. HTML and PDF reports are read-only documents, and the SQLite backup is a database file you swap in rather than import.

---

### 13. How often are prices updated?

| Data | Update Frequency |
|---|---|
| Stock prices (yfinance) | Every `PRICE_REFRESH_INTERVAL` minutes (default 5), plus once at app startup |
| RSI calculation | Recomputed with every price refresh |
| Alert evaluation | Every `ALERT_CHECK_INTERVAL` seconds (default 60) |
| AI portfolio digest | Daily (per-user frequency: daily / weekly / off) |
| Mutual fund NAV | **On demand only** — press **Refresh** on the Mutual Funds page. There is no scheduled NAV job. |
| Forex rates | On demand, cached; a same-day rate is refetched after 1 hour |

The refresh interval is **not** editable in the app — the Settings page only displays it. Change it with `PRICE_REFRESH_INTERVAL` in `backend/.env` and restart the backend.

---

### 14. Can I use the app on my phone?

FinanceTracker is a Progressive Web App (PWA). When you access it from a mobile browser, you can "Add to Home Screen" to use it like a native app. It is fully responsive and works on screens from tablets to 4K monitors. A dedicated mobile app (iOS/Android) is not currently available, but the PWA provides a comparable experience.

---

### 15. What happens if I accidentally delete a holding?

Deleting a holding removes it and all its transactions from the database. This action cannot be undone from the UI. To protect against accidental data loss:

1. **Regular backups**: Use the **Export** tab of the **Import & Export** page (or the **Reports** page) and download the **JSON backup** — the only full-fidelity export
2. **Confirmation dialog**: The app asks you to confirm before any deletion
3. **Audit log**: All deletions are logged internally

If you have a recent JSON backup, restore it from the **Import** tab of the **Import & Export** page. (There is no Settings → Advanced panel; import and export live on their own page.)

---

### 16. Can I add custom columns to the holdings table?

Yes. Open the **Holdings** page and click the **Columns** button above the table (it opens a slide-over panel). You can:
- Hide or show the optional built-in columns: **P&L Amount, P&L %, Sector, Exchange, Day Change, Notes**. The other seven (Symbol, Name, Quantity, Avg Price, Current Price, Action, RSI) are fixed and cannot be hidden.
- Add your own custom columns with the **Add Column** form (a name, a display label, and a type: text, number, or date)
- Reorder columns with the up/down arrows next to each one

There is no Settings → Display → Customize Columns panel — column management lives on the Holdings page.

Custom column values are stored per holding in a JSON field and are preserved across imports.

---

### 17. How do I set up WhatsApp or Telegram notifications?

Credentials are **server-side settings**, not app settings. There is no screen in the app for pasting an API key or bot token — they go in `backend/.env` (or real environment variables) and take effect on the next backend restart.

**WhatsApp / SMS** — requires a Twilio account (free trial available). In `backend/.env`:

```bash
TWILIO_ACCOUNT_SID=ACxxxxxxxx
TWILIO_AUTH_TOKEN=xxxxxxxx
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886
TWILIO_SMS_FROM=+14155238886
```

Then in the app: **Settings → Notifications**, toggle *WhatsApp* and/or *SMS* on, enter your own phone number in E.164 form (`+9198XXXXXXXX`) in the field that appears, and **Save Changes**.

**Telegram** — create a bot with [@BotFather](https://t.me/BotFather) (free), then in `backend/.env`:

```bash
TELEGRAM_BOT_TOKEN=123456789:ABCdefGhIJklMNopQRSTuvWXYz
```

Then in the app: **Settings → Notifications**, toggle *Telegram* on and **type your Chat ID** into the field that appears. The app does **not** auto-detect it — get it by messaging your bot and opening `https://api.telegram.org/bot<TOKEN>/getUpdates`, or by messaging `@userinfobot`.

A **Test Email** / **Test Telegram** button appears in Settings once the corresponding server-side key is present. There is no Test button for WhatsApp or SMS.

---

### 18. Is there a limit to how many stocks I can track?

There is no hard limit. The app is designed to handle hundreds of holdings per portfolio efficiently. The portfolio table uses virtual scrolling for large lists, and the backend is async for concurrent data fetching. Performance will depend on your machine and the number of concurrent price fetches.

---

### 19. Can I use the app for mutual funds?

Yes. You can add mutual fund holdings manually (with scheme code, units, and invested amount) or import your Consolidated Account Statement (CAS) from CAMS or KFintech. NAV comes from mfapi.in (AMFI data) and is fetched **when you press Refresh on the Mutual Funds page** — there is no nightly NAV job, so a fund you have not refreshed shows the NAV from the last time you did. The app calculates XIRR returns and tracks SIP investments.

---

### 20. What data sources are used for stock prices?

| Data | Source | Fallback |
|---|---|---|
| Current prices | yfinance (free) — the only source | Last cached price, flagged stale |
| Historical OHLCV | yfinance (20+ years) | Last cached history |
| RSI and indicators | Calculated locally with pandas_ta | Manual Wilder-smoothed implementation |
| Mutual fund NAV | mfapi.in (AMFI data), on demand | Last stored NAV |
| Forex rates | yfinance `{FROM}{TO}=X` tickers (e.g. `EURINR=X`) | Cached rate from the `forex_rates` table |
| News/sentiment | RSS feeds (free) | - |

There is no ECB integration and no broker price feed; every quote and every FX rate comes from yfinance.

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

### 24. How do I download a tax report for filing?

Go to the **Reports** page and use the **Capital Gains Tax Report** card. Pick the financial year and jurisdiction (India or Germany), then download it as **CSV** or **HTML**. It is a consolidated, ITR-ready statement of your capital gains for that year -- per-transaction gains plus STCG/LTCG, tax, and exemption totals. Indian long-term gains use FIFO lot matching and the 31-January-2018 grandfathered cost basis; German figures apply Teilfreistellung and the Sparer-Pauschbetrag allowance automatically. See [tax-guide.md](tax-guide.md) for details.

---

### 25. What is the Stock Screener and what does it search?

The Screener (in the sidebar) filters a **curated universe of liquid stocks** -- major NSE and XETRA names -- by fundamentals and technicals. It is not a full-market scanner. Pick an exchange and set any combination of filters (market cap, P/E, dividend yield, price, RSI, 52-week position, day change, sector), then Run Screen to get a sortable table of matches. You can also add extra symbols to include in the scan.

---

### 26. How are stock splits and bonus issues handled?

Open the **Corporate Actions** page and click **Detect now**. The app scans your holdings against market data for splits and bonus issues and lists anything it finds under Pending review. Click **Apply** to adjust the holding automatically (quantity multiplied and average price divided by the ratio), or **Dismiss** to ignore it. Applied and dismissed actions are kept in a History list.

---

### 27. Can I view my totals in a different currency?

Yes. The **display-currency** dropdown in the top bar (INR / EUR / USD) converts the totals shown across the dashboard and Net Worth pages for viewing, using live forex rates. It is a viewing preference only -- it does not change how your holdings are stored or your account's base currency (set that in Settings).

---

### 28. I forgot my password -- how do I reset it?

On the login page, click **Forgot password?**, enter your account email, and click **Send reset link**. Open the link from the email you receive and choose a new password (at least 8 characters). For your security, the app always responds with "if that email exists, a reset link was sent," so it never reveals whether an email is registered. If you have Two-Factor Authentication enabled, you will still enter your authenticator code the next time you log in.

---

### 29. What can the AI assistant do?

Four things, and all of them are optional:

1. **Answer questions about your portfolio** in plain language, grounded in your real holdings and numbers. Needs a connected model (Ollama, OpenAI, Claude, or Gemini).
2. **Propose changes for you to confirm.** Ask it to record a transaction, add a holding, or create an alert and it will reply with a summary of exactly what it would do -- and then wait. **Nothing is executed until you confirm**; dismissing discards it. On confirmation the details are re-validated, ownership re-checked, and the change goes through the same code as manual entry, so the same guards apply. Proposals expire after 15 minutes and at most 5 can be pending in a conversation. Needs a connected model.
3. **Write a portfolio digest** -- totals, P&L, largest positions, gainers/losers, and concentration flags -- on demand or on a daily/weekly schedule delivered through your notification channels. **This one works with no AI model connected**, falling back to a digest built from your own computed numbers.
4. **Add short explanations** -- an optional AI summary at the top of the HTML/PDF report, and a one-sentence explanation on triggered alert notifications. Both are best-effort: the report still exports and the alert still arrives if AI is unavailable or slow.

What it cannot do: predict prices, or give you financial advice. Everything it writes is educational information to help you think, and it can be wrong -- check the numbers it quotes.

---

## Still Have Questions?

- Check the [Troubleshooting Guide](troubleshooting.md) for common issues
- Visit the in-app Help Center (click the ? button in the header)
- Open a GitHub issue for bugs or feature requests
