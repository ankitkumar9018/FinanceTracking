"""ICICI Direct (Breeze Connect) broker adapter.

The ``breeze_connect`` package is an *optional* dependency.  If it is not
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
    from breeze_connect import BreezeConnect  # type: ignore[import-untyped]

    _BREEZE_AVAILABLE = True
except ImportError:
    _BREEZE_AVAILABLE = False
    BreezeConnect = None  # type: ignore[assignment,misc]

# ---------------------------------------------------------------------------
# Exchange mapping
# ---------------------------------------------------------------------------
EXCHANGE_MAP: dict[str, str] = {
    "NSE": "NSE",
    "BSE": "BSE",
}


class ICICIDirectBroker(BrokerAdapter):
    """ICICI Direct Breeze Connect adapter."""

    BROKER_NAME: str = "icici_direct"

    def __init__(self) -> None:
        self._breeze: BreezeConnect | None = None  # type: ignore[assignment]
        self._session_token: str | None = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def connect(self, api_key: str, api_secret: str, **kwargs) -> dict:
        """Generate session with ICICI Breeze API.

        Parameters
        ----------
        api_key : str
            ICICI Direct app key.
        api_secret : str
            ICICI Direct secret key.
        **kwargs
            Pass ``session_token`` to complete the session generation.

        Returns
        -------
        dict
            ``{"access_token": ..., "login_url": ...}``
        """
        if not _BREEZE_AVAILABLE:
            raise RuntimeError(
                "ICICI Direct SDK not installed. "
                "Run `pip install breeze-connect` to enable ICICI Direct integration."
            )

        self._breeze = BreezeConnect(api_key=api_key)

        session_token: str | None = kwargs.get("session_token")
        if session_token:
            # Complete the session generation
            self._breeze.generate_session(
                api_secret=api_secret,
                session_token=session_token,
            )
            self._session_token = session_token
            logger.info("ICICI Direct session established for api_key=%s", api_key[:6])
            return {
                "access_token": session_token,
                "login_url": None,
            }

        # Step 1: return login URL for the user to authenticate
        login_url = (
            f"https://api.icicidirect.com/apiuser/login?api_key={api_key}"
        )
        logger.info("ICICI Direct login URL generated for api_key=%s", api_key[:6])
        return {
            "access_token": None,
            "login_url": login_url,
        }

    async def disconnect(self) -> None:
        """Clean up the Breeze session."""
        self._breeze = None
        self._session_token = None

    def is_connected(self) -> bool:
        """Return ``True`` if the Breeze client has an active session."""
        return self._breeze is not None and self._session_token is not None

    # ------------------------------------------------------------------
    # Holdings
    # ------------------------------------------------------------------

    async def get_holdings(self) -> list[BrokerHolding]:
        """Fetch demat holdings from ICICI Direct."""
        self._ensure_connected()
        assert self._breeze is not None

        response = self._breeze.get_demat_holdings()
        raw_holdings = response.get("Success", []) if isinstance(response, dict) else []

        holdings: list[BrokerHolding] = []
        for h in raw_holdings:
            holdings.append(
                BrokerHolding(
                    symbol=h.get("stock_code", ""),
                    exchange=EXCHANGE_MAP.get(
                        h.get("exchange_code", "NSE"), "NSE"
                    ),
                    quantity=float(h.get("quantity", 0)),
                    average_price=float(h.get("average_price", 0)),
                    last_price=(
                        float(h["current_market_price"])
                        if h.get("current_market_price")
                        else None
                    ),
                )
            )
        return holdings

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    async def get_positions(self) -> list[BrokerPosition]:
        """Fetch current-day positions from ICICI Direct."""
        self._ensure_connected()
        assert self._breeze is not None

        response = self._breeze.get_portfolio_positions()
        raw_positions = (
            response.get("Success", []) if isinstance(response, dict) else []
        )

        positions: list[BrokerPosition] = []
        for p in raw_positions:
            last_price = float(p.get("ltp", 0))
            avg_price = float(p.get("average_price", 0))
            qty = float(p.get("quantity", 0))
            pnl = (last_price - avg_price) * qty if avg_price else 0.0

            positions.append(
                BrokerPosition(
                    symbol=p.get("stock_code", ""),
                    exchange=EXCHANGE_MAP.get(
                        p.get("exchange_code", "NSE"), "NSE"
                    ),
                    quantity=qty,
                    average_price=avg_price,
                    last_price=last_price,
                    pnl=round(pnl, 2),
                    day_change=float(p.get("day_change", 0)),
                )
            )
        return positions

    # ------------------------------------------------------------------
    # Orders
    # ------------------------------------------------------------------

    async def get_orders(
        self, from_date: datetime | None = None, to_date: datetime | None = None
    ) -> list[BrokerOrder]:
        """Fetch order history from ICICI Direct."""
        self._ensure_connected()
        assert self._breeze is not None

        params: dict = {}
        if from_date:
            params["from_date"] = from_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        if to_date:
            params["to_date"] = to_date.strftime("%Y-%m-%dT%H:%M:%S.000Z")

        response = self._breeze.get_order_list(
            exchange_code="NSE",
            from_date=params.get("from_date", ""),
            to_date=params.get("to_date", ""),
        )
        raw_orders = (
            response.get("Success", []) if isinstance(response, dict) else []
        )

        orders: list[BrokerOrder] = []
        for o in raw_orders:
            ts = None
            ts_str = o.get("order_datetime")
            if ts_str:
                try:
                    ts = datetime.fromisoformat(str(ts_str))
                except (ValueError, TypeError):
                    pass

            status_map = {
                "Executed": "COMPLETE",
                "Pending": "PENDING",
                "Cancelled": "CANCELLED",
            }

            orders.append(
                BrokerOrder(
                    order_id=str(o.get("order_id", "")),
                    symbol=o.get("stock_code", ""),
                    exchange=EXCHANGE_MAP.get(
                        o.get("exchange_code", "NSE"), "NSE"
                    ),
                    order_type=o.get("action", "BUY"),
                    quantity=float(o.get("quantity", 0)),
                    price=float(o.get("price", 0)),
                    status=status_map.get(o.get("status", ""), "UNKNOWN"),
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
        """Fetch OHLCV candle data from ICICI Direct."""
        self._ensure_connected()
        assert self._breeze is not None

        # Map interval to Breeze API values
        interval_map = {
            "day": "1day",
            "minute": "1minute",
            "5minute": "5minute",
            "15minute": "15minute",
            "60minute": "1hour",
        }
        breeze_interval = interval_map.get(interval, "1day")
        exchange_code = EXCHANGE_MAP.get(exchange, exchange)

        response = self._breeze.get_historical_data(
            interval=breeze_interval,
            from_date=from_date.strftime("%Y-%m-%dT07:00:00.000Z"),
            to_date=to_date.strftime("%Y-%m-%dT07:00:00.000Z"),
            stock_code=symbol,
            exchange_code=exchange_code,
        )
        raw_data = (
            response.get("Success", []) if isinstance(response, dict) else []
        )

        candles: list[dict] = []
        for candle in raw_data:
            candles.append(
                {
                    "date": candle.get("datetime"),
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
        """Get the last traded price via Breeze quote API."""
        if not self.is_connected():
            return None
        assert self._breeze is not None

        exchange_code = EXCHANGE_MAP.get(exchange, exchange)
        try:
            response = self._breeze.get_quotes(
                stock_code=symbol,
                exchange_code=exchange_code,
            )
            data = response.get("Success", []) if isinstance(response, dict) else []
            if data and isinstance(data, list) and len(data) > 0:
                return float(data[0].get("ltp", 0))
            return None
        except Exception:
            logger.warning(
                "Failed to get live price for %s:%s", exchange, symbol, exc_info=True
            )
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_connected(self) -> None:
        """Raise if the adapter is not connected."""
        if not self.is_connected():
            raise RuntimeError(
                "ICICI Direct adapter is not connected. Call connect() first."
            )
