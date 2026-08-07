"""Single source of exchange knowledge.

Merges the per-service copies of exchange metadata:

- ``market_data_service._EXCHANGE_SUFFIX`` / ``tax_service._EXCHANGE_YF_SUFFIX``
  → :data:`YF_SUFFIX`
- ``tax_service.EXCHANGE_CURRENCY_MAP`` / ``forex_service.EXCHANGE_CURRENCY_MAP``
  → :data:`CURRENCY`
- ``tax_service.EXCHANGE_JURISDICTION_MAP`` → :data:`JURISDICTION`

Every map here is a value-identical superset of the service-local copies so
those services can delegate here without behavior change.
"""

from __future__ import annotations

__all__ = ["CURRENCY", "JURISDICTION", "YF_SUFFIX", "ticker_symbol"]

# Exchange -> yfinance ticker suffix.
YF_SUFFIX: dict[str, str] = {
    "NSE": ".NS",
    "BSE": ".BO",
    "XETRA": ".DE",
    "NYSE": "",
    "NASDAQ": "",
}

# Exchange -> trading currency.
# FRA (Frankfurt floor) extends the service-local maps; it does not conflict
# with them.
CURRENCY: dict[str, str] = {
    "NSE": "INR",
    "BSE": "INR",
    "XETRA": "EUR",
    "FRA": "EUR",
    "NYSE": "USD",
    "NASDAQ": "USD",
}

# Exchange -> tax jurisdiction (ISO country code).
# FRA extends tax_service.EXCHANGE_JURISDICTION_MAP; it does not conflict.
JURISDICTION: dict[str, str] = {
    "NSE": "IN",
    "BSE": "IN",
    "XETRA": "DE",
    "FRA": "DE",
    "NYSE": "US",
    "NASDAQ": "US",
}


def ticker_symbol(symbol: str, exchange: str | None) -> str:
    """Return the yfinance ticker string for a symbol and exchange.

    Same behavior as ``market_data_service._ticker_symbol`` (unknown
    exchanges get no suffix), with two safe extensions:

    - ``exchange=None``/empty → the bare symbol (the original required a
      string and would crash on ``None``).
    - Index symbols starting with ``^`` (e.g. ``^NSEI``, ``^GSPC``) pass
      through unsuffixed — yfinance index tickers never take an exchange
      suffix, and the original was never called with them.
    """
    if symbol.startswith("^") or not exchange:
        return symbol
    suffix = YF_SUFFIX.get(exchange.upper(), "")
    return f"{symbol}{suffix}"
