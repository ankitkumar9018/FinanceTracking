"""Comdirect broker adapter — stub (integration coming soon)."""

from __future__ import annotations

from app.brokers.base import StubBroker


class ComdirectBroker(StubBroker):
    """Comdirect stub adapter — every operation raises ``NotImplementedError``."""

    BROKER_NAME: str = "comdirect"
