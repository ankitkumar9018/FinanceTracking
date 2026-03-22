"""Upstox broker adapter — stub implementation."""

from __future__ import annotations

from datetime import datetime

from app.brokers.base import (
    BrokerAdapter,
    BrokerHolding,
    BrokerOrder,
    BrokerPosition,
)

_NOT_IMPLEMENTED_MSG = "Upstox integration coming soon"


class UpstoxBroker(BrokerAdapter):
    """Upstox stub adapter — all methods raise ``NotImplementedError``."""

    BROKER_NAME: str = "upstox"

    async def connect(self, api_key: str, api_secret: str, **kwargs) -> dict:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    async def disconnect(self) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    async def get_holdings(self) -> list[BrokerHolding]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    async def get_positions(self) -> list[BrokerPosition]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    async def get_orders(
        self, from_date: datetime | None = None, to_date: datetime | None = None
    ) -> list[BrokerOrder]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    async def get_historical_data(
        self,
        symbol: str,
        exchange: str,
        from_date: datetime,
        to_date: datetime,
        interval: str = "day",
    ) -> list[dict]:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)

    def is_connected(self) -> bool:
        raise NotImplementedError(_NOT_IMPLEMENTED_MSG)
