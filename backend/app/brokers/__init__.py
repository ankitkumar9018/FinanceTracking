"""Broker integration registry.

Provides ``BROKER_REGISTRY`` — a mapping of broker names to their adapter
classes — and ``get_broker()`` to instantiate an adapter by name.
"""

from __future__ import annotations

from app.brokers.angel_one import AngelOneBroker
from app.brokers.base import BrokerAdapter
from app.brokers.fivepaisa import FivePaisaBroker
from app.brokers.german.comdirect import ComdirectBroker
from app.brokers.german.deutsche_bank import DeutscheBankBroker
from app.brokers.groww import GrowwBroker
from app.brokers.icici_direct import ICICIDirectBroker
from app.brokers.upstox import UpstoxBroker
from app.brokers.zerodha import ZerodhaBroker

BROKER_REGISTRY: dict[str, type[BrokerAdapter]] = {
    "zerodha": ZerodhaBroker,
    "icici_direct": ICICIDirectBroker,
    "groww": GrowwBroker,
    "angel_one": AngelOneBroker,
    "upstox": UpstoxBroker,
    "5paisa": FivePaisaBroker,
    "deutsche_bank": DeutscheBankBroker,
    "comdirect": ComdirectBroker,
}


def get_broker(name: str) -> BrokerAdapter:
    """Instantiate and return a broker adapter by name.

    Parameters
    ----------
    name : str
        One of the keys in ``BROKER_REGISTRY`` (e.g. ``"zerodha"``).

    Returns
    -------
    BrokerAdapter
        A fresh adapter instance ready for ``connect()``.

    Raises
    ------
    ValueError
        If the broker name is not found in the registry.
    """
    cls = BROKER_REGISTRY.get(name)
    if cls is None:
        available = ", ".join(sorted(BROKER_REGISTRY.keys()))
        raise ValueError(
            f"Unknown broker '{name}'. Available brokers: {available}"
        )
    return cls()


__all__ = [
    "BROKER_REGISTRY",
    "BrokerAdapter",
    "get_broker",
    # Concrete adapters
    "ZerodhaBroker",
    "ICICIDirectBroker",
    "GrowwBroker",
    "AngelOneBroker",
    "UpstoxBroker",
    "FivePaisaBroker",
    "DeutscheBankBroker",
    "ComdirectBroker",
]
