"""5Paisa broker adapter — stub (integration coming soon)."""

from __future__ import annotations

from app.brokers.base import StubBroker


class FivePaisaBroker(StubBroker):
    """5Paisa stub adapter — every operation raises ``NotImplementedError``."""

    BROKER_NAME: str = "5paisa"
