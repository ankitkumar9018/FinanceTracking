"""Zerodha (Kite Connect) broker adapter.

The ``kiteconnect`` package is an *optional* dependency.  If it is not
installed, the adapter will still load but ``connect()`` will raise a
clear error telling the user to install it.
"""

from __future__ import annotations

import logging
from datetime import datetime

from app.brokers.base import (
    BrokerAdapter,
    BrokerHolding,
    BrokerOrder,
    BrokerPosition,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional SDK import
# ---------------------------------------------------------------------------
try:
    from kiteconnect import KiteConnect  # type: ignore[import-untyped]

    _KITE_AVAILABLE = True
except ImportError:
    _KITE_AVAILABLE = False
    KiteConnect = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Exchange mapping (Zerodha uses same exchange codes)
# ---------------------------------------------------------------------------
EXCHANGE_MAP: dict[str, str] = {
    "NSE": "NSE",
    "BSE": "BSE",
}


class ZerodhaBroker(BrokerAdapter):
    """Zerodha Kite Connect adapter."""

    BROKER_NAME: str = "zerodha"

    def __init__(self) -> None:
        self._kite: KiteConnect | None = None  # type: ignore[assignment]
        self._access_token: str | None = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def connect(self, api_key: str, api_secret: str, **kwargs) -> dict:
        """Generate login URL or complete the token exchange.

        Parameters
        ----------
        api_key : str
            Zerodha API key.
        api_secret : str
            Zerodha API secret.
        **kwargs
            Pass ``request_token`` to complete the access-token exchange.

        Returns
        -------
        dict
            ``{"login_url": ..., "access_token": ...}``
        """
        if not _KITE_AVAILABLE:
            raise RuntimeError(
                "Zerodha SDK not installed. "
                "Run `pip install kiteconnect` to enable Zerodha integration."
            )

        self._kite = KiteConnect(api_key=api_key)

        request_token: str | None = kwargs.get("request_token")
        if request_token:
            # Complete the token exchange
            data = self._kite.generate_session(request_token, api_secret=api_secret)
            self._access_token = data["access_token"]
            self._kite.set_access_token(self._access_token)
            logger.info("Zerodha session established for api_key=%s", api_key[:6])
            return {
                "access_token": self._access_token,
                "login_url": None,
            }

        # Step 1: return login URL so the frontend can redirect
        login_url = self._kite.login_url()
        logger.info("Zerodha login URL generated for api_key=%s", api_key[:6])
        return {
            "access_token": None,
            "login_url": login_url,
        }

    async def disconnect(self) -> None:
        """Invalidate the Kite session."""
        if self._kite and self._access_token:
            try:
                self._kite.invalidate_access_token(self._access_token)
            except Exception:
                logger.warning("Failed to invalidate Zerodha access token", exc_info=True)
        self._kite = None
        self._access_token = None

    def is_connected(self) -> bool:
        """Return ``True`` if the Kite client has an active access token."""
        return self._kite is not None and self._access_token is not None

    # ------------------------------------------------------------------
    # Holdings
    # ------------------------------------------------------------------

    async def get_holdings(self) -> list[BrokerHolding]:
        """Fetch demat holdings from Zerodha."""
        self._ensure_connected()
        assert self._kite is not None  # for type narrowing

        raw_holdings = self._kite.holdings()
        holdings: list[BrokerHolding] = []
        for h in raw_holdings:
            holdings.append(
                BrokerHolding(
                    symbol=h.get("tradingsymbol", ""),
                    exchange=EXCHANGE_MAP.get(h.get("exchange", "NSE"), "NSE"),
                    quantity=float(h.get("quantity", 0)),
                    average_price=float(h.get("average_price", 0)),
                    last_price=float(h["last_price"]) if h.get("last_price") else None,
                )
            )
        return holdings

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    async def get_positions(self) -> list[BrokerPosition]:
        """Fetch current-day positions from Zerodha."""
        self._ensure_connected()
        assert self._kite is not None

        data = self._kite.positions()
        positions: list[BrokerPosition] = []

        # Kite returns {"net": [...], "day": [...]}
        for p in data.get("net", []):
            positions.append(
                BrokerPosition(
                    symbol=p.get("tradingsymbol", ""),
                    exchange=EXCHANGE_MAP.get(p.get("exchange", "NSE"), "NSE"),
                    quantity=float(p.get("quantity", 0)),
                    average_price=float(p.get("average_price", 0)),
                    last_price=float(p.get("last_price", 0)),
                    pnl=float(p.get("pnl", 0)),
                    day_change=float(p.get("day_m2m", 0)),
                )
            )
        return positions

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    async def get_orders(
        self, from_date: datetime | None = None, to_date: datetime | None = None
    ) -> list[BrokerOrder]:
        """Fetch order history from Zerodha.

        Note: Kite API returns all orders for the current trading day.
        Date filtering is applied client-side.
        """
        self._ensure_connected()
        assert self._kite is not None

        raw_orders = self._kite.orders()
        orders: list[BrokerOrder] = []
        for o in raw_orders:
            ts_str = o.get("order_timestamp")
            ts = None
            if ts_str:
                try:
                    ts = datetime.fromisoformat(str(ts_str))
                except (ValueError, TypeError):
                    pass

            # Client-side date filtering
            if ts:
                if from_date and ts < from_date:
                    continue
                if to_date and ts > to_date:
                    continue

            orders.append(
                BrokerOrder(
                    order_id=str(o.get("order_id", "")),
                    symbol=o.get("tradingsymbol", ""),
                    exchange=EXCHANGE_MAP.get(o.get("exchange", "NSE"), "NSE"),
                    order_type=o.get("transaction_type", "BUY"),
                    quantity=float(o.get("quantity", 0)),
                    price=float(o.get("average_price", 0) or o.get("price", 0)),
                    status=o.get("status", "UNKNOWN"),
                    timestamp=ts,
                )
            )
        return orders

    # ------------------------------------------------------------------
    # Historical data
    # ------------------------------------------------------------------

    async def get_historical_data(
        self,
        symbol: str,
        exchange: str,
        from_date: datetime,
        to_date: datetime,
        interval: str = "day",
    ) -> list[dict]:
        """Fetch OHLCV candle data from Zerodha.

        This requires looking up the instrument token first.
        """
        self._ensure_connected()
        assert self._kite is not None

        # Map friendly interval names to Kite intervals
        interval_map = {
            "day": "day",
            "minute": "minute",
            "5minute": "5minute",
            "15minute": "15minute",
            "60minute": "60minute",
        }
        kite_interval = interval_map.get(interval, "day")

        # Look up the instrument token
        exchange_code = EXCHANGE_MAP.get(exchange, exchange)
        instruments = self._kite.instruments(exchange_code)
        instrument_token: int | None = None
        for inst in instruments:
            if inst.get("tradingsymbol") == symbol:
                instrument_token = inst["instrument_token"]
                break

        if instrument_token is None:
            logger.warning("Instrument token not found for %s:%s", exchange, symbol)
            return []

        raw_data = self._kite.historical_data(
            instrument_token,
            from_date=from_date,
            to_date=to_date,
            interval=kite_interval,
        )

        candles: list[dict] = []
        for candle in raw_data:
            candles.append(
                {
                    "date": candle.get("date"),
                    "open": float(candle.get("open", 0)),
                    "high": float(candle.get("high", 0)),
                    "low": float(candle.get("low", 0)),
                    "close": float(candle.get("close", 0)),
                    "volume": int(candle.get("volume", 0)),
                }
            )
        return candles

    # ------------------------------------------------------------------
    # Live price
    # ------------------------------------------------------------------

    async def get_live_price(self, symbol: str, exchange: str) -> float | None:
        """Get the last traded price via Kite quote API."""
        if not self.is_connected():
            return None
        assert self._kite is not None

        exchange_code = EXCHANGE_MAP.get(exchange, exchange)
        instrument_key = f"{exchange_code}:{symbol}"
        try:
            quotes = self._kite.quote(instrument_key)
            data = quotes.get(instrument_key, {})
            return float(data["last_price"]) if "last_price" in data else None
        except Exception:
            logger.warning("Failed to get live price for %s", instrument_key, exc_info=True)
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_connected(self) -> None:
        """Raise if the adapter is not connected."""
        if not self.is_connected():
            raise RuntimeError(
                "Zerodha adapter is not connected. Call connect() first."
            )
