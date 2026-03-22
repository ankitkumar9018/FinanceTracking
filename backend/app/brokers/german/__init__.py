"""German broker adapters (Deutsche Bank, Comdirect)."""

from __future__ import annotations

from app.brokers.german.comdirect import ComdirectBroker
from app.brokers.german.deutsche_bank import DeutscheBankBroker

__all__ = ["ComdirectBroker", "DeutscheBankBroker"]
