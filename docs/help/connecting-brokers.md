# Connecting Your Broker

This guide walks you through connecting your stock broker to FinanceTracker for automatic portfolio syncing.

---

## Which brokers actually work today

Only **two** adapters are implemented. The rest are registered so they appear in the list, but every operation returns HTTP 501 and the app shows a **coming soon** badge — clicking Connect just tells you the integration is not available yet.

| Broker | Country | Status |
|---|---|---|
| **Zerodha** (Kite Connect) | India | **Connectable** |
| **ICICI Direct** (Breeze) | India | **Connectable** |
| Angel One (SmartAPI) | India | Coming soon — not implemented |
| Upstox | India | Coming soon — not implemented |
| 5Paisa | India | Coming soon — not implemented |
| Groww | India | Coming soon (no public API exists) |
| Deutsche Bank | Germany | Coming soon — not implemented |
| comdirect | Germany | Coming soon — not implemented |

Do not register for an API key with a "coming soon" broker expecting it to work here.

---

## Why Connect a Broker?

- **Automatic portfolio sync**: your holdings are imported instead of typed in
- **No manual entry**: saves time on data entry

**Prices are not part of the deal.** Every price in FinanceTracker comes from yfinance polling, whether or not a broker is connected. There is no broker price stream and no sub-second data — NSE quotes via Yahoo are typically ~15 minutes delayed.

**Important**: connecting a broker is completely optional. The app works fully with manual entry and Excel import.

---

## Before You Start

You will need:
1. An active trading account with **Zerodha** or **ICICI Direct**
2. API credentials from that broker (API key and secret)
3. Both brokers require you to register for API access separately (usually free or included with your trading plan)

---

## Zerodha (Kite Connect)

### Step 1: Get API Credentials

1. Go to https://developers.kite.trade/
2. Sign in with your Zerodha account
3. Click **Create New App**
4. Fill in the app details:
   - App name: FinanceTracker (or any name you like)
   - Redirect URL: your app address, e.g. `http://localhost:3000` (Zerodha
     sends you back here with a `request_token` in the address bar after login)
5. Note down your **API Key** and **API Secret**

### Step 2: Connect in FinanceTracker

1. Open **Brokers** in the sidebar and click **Connect** on the Zerodha card
2. Enter your API Key and API Secret and click **Connect**
3. The app opens the Zerodha login page (via the `login_url` it returns)
4. Log in with your Zerodha credentials and authorize the app
5. Zerodha redirects you to your redirect URL with `?request_token=...` in the
   address — copy that `request_token`
6. Paste the `request_token` back into the FinanceTracker connect dialog to
   finish. (FinanceTracker has no server-side OAuth callback; you complete the
   connection by pasting the token.)

### Step 3: Sync Your Data

After connecting, click **Sync** to fetch your holdings. The app will:
- Import all your demat holdings into the selected portfolio
- Price them from yfinance like every other holding
- You then set range levels for each imported stock yourself

### Daily Re-authentication

Zerodha access tokens expire every day at 6 AM IST, so a **Sync** the next day fails until you click **Reconnect** and repeat the login. Nothing else breaks: your holdings and prices are unaffected, because prices never came from the broker.

---

## ICICI Direct (Breeze API)

### Step 1: Get API Credentials

1. Go to https://api.icicidirect.com/
2. Register for API access
3. Create an app to get your **App Key** and **Secret Key**
4. Set the redirect URL to your app address, e.g. `http://localhost:3000` (you
   complete the connection in-app; there is no server-side callback endpoint)

### Step 2: Connect in FinanceTracker

1. Open **Brokers** in the sidebar and click **Connect** on the ICICI Direct card
2. Enter your App Key and Secret Key
3. Click **Connect**
4. Log in on the ICICI Direct page
5. Authorize and return to FinanceTracker

### Notes

- Holdings sync covers your demat holdings
- Charts and prices in the app still come from yfinance, not from Breeze

---

## Brokers that are not implemented yet

**Angel One, Upstox, 5Paisa, Groww, Deutsche Bank and comdirect** appear on the Brokers page with a **coming soon** badge. Their adapters are registered placeholders: every call — connect, sync, holdings, positions, orders, history — raises `NotImplementedError`, which the API returns as **HTTP 501**. Clicking Connect on one of them shows "…integration is not available yet" and nothing happens.

There is nothing to configure, no credentials to obtain, and no partial support. Until an adapter is actually written:

- Use **Excel/CSV import** or manual entry for these brokers
- Groww in particular has **no public API at all** — export your Groww data as CSV and import it
- For German brokers, a PSD2/Open-Banking flow is a design intention, not shipped code

Progress is tracked in [broker-integration.md](../broker-integration.md), which is the authoritative status table.

---

## After Connecting

### What Gets Synced

| Data | Synced? | Notes |
|---|---|---|
| Holdings (stocks you own) | Yes | Quantity, average price, current price |
| Recent transactions | Yes | Buys and sells from the last 30 days |
| Current prices | No | Prices always come from yfinance polling, connected or not |
| Price range levels | No | These are your personal settings -- never overwritten |
| Custom fields | No | Your custom data is preserved |
| Notes | No | Your notes on each stock are preserved |

### Handling Conflicts

If you already have a stock in your portfolio (from manual entry or Excel import) and the broker also has it:
- The **quantity and average price** are updated to match the broker (the broker is the source of truth for what you actually own)
- Your **range levels, notes, and custom fields** are never changed by the sync
- **Manual transactions** are preserved alongside broker-synced transactions

### Disconnecting

To disconnect a broker:
1. Open **Brokers** in the sidebar
2. Click **Disconnect** next to the broker
3. Your portfolio data is preserved (only the connection is removed)
4. Prices are unaffected — they were coming from yfinance all along

All encrypted API credentials are permanently deleted from the database when you disconnect.

---

## Troubleshooting

**"Token expired" message**: Re-authenticate by clicking Reconnect (normal for Zerodha, which expires daily)

**"No holdings found"**: Make sure you have delivery holdings (not just intraday positions) in your broker account

**"OAuth redirect error"**: Verify that the redirect URL in your broker's developer settings exactly matches the address you actually return to (e.g. `http://localhost:3000`)

---

Need more help? Check the [FAQ](../faq.md) or the [Troubleshooting Guide](../troubleshooting.md).
