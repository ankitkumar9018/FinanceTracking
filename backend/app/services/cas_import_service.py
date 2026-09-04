"""CAS (CAMS / KFintech Consolidated Account Statement) PDF import.

Uses the optional ``casparser`` package (declared in the ``mf`` extra of
pyproject.toml). The import is kept function-local so the app boots fine
without it; ``parse_cas`` raises a clear ``RuntimeError`` with an install hint
when the package is missing, which the API layer maps to HTTP 501.

Parsed schemes are returned in the mutual-fund import dict shape consumed by
``csv_import_service.import_mutual_funds`` (keys: ``scheme_code``,
``scheme_name``, ``folio_number``, ``units``, ``nav``, ``invested_amount``).
"""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Any

logger = logging.getLogger(__name__)


def _get(obj: object, key: str) -> Any:
    """Read ``key`` from a dict or an attribute from an object (casparser
    returns dicts with ``output='dict'`` but objects otherwise).

    Returns ``Any`` because casparser's parsed structure is dynamic (nested
    dicts/objects of folios, schemes and valuations) — callers narrow via the
    ``or []`` / ``_num`` coercions below.
    """
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _num(value: object) -> float | None:
    """Coerce a value to float, returning None on failure."""
    if value is None:
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _cost_from_transactions(scheme: object) -> float | None:
    """Derive a cost basis by replaying the scheme's CAS transaction section.

    CAS statements carry a per-scheme transaction list (purchases, SIP
    instalments, switch-ins, redemptions, switch-outs). Purchases have positive
    ``units``, redemptions negative. Replaying them keeps a running
    (units, cost) pair and reduces cost proportionally on the way out, which is
    the same weighted-average basis the rest of the app uses.

    Returns ``None`` when the statement has no usable transaction rows.
    """
    transactions = _get(scheme, "transactions") or []
    units_held = 0.0
    cost = 0.0
    saw_any = False

    for txn in transactions:
        units = _num(_get(txn, "units"))
        amount = _num(_get(txn, "amount"))
        if not units:
            # Dividend payouts, stamp duty, tax rows: no unit movement, so no
            # effect on the cost basis.
            continue
        if amount is None:
            # A unit movement with no amount (e.g. a bonus allotment) adds
            # units at zero cost rather than invalidating the whole replay.
            amount = 0.0
        saw_any = True
        if units > 0:
            units_held += units
            cost += abs(amount)
        else:
            sold = min(-units, units_held)
            if units_held > 0:
                cost -= cost * (sold / units_held)
            units_held -= sold
            if units_held <= 0:
                units_held = 0.0
                cost = 0.0

    if not saw_any:
        return None
    return round(cost, 4)


def _map_cas_to_mf(data: object) -> list[dict]:
    """Flatten parsed CAS folios/schemes into mutual-fund import rows."""
    rows: list[dict] = []
    folios = _get(data, "folios") or []
    for folio in folios:
        folio_no = str(_get(folio, "folio") or "").strip() or None
        for scheme in (_get(folio, "schemes") or []):
            name = str(_get(scheme, "scheme") or "").strip()
            amfi = _get(scheme, "amfi")
            isin = _get(scheme, "isin")
            code = str(amfi or isin or name or "").strip()
            if not name or not code:
                continue

            units = _num(_get(scheme, "close"))
            if units is None:
                continue

            valuation = _get(scheme, "valuation") or {}
            nav = _num(_get(valuation, "nav"))
            value = _num(_get(valuation, "value"))
            invested = _num(_get(valuation, "cost"))

            # A missing cost figure used to fall back to the CURRENT valuation
            # (``value``, or units * nav) — which is the market value, not the
            # amount invested, so every such fund imported showing exactly zero
            # gain/loss. Replay the statement's own transaction section
            # instead; only if that is unavailable do we fall back, and then
            # the row is flagged as an estimate.
            estimated = False
            if invested is None:
                invested = _cost_from_transactions(scheme)
            if invested is None:
                estimated = True
                invested = value if value is not None else units * (nav or 0.0)
                logger.warning(
                    "CAS scheme %s (folio %s) has no cost and no transaction "
                    "history; invested_amount falls back to current value "
                    "%.2f and will show zero gain/loss",
                    name,
                    folio_no,
                    invested,
                )

            rows.append({
                "scheme_code": code,
                "scheme_name": name,
                "folio_number": folio_no,
                "units": units,
                "nav": nav if nav is not None else 0.0,
                "invested_amount": invested,
                # Consumed by nothing yet: the MF upsert in
                # csv_import_service.import_mutual_funds should use it to stop
                # overwriting a user's real cost with a derived one (see the
                # handoff note in the stream report).
                "invested_amount_is_estimate": estimated,
            })
    return rows


def parse_cas(file_bytes: bytes, password: str | None) -> list[dict]:
    """Parse a password-protected CAMS/KFintech CAS PDF into MF import rows.

    Raises ``RuntimeError`` (with an install hint) when ``casparser`` is not
    installed. Other parse/decrypt failures propagate as exceptions for the
    caller to translate into an HTTP 400.
    """
    try:
        import casparser
    except ImportError as exc:  # pragma: no cover - depends on optional extra
        raise RuntimeError(
            "CAS import requires the 'casparser' package. "
            "Install the 'cas' extra: uv sync --extra cas"
        ) from exc

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            # Record the path BEFORE writing: NamedTemporaryFile creates the file
            # on disk the moment it opens (delete=False keeps it), so if the write
            # itself fails (e.g. ENOSPC) the finally-block must still be able to
            # unlink it. Assigning after write would leak the file on that path.
            tmp_path = tmp.name
            tmp.write(file_bytes)
        data = casparser.read_cas_pdf(tmp_path, password or "", output="dict")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:  # pragma: no cover
                logger.debug("Failed to remove temp CAS file %s", tmp_path, exc_info=True)

    return _map_cas_to_mf(data)
