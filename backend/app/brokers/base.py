"""Abstract broker adapter — base interface for all broker integrations."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class BrokerHolding:
    """A single holding returned by a broker."""

    symbol: str
    exchange: str
    quantity: float
    average_price: float
    last_price: float | None = None


@dataclass
class BrokerOrder:
    """A single order returned by a broker."""

    order_id: str
    symbol: str
    exchange: str
    order_type: str  # BUY / SELL
    quantity: float
    price: float
    status: str  # COMPLETE / PENDING / CANCELLED
    timestamp: datetime | None = None


@dataclass
class BrokerPosition:
    """A current-day position returned by a broker."""

    symbol: str
    exchange: str
    quantity: float
    average_price: float
    last_price: float
    pnl: float
    day_change: float


class BrokerAdapter(ABC):
    """Abstract interface for all broker integrations.

    Every concrete broker adapter (Zerodha, ICICI Direct, Groww, etc.)
    must subclass this and implement all abstract methods.
    """

    BROKER_NAME: str = ""

    @abstractmethod
    async def connect(self, api_key: str, api_secret: str, **kwargs) -> dict:
        """Initialize connection and return access-token info.

        Returns
        -------
        dict
            Must contain at least ``{"access_token": ..., "login_url": ...}``
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
        """Fetch OHLCV candle data.

        Returns
        -------
        list[dict]
            Each dict has keys: ``date``, ``open``, ``high``, ``low``,
            ``close``, ``volume``.
        """

    @abstractmethod
    def is_connected(self) -> bool:
        """Return ``True`` if the session is active and usable."""

    async def get_live_price(self, symbol: str, exchange: str) -> float | None:
        """Get the live price for a symbol.

        Default implementation returns ``None`` — not all brokers support
        streaming or polling live quotes.
        """
        return None
