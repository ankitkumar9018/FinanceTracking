"""Groww broker adapter — stub (integration coming soon)."""

from __future__ import annotations

from app.brokers.base import StubBroker


class GrowwBroker(StubBroker):
    """Groww stub adapter — every operation raises ``NotImplementedError``."""

    BROKER_NAME: str = "groww"
