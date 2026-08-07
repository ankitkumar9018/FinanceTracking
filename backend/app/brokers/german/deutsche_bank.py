"""Deutsche Bank broker adapter — stub (integration coming soon)."""

from __future__ import annotations

from app.brokers.base import StubBroker


class DeutscheBankBroker(StubBroker):
    """Deutsche Bank stub adapter — every operation raises ``NotImplementedError``."""

    BROKER_NAME: str = "deutsche_bank"
