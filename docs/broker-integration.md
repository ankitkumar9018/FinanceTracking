# Broker Integration Guide

> FinanceTracker -- Connecting to Indian & German Brokers

## Overview

FinanceTracker connects to stock brokers to automatically sync your holdings, transactions, and real-time prices. All broker integrations follow an abstract adapter pattern, making it straightforward to add new brokers.

Broker connections are **optional**. The app works fully without any broker by using manual entry and yfinance for price data.

### Implementation Status

| Broker | Country | Status | File |
|---|---|---|---|
| **Zerodha** (Kite Connect) | India | Fully implemented | `brokers/zerodha.py` |
| **ICICI Direct** (Breeze) | India | Fully implemented | `brokers/icici_direct.py` |
| **Angel One** (SmartAPI) | India | Stub (coming soon) | `brokers/angel_one.py` |
| **Upstox** | India | Stub (coming soon) | `brokers/upstox.py` |
| **5Paisa** | India | Stub (coming soon) | `brokers/fivepaisa.py` |
| **Groww** | India | Stub (no public API) | `brokers/groww.py` |
| **Deutsche Bank** | Germany | Stub (coming soon) | `brokers/german/deutsche_bank.py` |
| **comdirect** | Germany | Stub (coming soon) | `brokers/german/comdirect.py` |

Stub brokers are registered in the broker registry and return HTTP 501 with "coming soon" status in the API. The frontend displays them as unavailable with a "coming soon" badge.

---

## Abstract BrokerAdapter Pattern

All broker integrations implement a common interface defined in `backend/app/brokers/base.py`:

```python
from abc import ABC, abstractmethod
from typing import Optional
from datetime import datetime, date

class BrokerAdapter(ABC):
    """Abstract base class for all broker integrations."""

    @abstractmethod
    async def connect(self, api_key: str, api_secret: str, **kwargs) -> bool:
        """Establish connection and authenticate with the broker."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Revoke tokens and clean up connection."""
        ...

    @abstractmethod
    async def get_auth_url(self) -> str:
        """Return the OAuth authorization URL for user consent."""
        ...

    @abstractmethod
    async def handle_callback(self, request_token: str) -> dict:
        """Process OAuth callback and store access token."""
        ...

    @abstractmethod
    async def get_holdings(self) -> list[HoldingData]:
        """Fetch current demat holdings."""
        ...

    @abstractmethod
    async def get_positions(self) -> list[PositionData]:
        """Fetch open intraday/delivery positions."""
        ...

    @abstractmethod
    async def get_orders(self, from_date: date, to_date: date) -> list[OrderData]:
        """Fetch order history for a date range."""
        ...

    @abstractmethod
    async def get_historical_data(
        self, symbol: str, from_date: date, to_date: date, interval: str = "day"
    ) -> list[OHLCVData]:
        """Fetch historical OHLCV candle data."""
        ...

    @abstractmethod
    async def get_quote(self, symbol: str) -> QuoteData:
        """Fetch current market quote for a symbol."""
        ...

    @abstractmethod
    async def is_connected(self) -> bool:
        """Check if the connection is active and token is valid."""
        ...

    async def get_funds(self) -> Optional[FundsData]:
        """Fetch available margin/funds. Optional."""
        return None

    async def subscribe_prices(self, symbols: list[str], callback) -> None:
        """Subscribe to real-time price streaming. Optional."""
        raise NotImplementedError("This broker does not support WebSocket streaming")
```

### Data Transfer Objects

All brokers return standardized data objects:

```python
@dataclass
class HoldingData:
    symbol: str
    exchange: str         # NSE, BSE, XETRA, etc.
    quantity: float
    average_price: float
    current_price: float
    pnl: float
    isin: Optional[str]

@dataclass
class OHLCVData:
    date: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
```

---

## Indian Brokers

### Zerodha (Kite Connect)

**Library**: `kiteconnect` (PyKiteConnect)
**File**: `backend/app/brokers/zerodha.py`
**Documentation**: https://kite.trade/docs/connect/v3/

#### Prerequisites

1. Sign up for a Kite Connect developer account at https://developers.kite.trade/
2. Create an app to get your API Key and API Secret
3. Subscribe to the relevant Kite Connect plan (costs apply)

#### OAuth Flow

```
1. User clicks "Connect Zerodha" in Settings -> Brokers
2. App redirects to Kite login page:
   https://kite.zerodha.com/connect/login?v=3&api_key=YOUR_API_KEY
3. User logs in and grants permissions
4. Kite redirects back to:
   http://localhost:8000/api/v1/brokers/zerodha/callback?request_token=TOKEN&status=success
5. Backend exchanges request_token for access_token using API secret
6. Access token stored (Fernet-encrypted) in broker_connections table
```

#### Available Endpoints

| Feature | Kite API | Status |
|---|---|---|
| Holdings | `kite.holdings()` | Supported |
| Positions | `kite.positions()` | Supported |
| Order history | `kite.orders()` | Supported |
| Historical data | `kite.historical_data(instrument, from, to, interval)` | Supported |
| Live quotes | `kite.quote(instruments)` | Supported |
| WebSocket streaming | `KiteTicker` | Supported |
| Margins/Funds | `kite.margins()` | Supported |
| Place order | `kite.place_order()` | Not implemented (read-only app) |

#### Token Management

- Access tokens expire at 6 AM IST daily
- On token expiry, user is prompted to re-authenticate via the OAuth flow
- The app checks token validity before each sync attempt

#### Implementation Notes

```python
from kiteconnect import KiteConnect, KiteTicker

class ZerodhaAdapter(BrokerAdapter):
    def __init__(self):
        self.kite = None
        self.ticker = None

    async def connect(self, api_key: str, api_secret: str, **kwargs):
        self.kite = KiteConnect(api_key=api_key)
        if "access_token" in kwargs:
            self.kite.set_access_token(kwargs["access_token"])
            return True
        return False

    async def get_auth_url(self) -> str:
        return self.kite.login_url()

    async def handle_callback(self, request_token: str) -> dict:
        data = self.kite.generate_session(
            request_token, api_secret=self.api_secret
        )
        self.kite.set_access_token(data["access_token"])
        return {
            "access_token": data["access_token"],
            "user_id": data["user_id"],
            "login_time": data["login_time"]
        }

    async def get_holdings(self) -> list[HoldingData]:
        holdings = self.kite.holdings()
        return [
            HoldingData(
                symbol=h["tradingsymbol"],
                exchange=h["exchange"],
                quantity=h["quantity"],
                average_price=h["average_price"],
                current_price=h["last_price"],
                pnl=h["pnl"],
                isin=h["isin"]
            )
            for h in holdings
        ]
```

---

### ICICI Direct (Breeze API)

**Library**: `breeze-connect`
**File**: `backend/app/brokers/icici_direct.py`
**Documentation**: https://api.icicidirect.com/

#### Prerequisites

1. Open an ICICI Direct trading account
2. Register for API access at https://api.icicidirect.com/
3. Get your App Key and Secret Key

#### OAuth Flow

```
1. User clicks "Connect ICICI Direct" in Settings -> Brokers
2. App redirects to ICICI login:
   https://api.icicidirect.com/apiuser/login?api_key=YOUR_APP_KEY
3. User logs in and authorizes
4. ICICI redirects back with session token
5. Backend initializes Breeze session with the token
6. Credentials stored encrypted in broker_connections
```

#### Available Endpoints

| Feature | Breeze API | Status |
|---|---|---|
| Holdings | `breeze.get_demat_holdings()` | Supported |
| Positions | `breeze.get_portfolio_positions()` | Supported |
| Trade history | `breeze.get_trade_list()` | Supported |
| Historical data | `breeze.get_historical_data_v2()` | Supported (10yr, 1-sec OHLCV) |
| Live quotes | `breeze.get_quotes()` | Supported |
| WebSocket streaming | `breeze.on_ticks` | Supported |
| Margins | `breeze.get_margin()` | Supported |

#### Implementation Notes

```python
from breeze_connect import BreezeConnect

class ICICIDirectAdapter(BrokerAdapter):
    def __init__(self):
        self.breeze = None

    async def connect(self, api_key: str, api_secret: str, **kwargs):
        self.breeze = BreezeConnect(api_key=api_key)
        if "session_token" in kwargs:
            self.breeze.generate_session(
                api_secret=api_secret,
                session_token=kwargs["session_token"]
            )
            return True
        return False

    async def get_historical_data(self, symbol, from_date, to_date, interval="1day"):
        data = self.breeze.get_historical_data_v2(
            interval=interval,
            from_date=from_date.isoformat(),
            to_date=to_date.isoformat(),
            stock_code=symbol,
            exchange_code="NSE"
        )
        return [self._to_ohlcv(candle) for candle in data["Success"]]
```

ICICI Direct Breeze stands out for providing up to 10 years of historical data with 1-second OHLCV resolution, which is significantly more granular than most other brokers.

---

### Groww

**File**: `backend/app/brokers/groww.py`
**Status**: Stub — Groww does not offer a public trading API. Adapter registered in broker registry but all methods raise `NotImplementedError`.

Integration uses a read-only approach:

| Method | Description |
|---|---|
| Groww Reports Export | Users export their holdings as CSV from Groww app |
| CAS Import | Import Consolidated Account Statement (CAMS/KFintech) for mutual funds |

**Workaround**: Users can export their Groww portfolio data as CSV, which FinanceTracker imports using the standard Excel import flow with column mapping.

---

### Angel One (SmartAPI)

**Library**: `smartapi-python`
**File**: `backend/app/brokers/angel_one.py`
**Documentation**: https://smartapi.angelbroking.com/docs
**Status**: Stub (coming soon) — adapter registered in broker registry, all methods raise `NotImplementedError`

#### Prerequisites (for when implementation is complete)

1. Open an Angel One trading account
2. Register for SmartAPI access
3. Get API Key, Client ID, and TOTP secret

#### Planned Features

| Feature | SmartAPI | Status |
|---|---|---|
| Holdings | `smartApi.holding()` | Planned |
| Positions | `smartApi.position()` | Planned |
| Order history | `smartApi.orderBook()` | Planned |
| Historical data | `smartApi.getCandleData()` | Planned |
| Live quotes | `smartApi.ltpData()` | Planned |
| WebSocket | `SmartWebSocket` | Planned |

#### Notes

- Angel One requires TOTP authentication (app-generated code) in addition to API credentials
- Access tokens expire daily and require re-login

---

### Upstox

**Library**: `upstox-python-sdk`
**File**: `backend/app/brokers/upstox.py`
**Documentation**: https://upstox.com/developer/api-documentation/
**Status**: Stub (coming soon) — adapter registered in broker registry, all methods raise `NotImplementedError`

#### Planned Features

| Feature | Upstox API v2 | Status |
|---|---|---|
| Holdings | `GET /portfolio/long-term-holdings` | Planned |
| Positions | `GET /portfolio/short-term-positions` | Planned |
| Historical data | `GET /historical-candle/{instrument}/{interval}/{to_date}` | Planned |
| Live quotes | Market data WebSocket | Planned |
| OAuth2 | Standard OAuth2 flow | Planned |

---

### 5Paisa

**Library**: `py5paisa`
**File**: `backend/app/brokers/fivepaisa.py`
**Documentation**: https://www.5paisa.com/developerapi
**Status**: Stub (coming soon) — adapter registered in broker registry, all methods raise `NotImplementedError`

#### Planned Features

| Feature | 5Paisa API | Status |
|---|---|---|
| Holdings | `client.holdings()` | Planned |
| Positions | `client.positions()` | Planned |
| Order book | `client.order_book()` | Planned |
| Historical data | `client.historical_data()` | Planned |
| Live feed | WebSocket subscription | Planned |

---

## German Brokers

### Deutsche Bank (PSD2 / Open Banking)

**File**: `backend/app/brokers/german/deutsche_bank.py`
**Protocol**: PSD2 (Payment Services Directive 2) / Berlin Group NextGenPSD2
**Status**: Stub (coming soon) — adapter registered in broker registry, all methods raise `NotImplementedError`. Requires PSD2 registration with BaFin.

#### Overview

German brokers are accessed through the PSD2 Open Banking framework, which mandates that banks provide third-party access to account data through standardized APIs.

#### PSD2 Flow

```
1. User clicks "Connect Deutsche Bank" in Settings -> Brokers
2. App redirects to Deutsche Bank consent page
3. User authenticates with their banking credentials
4. User grants consent for account access (valid for 90 days)
5. Bank redirects back with authorization code
6. Backend exchanges code for access token
7. Token stored encrypted, auto-refreshed before expiry
```

#### Available Endpoints (PSD2 Berlin Group)

| Feature | Endpoint | Status |
|---|---|---|
| Account list | `GET /v1/accounts` | Supported |
| Account balance | `GET /v1/accounts/{id}/balances` | Supported |
| Transaction list | `GET /v1/accounts/{id}/transactions` | Supported |
| Securities positions | Bank-specific extension | Planned |

#### Limitations

- PSD2 primarily covers payment accounts, not securities depots
- Securities portfolio data may require the bank's proprietary API
- Consent must be renewed every 90 days (SCA requirement)
- Strong Customer Authentication (SCA) required for each new consent

#### Implementation Notes

```python
class DeutscheBankAdapter(BrokerAdapter):
    PSD2_BASE_URL = "https://api.db.com/gw/dbapi/banking/v2"

    async def get_auth_url(self) -> str:
        return (
            f"https://simulator-api.db.com/gw/oidc/authorize"
            f"?response_type=code"
            f"&client_id={self.client_id}"
            f"&redirect_uri={self.redirect_uri}"
            f"&scope=read_accounts read_transactions"
        )

    async def handle_callback(self, authorization_code: str) -> dict:
        # Exchange auth code for access token
        response = await self.http.post(
            "https://simulator-api.db.com/gw/oidc/token",
            data={
                "grant_type": "authorization_code",
                "code": authorization_code,
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "redirect_uri": self.redirect_uri
            }
        )
        return response.json()
```

---

### comdirect (PSD2 / Open Banking)

**File**: `backend/app/brokers/german/comdirect.py`
**Documentation**: https://developer.comdirect.de/
**Status**: Stub (coming soon) — adapter registered in broker registry, all methods raise `NotImplementedError`

#### Overview

comdirect (now part of Commerzbank) provides both PSD2-compliant APIs and a proprietary REST API for securities depot access.

#### Features

| Feature | API | Status |
|---|---|---|
| Account list | PSD2 standard | Supported |
| Account balance | PSD2 standard | Supported |
| Transaction list | PSD2 standard | Supported |
| Securities depot | comdirect REST API | Supported |
| Depot positions | `GET /brokerage/depots/{depotId}/positions` | Supported |
| Order history | `GET /brokerage/depots/{depotId}/orders` | Supported |

#### Authentication

comdirect uses a multi-step authentication process:

```
1. POST /oauth/token (client credentials)
2. GET /session/clients/{clientId}/v1/sessions (get session)
3. POST /session/clients/{clientId}/v1/sessions/{sessionId}/validate
   -> User completes TAN challenge (photoTAN/pushTAN)
4. POST /oauth/token (session token exchange)
5. Access token valid for 10 minutes, refresh token for 24 hours
```

---

## Credential Security

All broker credentials are encrypted before storage:

1. **API Keys / Secrets**: Encrypted with Fernet symmetric encryption. The encryption key is derived from the `SECRET_KEY` environment variable.
2. **Access Tokens**: Encrypted at rest, decrypted only when making API calls.
3. **Token Rotation**: Access tokens are refreshed before expiry when possible.
4. **Disconnection**: Revoking a broker connection deletes all encrypted credentials from the database.

```python
from cryptography.fernet import Fernet

class CredentialManager:
    def __init__(self, secret_key: str):
        self.fernet = Fernet(secret_key.encode())

    def encrypt(self, value: str) -> str:
        return self.fernet.encrypt(value.encode()).decode()

    def decrypt(self, encrypted: str) -> str:
        return self.fernet.decrypt(encrypted.encode()).decode()
```

---

## Sync Strategy

When a broker is connected, the sync process follows this pattern:

```
1. Check token validity
   -> If expired: prompt user to re-authenticate
   -> If valid: proceed

2. Fetch holdings from broker
   -> Map to standardized HoldingData format
   -> Match with existing holdings by symbol+exchange

3. For new holdings:
   -> Create holding record with quantity and average price
   -> User needs to set range levels manually

4. For existing holdings:
   -> Update current_price from broker data
   -> Update cumulative_quantity if different
   -> Preserve user-set range levels (never overwritten by sync)

5. Fetch recent transactions
   -> Import new transactions not already in database
   -> Mark source as "BROKER"

6. Update last_synced timestamp
7. Trigger alert check on all updated holdings
```

### Conflict Resolution

| Scenario | Resolution |
|---|---|
| Broker quantity differs from app | Broker quantity takes precedence (it's the source of truth for what you hold) |
| Broker average price differs | Broker value used (accounts for corporate actions) |
| Range levels | Never overwritten by sync -- user-controlled |
| Custom fields | Never overwritten by sync -- user-controlled |
| Missing transactions | Broker transactions imported; manual transactions preserved |

---

## Adding a New Broker

To add a new broker integration:

1. Create a new file in `backend/app/brokers/` (e.g., `new_broker.py`)
2. Implement the `BrokerAdapter` abstract class
3. Register the adapter in `backend/app/brokers/__init__.py`
4. Add UI elements in Settings -> Brokers (web app)
5. Add OAuth redirect route in `backend/app/api/v1/broker.py`
6. Write tests in `backend/tests/test_brokers/test_new_broker.py`

---

## Related Documentation

- [Architecture](architecture.md) -- System overview
- [Security](security.md) -- Credential encryption details
- [API Reference](api-reference.md) -- Broker API endpoints
- [help/connecting-brokers.md](help/connecting-brokers.md) -- User guide for broker setup
