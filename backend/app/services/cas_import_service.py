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

logger = logging.getLogger(__name__)


def _get(obj: object, key: str) -> object:
    """Read ``key`` from a dict or an attribute from an object (casparser
    returns dicts with ``output='dict'`` but objects otherwise)."""
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
            if invested is None:
                invested = value if value is not None else units * (nav or 0.0)

            rows.append({
                "scheme_code": code,
                "scheme_name": name,
                "folio_number": folio_no,
                "units": units,
                "nav": nav if nav is not None else 0.0,
                "invested_amount": invested,
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
            "Install the 'mf' extra: uv sync --extra mf"
        ) from exc

    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        data = casparser.read_cas_pdf(tmp_path, password or "", output="dict")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:  # pragma: no cover
                logger.debug("Failed to remove temp CAS file %s", tmp_path, exc_info=True)

    return _map_cas_to_mf(data)
