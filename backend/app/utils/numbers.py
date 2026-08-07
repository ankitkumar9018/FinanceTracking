"""Shared numeric parsing helpers.

Two parsers with distinct contracts:

- :func:`parse_number` — locale-aware parsing of human/broker-formatted
  strings (currency symbols, US ``1,234.56`` and European ``1.234,56`` /
  ``1234,56`` conventions).  Extracted from
  ``app.services.csv_import_service`` (``_normalize_numeric_str`` +
  ``_safe_float``) with identical semantics so CSV import can delegate to
  it without behavior change.
- :func:`coerce_float` — plain NaN/Inf-safe ``float()`` coercion with no
  locale logic, matching ``app.services.market_data_service._safe_float``.
"""

from __future__ import annotations

import math

__all__ = ["coerce_float", "parse_number"]


def _normalize_numeric_str(s: str) -> str:
    """Normalize a numeric string to a Python-parseable form, handling both
    US (``1,234.56``) and European (``1.234,56`` / ``1234,56``) conventions.

    Rules:
    - Both ``.`` and ``,`` present → the *last* one is the decimal separator:
      ``1.234,56`` (European) → ``1234.56``; ``1,234.56`` (US) → ``1234.56``.
    - Only ``,`` present → a single trailing group of not-3 digits is treated as
      a decimal comma (``1234,56`` → ``1234.56``, ``1,5`` → ``1.5``); otherwise
      commas are thousands separators and dropped (``1,234`` → ``1234``).
    - Only ``.`` present → multiple dots are thousands separators and dropped
      (``1.234.567`` → ``1234567``); a single dot stays a US decimal point so
      existing ``1234.56`` parsing is unaffected.
    """
    s = s.strip()
    has_dot = "." in s
    has_comma = "," in s

    if has_dot and has_comma:
        if s.rfind(",") > s.rfind("."):
            # European: dot = thousands, comma = decimal
            s = s.replace(".", "").replace(",", ".")
        else:
            # US: comma = thousands, dot = decimal
            s = s.replace(",", "")
    elif has_comma:
        parts = s.split(",")
        # Single comma with a non-3-digit tail → decimal comma; otherwise the
        # comma(s) are thousands separators and dropped.
        decimal_comma = len(parts) == 2 and len(parts[1]) != 3
        s = s.replace(",", ".") if decimal_comma else s.replace(",", "")
    elif has_dot and s.count(".") > 1:
        # Multiple dots → thousands separators (European grouping)
        s = s.replace(".", "")

    return s


def parse_number(value: object) -> float | None:
    """Parse a locale-formatted number, returning ``None`` on failure.

    Strips common currency symbols (₹, $, €, £), non-breaking spaces, and
    regular spaces, then understands both US and European number formatting
    (see :func:`_normalize_numeric_str`).  ``int``/``float`` inputs pass
    through unchanged; ``None`` and empty/unparseable strings yield ``None``.
    """
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        s = (
            str(value)
            .replace("₹", "")
            .replace("$", "")
            .replace("€", "")
            .replace("£", "")
            .replace("\xa0", "")  # non-breaking space (common thousands sep)
            .replace(" ", "")
            .strip()
        )
        if not s:
            return None
        return float(_normalize_numeric_str(s))
    except (ValueError, TypeError):
        return None


def coerce_float(value: object) -> float | None:
    """Convert a value to ``float``, returning ``None`` for NaN/Inf/invalid.

    No locale logic — a plain ``float()`` in a try/except.  Use this for
    already-machine-formatted values (yfinance fields, DB columns), and
    :func:`parse_number` for human/broker-formatted strings.
    """
    if value is None:
        return None
    try:
        f = float(value)  # type: ignore[arg-type]
        return None if math.isnan(f) or math.isinf(f) else f
    except (ValueError, TypeError):
        return None
