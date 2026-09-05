"""Shared numeric parsing and money-rounding helpers.

Two parsers with distinct contracts:

- :func:`parse_number` — locale-aware parsing of human/broker-formatted
  strings (currency symbols, US ``1,234.56`` and European ``1.234,56`` /
  ``1234,56`` conventions).  Extracted from
  ``app.services.csv_import_service`` (``_normalize_numeric_str`` +
  ``_safe_float``) with identical semantics so CSV import can delegate to
  it without behavior change.
- :func:`coerce_float` — plain NaN/Inf-safe ``float()`` coercion with no
  locale logic, matching ``app.services.market_data_service._safe_float``.

Plus one pair of rounding helpers, :func:`round4` / :func:`round4_variants`,
used to build the scale-4 natural keys that both write paths into
``tax_records`` (CSV import and JSON backup restore) dedup on.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal

__all__ = ["coerce_float", "parse_number", "round4", "round4_variants"]


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


# ---------------------------------------------------------------------------
# Scale-4 money rounding for natural-key dedup
# ---------------------------------------------------------------------------

_QUANT4 = Decimal("0.0001")


def round4_variants(value: object) -> tuple[object, ...]:
    """Every scale-4 form a value may take once the database has stored it.

    The money columns natural keys are built from are ``Numeric(18, 4)``, so a
    full-precision incoming float (a CSV cell, a JSON backup field) has to be
    normalised to scale 4 before it can be compared with what comes back out of
    the column. The catch is that the two backends round a tie differently, and
    the incoming side cannot know which one it is talking to:

    - PostgreSQL ``numeric`` rounds half away from zero — ``2.50005`` is stored
      as ``2.5001``.
    - SQLite gets the value as a binary double and formats it to 4 places, i.e.
      nearest-with-ties-to-even on the *binary* value — the same ``2.50005`` is
      stored as ``2.5000``.

    So this returns the half-up form first (the canonical key) and the
    binary-rounded form after it when they disagree, which happens only for
    exact-half values at the 5th decimal. Callers look up every variant, so
    dedup works on either backend instead of silently missing.

    ``None`` stays ``None``; a value that is not a number is returned unchanged
    rather than collapsed to ``None``, so two different unparseable values never
    collide into the same key.
    """
    if value is None:
        return (None,)
    try:
        half_up = Decimal(str(value)).quantize(_QUANT4, rounding=ROUND_HALF_UP)
    except (TypeError, ValueError, ArithmeticError):
        return (value,)
    try:
        binary = Decimal(f"{float(value):.4f}")  # type: ignore[arg-type]
    except (TypeError, ValueError, ArithmeticError, OverflowError):
        return (half_up,)
    return (half_up,) if binary == half_up else (half_up, binary)


def round4(value: object) -> object:
    """Canonical scale-4 form of a numeric — see :func:`round4_variants`.

    Values read back from the database are already at scale 4, so quantizing
    them again is the identity and this single form is exact for them.  Build
    the *stored* side of a natural key with this, and look the *incoming* side
    up through every :func:`round4_variants` form.
    """
    return round4_variants(value)[0]
