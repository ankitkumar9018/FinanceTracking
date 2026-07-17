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
from datetime import datetime

class BrokerAdapter(ABC):
    """Abstract interface for all broker integrations."""

    BROKER_NAME: str = ""

    @abstractmethod
    async def connect(self, api_key: str, api_secret: str, **kwargs) -> dict:
        """Initialize connection and return access-token info.

        Returns a dict with at least ``{"access_token": ..., "login_url": ...}``
        depending on the broker's OAuth flow.
        """

    @abstractmethod
    async def disconnect(self) -> None:
        """Clean up the connection / invalidate session."""

    @abstractmethod
    async def get_holdings(self) -> list[BrokerHolding]:
        """Fetch demat holdings."""

    @abstractmethod
    async def get_positions(self) -> list[BrokerPosition]:
        """Fetch current-day positions."""

    @abstractmethod
    async def get_orders(
        self, from_date: datetime | None = None, to_date: datetime | None = None
    ) -> list[BrokerOrder]:
        """Fetch order history, optionally filtered by date range."""

    @abstractmethod
    async def get_historical_data(
        self,
        symbol: str,
        exchange: str,
        from_date: datetime,
        to_date: datetime,
        interval: str = "day",
    ) -> list[dict]:
        """Fetch OHLCV candles as dicts with keys date/open/high/low/close/volume."""

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if the session is active and usable. (Synchronous.)"""

    async def get_live_price(self, symbol: str, exchange: str) -> float | None:
        """Get the live price for a symbol. Optional — default returns None."""
        return None
```

Note that there are no separate `get_auth_url` / `handle_callback` methods: the OAuth round-trip is handled entirely inside `connect()` (call it without a token to get a `login_url`, call it again with the token to complete the exchange — see the Zerodha flow below).

### Data Transfer Objects

All brokers return standardized dataclasses defined in `base.py`:

```python
@dataclass
class BrokerHolding:
    symbol: str
    exchange: str         # NSE, BSE, etc.
    quantity: float
    average_price: float
    last_price: float | None = None

@dataclass
class BrokerOrder:
    order_id: str
    symbol: str
    exchange: str
    order_type: str       # BUY / SELL
    quantity: float
    price: float
    status: str           # COMPLETE / PENDING / CANCELLED
    timestamp: datetime | None = None

@dataclass
class BrokerPosition:
    symbol: str
    exchange: str
    quantity: float
    average_price: float
    last_price: float
    pnl: float
    day_change: float
```

Historical candles are returned as plain dicts (`date`, `open`, `high`, `low`, `close`, `volume`) rather than a dedicated OHLCV dataclass.

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

There is no dedicated callback route — the whole round-trip goes through `POST /api/v1/broker/connect` (router prefix is `/broker`, singular):

```
1. User clicks "Connect Zerodha" in the Brokers page
2. Frontend calls POST /api/v1/broker/connect with api_key + api_secret
   (no request_token yet)
3. Backend returns a connect response whose login_url points to the
   Kite login page:
   https://kite.zerodha.com/connect/login?v=3&api_key=YOUR_API_KEY
4. User logs in and grants permissions; Kite redirects to the app's
   configured redirect URL with request_token=TOKEN
5. Frontend calls POST /api/v1/broker/connect again, passing the
   request_token in additional_params
6. Backend exchanges request_token for access_token using the API secret
7. Access token stored (Fernet-encrypted) in broker_connections table
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

The adapter class is `ZerodhaBroker` (in `brokers/zerodha.py`). `kiteconnect` is an optional dependency — if it is not installed, `connect()` raises a clear "install kiteconnect" error. The two-phase OAuth handshake lives entirely in `connect()`:

```python
class ZerodhaBroker(BrokerAdapter):
    BROKER_NAME = "zerodha"

    async def connect(self, api_key: str, api_secret: str, **kwargs) -> dict:
        self._kite = KiteConnect(api_key=api_key)

        request_token = kwargs.get("request_token")
        if request_token:
            # Phase 2: complete the token exchange
            data = self._kite.generate_session(request_token, api_secret=api_secret)
            self._access_token = data["access_token"]
            self._kite.set_access_token(self._access_token)
            return {"access_token": self._access_token, "login_url": None}

        # Phase 1: return login URL so the frontend can redirect
        return {"access_token": None, "login_url": self._kite.login_url()}

    async def get_holdings(self) -> list[BrokerHolding]:
        raw_holdings = self._kite.holdings()
        return [
            BrokerHolding(
                symbol=h.get("tradingsymbol", ""),
                exchange=EXCHANGE_MAP.get(h.get("exchange", "NSE"), "NSE"),
                quantity=float(h.get("quantity", 0)),
                average_price=float(h.get("average_price", 0)),
                last_price=float(h["last_price"]) if h.get("last_price") else None,
            )
            for h in raw_holdings
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

The adapter class is `ICICIDirectBroker` (in `brokers/icici_direct.py`). `breeze_connect` is an optional dependency. Like Zerodha, the OAuth handshake is two calls to `connect()` — the first returns a `login_url` (`https://api.icicidirect.com/apiuser/login?api_key=...`), the second passes `session_token` in `additional_params` to complete `generate_session`:

```python
class ICICIDirectBroker(BrokerAdapter):
    BROKER_NAME = "icici_direct"

    async def connect(self, api_key: str, api_secret: str, **kwargs) -> dict:
        self._breeze = BreezeConnect(api_key=api_key)

        session_token = kwargs.get("session_token")
        if session_token:
            # Phase 2: complete the session generation
            self._breeze.generate_session(
                api_secret=api_secret,
                session_token=session_token,
            )
            self._session_token = session_token
            return {"access_token": session_token, "login_url": None}

        # Phase 1: return login URL for the user to authenticate
        login_url = f"https://api.icicidirect.com/apiuser/login?api_key={api_key}"
        return {"access_token": None, "login_url": login_url}
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

The adapter class is `DeutscheBankBroker` (in `brokers/german/deutsche_bank.py`). It is currently a stub: every method raises `NotImplementedError`, and the API surfaces it as HTTP 501. The PSD2 flow above describes the planned integration only.

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

1. **API Keys / Secrets**: Encrypted with Fernet symmetric encryption. The key comes from the dedicated `FERNET_KEY` environment variable (`backend/app/config.py`) — it is **not** derived from `SECRET_KEY`.
2. **Access Tokens**: Encrypted at rest, decrypted only when making API calls.
3. **Token Rotation**: Access tokens are refreshed before expiry when possible.
4. **Disconnection**: Revoking a broker connection deletes all encrypted credentials from the database.

Encryption is done via module-level functions in `backend/app/utils/security.py` (there is no `CredentialManager` class):

```python
from app.utils.security import encrypt_value, decrypt_value

encrypted = encrypt_value(api_secret)   # before DB storage
plaintext = decrypt_value(encrypted)    # when making API calls
```

If `FERNET_KEY` is unset, an **ephemeral key is generated at startup** (with a warning): encrypted data becomes unrecoverable after a restart. Set `FERNET_KEY` in `.env` for persistence.

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
2. Implement the `BrokerAdapter` abstract class (handle any OAuth handshake inside `connect()` via the `login_url` / `additional_params` pattern)
3. Register the adapter in `BROKER_REGISTRY` in `backend/app/brokers/__init__.py`
4. Add UI elements in the Brokers page (web app)
5. Write tests in `backend/tests/test_brokers/test_new_broker.py`

---

## Related Documentation

- [Architecture](architecture.md) -- System overview
- [Security](security.md) -- Credential encryption details
- [API Reference](api-reference.md) -- Broker API endpoints
- [help/connecting-brokers.md](help/connecting-brokers.md) -- User guide for broker setup
