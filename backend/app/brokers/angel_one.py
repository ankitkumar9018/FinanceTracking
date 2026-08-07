"""Angel One broker adapter — stub (integration coming soon)."""

from __future__ import annotations

from app.brokers.base import StubBroker


class AngelOneBroker(StubBroker):
    """Angel One stub adapter — every operation raises ``NotImplementedError``."""

    BROKER_NAME: str = "angel_one"
