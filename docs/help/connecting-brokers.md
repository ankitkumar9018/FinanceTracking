# Connecting Your Broker

This guide walks you through connecting your stock broker to FinanceTracker for automatic portfolio syncing and real-time prices.

---

## Why Connect a Broker?

Connecting a broker provides several benefits:
- **Automatic portfolio sync**: Your holdings and transactions are imported automatically
- **Real-time prices**: Get live price updates with less than 1 second delay (instead of 15-minute delayed data from yfinance)
- **Transaction history**: New buys and sells appear automatically
- **No manual entry**: Save time on data entry

**Important**: Connecting a broker is completely optional. The app works perfectly with manual entry and Excel import.

---

## Before You Start

You will need:
1. An active trading account with a supported broker
2. API credentials from your broker (API key and secret)
3. Most brokers require you to register for API access separately (usually free or included with your trading plan)

---

## Zerodha (Kite Connect)

### Step 1: Get API Credentials

1. Go to https://developers.kite.trade/
2. Sign in with your Zerodha account
3. Click **Create New App**
4. Fill in the app details:
   - App name: FinanceTracker (or any name you like)
   - Redirect URL: `http://localhost:8000/api/v1/brokers/zerodha/callback`
5. Note down your **API Key** and **API Secret**

### Step 2: Connect in FinanceTracker

1. Go to **Settings** then **Brokers** then **Zerodha**
2. Enter your API Key and API Secret
3. Click **Connect**
4. You will be redirected to the Zerodha login page
5. Log in with your Zerodha credentials (Client ID and password)
6. Authorize the app
7. You will be redirected back to FinanceTracker

### Step 3: Sync Your Data

After connecting, click **Sync Now** to fetch your holdings. The app will:
- Import all your demat holdings
- Fetch current prices via live streaming
- You can then set range levels for each imported stock

### Daily Re-authentication

Zerodha access tokens expire every day at 6 AM IST. You will need to click **Reconnect** each day if you want real-time streaming. Your holdings data is cached, so the app still shows your portfolio even when the token expires.

---

## ICICI Direct (Breeze API)

### Step 1: Get API Credentials

1. Go to https://api.icicidirect.com/
2. Register for API access
3. Create an app to get your **App Key** and **Secret Key**
4. Set the redirect URL to: `http://localhost:8000/api/v1/brokers/icici_direct/callback`

### Step 2: Connect in FinanceTracker

1. Go to **Settings** then **Brokers** then **ICICI Direct**
2. Enter your App Key and Secret Key
3. Click **Connect**
4. Log in on the ICICI Direct page
5. Authorize and return to FinanceTracker

### Highlights

- ICICI Direct provides up to 10 years of historical data
- 1-second OHLCV resolution for very detailed charts
- Holdings sync includes demat holdings and mutual funds

---

## Angel One (SmartAPI)

### Step 1: Get API Credentials

1. Go to https://smartapi.angelbroking.com/
2. Register with your Angel One account
3. Create an app and get your **API Key**
4. You will also need your **Client ID** and **TOTP secret** (from your Angel One app)

### Step 2: Connect in FinanceTracker

1. Go to **Settings** then **Brokers** then **Angel One**
2. Enter your API Key, Client ID, and TOTP secret
3. Click **Connect**
4. The app will authenticate using your credentials

### Note

Angel One uses TOTP (time-based one-time password) for authentication, which the app handles automatically using your TOTP secret.

---

## Upstox

### Step 1: Get API Credentials

1. Go to https://upstox.com/developer/api-documentation/
2. Create a developer account
3. Create an app to get your **API Key** and **API Secret**
4. Set the redirect URL

### Step 2: Connect in FinanceTracker

1. Go to **Settings** then **Brokers** then **Upstox**
2. Enter your credentials
3. Complete the OAuth flow (similar to Zerodha)

---

## 5Paisa

### Step 1: Get API Credentials

1. Go to https://www.5paisa.com/developerapi
2. Register for developer access
3. Create an app and get your credentials

### Step 2: Connect in FinanceTracker

Same pattern as above: enter credentials in Settings, complete the login flow.

---

## German Brokers

### Deutsche Bank

Deutsche Bank uses PSD2 Open Banking, which is a European regulation that allows third-party apps to access your bank data with your permission.

1. Go to **Settings** then **Brokers** then **Deutsche Bank**
2. Click **Connect**
3. You will be redirected to the Deutsche Bank login page
4. Log in with your online banking credentials
5. Grant consent for account access (valid for 90 days)
6. Return to FinanceTracker

**Note**: PSD2 consent must be renewed every 90 days. The app will remind you when renewal is needed.

### comdirect

Similar PSD2 flow as Deutsche Bank:

1. Go to **Settings** then **Brokers** then **comdirect**
2. Click **Connect**
3. Log in on the comdirect page
4. Complete the TAN challenge (photoTAN or pushTAN)
5. Grant consent and return

comdirect also provides access to your securities depot (portfolio of stocks and funds).

---

## After Connecting

### What Gets Synced

| Data | Synced? | Notes |
|---|---|---|
| Holdings (stocks you own) | Yes | Quantity, average price, current price |
| Recent transactions | Yes | Buys and sells from the last 30 days |
| Current prices | Yes | Real-time or near-real-time |
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
1. Go to **Settings** then **Brokers**
2. Click **Disconnect** next to the broker
3. Your portfolio data is preserved (only the live connection is removed)
4. Prices will fall back to yfinance updates

All encrypted API credentials are permanently deleted from the database when you disconnect.

---

## Troubleshooting

**"Token expired" message**: Re-authenticate by clicking Reconnect (normal for Zerodha, which expires daily)

**"No holdings found"**: Make sure you have delivery holdings (not just intraday positions) in your broker account

**"OAuth redirect error"**: Verify that the redirect URL in your broker's developer settings exactly matches the one shown in FinanceTracker's Settings

---

Need more help? Check the [FAQ](../faq.md) or the [Troubleshooting Guide](../troubleshooting.md).
