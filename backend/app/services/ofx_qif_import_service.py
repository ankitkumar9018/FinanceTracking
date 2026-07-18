"""OFX / QIF statement import — minimal, dependency-free parsers.

Both parsers emit the same ``list[dict]`` row shape that
``excel_service.import_to_portfolio`` consumes (keys: ``stock_symbol``,
``stock_name``, ``exchange``, ``transaction_type`` (BUY/SELL), ``date``
(a ``datetime.date``), ``quantity``, ``price``, ``brokerage``, ``notes``,
``sector``) so the actual holding/transaction creation logic is reused rather
than reimplemented.

No third-party OFX/QIF libraries are used: OFX is parsed with a tolerant,
SGML-friendly regex approach (aggregates carry closing tags, leaf value
elements may omit them) and QIF with the classic line-code format.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.excel_service import import_to_portfolio

logger = logging.getLogger(__name__)

# Exchange is not reliably carried by OFX/QIF investment records; default to the
# app's primary market. Cash/bank fallback rows use a distinct "CASH" exchange.
_DEFAULT_EXCHANGE = "NSE"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _safe_float(value: object) -> float | None:
    """Coerce a value to float, tolerating thousands separators / currency."""
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    s = (
        str(value)
        .strip()
        .replace(",", "")
        .replace("₹", "")  # ₹
        .replace("$", "")
        .replace("€", "")  # €
    )
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# OFX / QFX
# ---------------------------------------------------------------------------

def _ofx_tag(block: str, tag: str) -> str | None:
    """Extract a single OFX leaf value for ``tag`` from ``block``.

    Handles both closed (``<TAG>v</TAG>``) and SGML-style unclosed
    (``<TAG>v`` followed by a newline/next tag) forms.
    """
    m = re.search(rf"<{re.escape(tag)}>([^<\r\n]*)", block, re.IGNORECASE)
    if not m:
        return None
    return m.group(1).strip() or None


def _parse_ofx_date(value: str | None) -> date | None:
    """Parse an OFX datetime (``YYYYMMDD[HHMMSS[.XXX][tz]]``) to a date."""
    if not value:
        return None
    digits = re.sub(r"[^0-9]", "", value)
    if len(digits) < 8:
        return None
    try:
        return datetime.strptime(digits[:8], "%Y%m%d").date()
    except ValueError:
        return None


def parse_ofx(file_bytes: bytes) -> list[dict]:
    """Parse an OFX/QFX statement into import rows.

    Prefers investment transactions (``BUYSTOCK``/``BUYMF``/``SELLSTOCK``/…);
    if none are present, falls back to bank statement lines (``STMTTRN``),
    mapping each cash movement to a single-unit pseudo-transaction. Returns
    ``[]`` when nothing usable is found.
    """
    text = file_bytes.decode("utf-8", errors="ignore")

    # Build UNIQUEID -> {ticker, name} map from the security list.
    sec_map: dict[str, dict] = {}
    for block in re.findall(r"<SECINFO>(.*?)</SECINFO>", text, re.IGNORECASE | re.DOTALL):
        uid = _ofx_tag(block, "UNIQUEID")
        if uid:
            sec_map[uid] = {
                "ticker": _ofx_tag(block, "TICKER"),
                "name": _ofx_tag(block, "SECNAME"),
            }

    rows: list[dict] = []

    # ── Investment buy/sell aggregates ────────────────────────────────
    for m in re.finditer(
        r"<(BUY|SELL)(STOCK|MF|DEBT|OPT|OTHER)>(.*?)</\1\2>",
        text,
        re.IGNORECASE | re.DOTALL,
    ):
        action = m.group(1).upper()  # BUY / SELL
        block = m.group(3)

        units = _safe_float(_ofx_tag(block, "UNITS"))
        price = _safe_float(_ofx_tag(block, "UNITPRICE"))
        dt = _parse_ofx_date(_ofx_tag(block, "DTTRADE") or _ofx_tag(block, "DTSETTLE"))
        if units is None or price is None or dt is None:
            continue

        commission = (
            _safe_float(_ofx_tag(block, "COMMISSION"))
            or _safe_float(_ofx_tag(block, "FEES"))
            or 0.0
        )
        uid = _ofx_tag(block, "UNIQUEID") or ""
        sec = sec_map.get(uid, {})
        symbol = (sec.get("ticker") or uid).strip().upper()
        if not symbol:
            continue
        name = (sec.get("name") or symbol).strip()

        rows.append({
            "stock_symbol": symbol,
            "stock_name": name,
            "exchange": _DEFAULT_EXCHANGE,
            "transaction_type": action,
            "date": dt,
            "quantity": abs(units),
            "price": abs(price),
            "brokerage": abs(commission),
            "notes": "Imported from OFX",
            "sector": None,
        })

    if rows:
        return rows

    # ── Bank statement fallback ───────────────────────────────────────
    for block in re.findall(r"<STMTTRN>(.*?)</STMTTRN>", text, re.IGNORECASE | re.DOTALL):
        amount = _safe_float(_ofx_tag(block, "TRNAMT"))
        dt = _parse_ofx_date(_ofx_tag(block, "DTPOSTED"))
        if amount is None or dt is None:
            continue
        payee = (_ofx_tag(block, "NAME") or _ofx_tag(block, "MEMO") or "CASH").strip()
        symbol = payee.upper()[:50] or "CASH"
        rows.append({
            "stock_symbol": symbol,
            "stock_name": payee,
            "exchange": "CASH",
            "transaction_type": "BUY" if amount >= 0 else "SELL",
            "date": dt,
            "quantity": 1.0,
            "price": abs(amount),
            "brokerage": 0.0,
            "notes": (_ofx_tag(block, "MEMO") or "Imported from OFX (bank)"),
            "sector": None,
        })

    return rows


# ---------------------------------------------------------------------------
# QIF
# ---------------------------------------------------------------------------

_QIF_DATE_FORMATS = (
    "%m/%d'%y",
    "%m/%d'%Y",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%d/%m/%Y",
    "%d/%m/%y",
    "%Y-%m-%d",
)


def _parse_qif_date(value: str | None) -> date | None:
    """Parse a QIF date (``MM/DD'YY``, ``MM/DD/YYYY``, ``D/M/YYYY``, …)."""
    if not value:
        return None
    s = value.strip().replace(" ", "")
    for fmt in _QIF_DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _build_qif_row(fields: dict[str, str], acct_type: str | None) -> dict | None:
    """Turn one QIF record's field map into an import row (or None to skip)."""
    dt = _parse_qif_date(fields.get("D"))
    if dt is None:
        return None

    is_invest = acct_type == "invest" or bool(fields.get("Y"))

    if is_invest:
        action = (fields.get("N") or "").strip().lower()
        if action.startswith("buy") or action in ("shrsin", "reinvsh", "reinvdiv", "reinvlg"):
            tx_type = "BUY"
        elif action.startswith("sell") or action == "shrsout":
            tx_type = "SELL"
        else:
            return None  # dividends, transfers, etc. don't map to a BUY/SELL

        name = (fields.get("Y") or "").strip()
        if not name:
            return None
        qty = _safe_float(fields.get("Q"))
        price = _safe_float(fields.get("I"))
        amount = _safe_float(fields.get("T"))
        if amount is None:
            amount = _safe_float(fields.get("U"))
        # Derive a missing price from amount / quantity when possible.
        if price is None and qty and amount:
            price = abs(amount) / abs(qty)
        if qty is None or price is None:
            return None

        symbol = (re.sub(r"\s+", "", name).upper()[:50]) or name.upper()[:50]
        commission = _safe_float(fields.get("O")) or 0.0
        return {
            "stock_symbol": symbol,
            "stock_name": name,
            "exchange": _DEFAULT_EXCHANGE,
            "transaction_type": tx_type,
            "date": dt,
            "quantity": abs(qty),
            "price": abs(price),
            "brokerage": abs(commission),
            "notes": (fields.get("M") or "Imported from QIF").strip(),
            "sector": None,
        }

    # Bank / cash record
    amount = _safe_float(fields.get("T"))
    if amount is None:
        amount = _safe_float(fields.get("U"))
    if amount is None:
        return None
    payee = (fields.get("P") or fields.get("M") or "CASH").strip()
    symbol = payee.upper()[:50] or "CASH"
    return {
        "stock_symbol": symbol,
        "stock_name": payee,
        "exchange": "CASH",
        "transaction_type": "BUY" if amount >= 0 else "SELL",
        "date": dt,
        "quantity": 1.0,
        "price": abs(amount),
        "brokerage": 0.0,
        "notes": (fields.get("M") or "Imported from QIF (bank)").strip(),
        "sector": None,
    }


def parse_qif(file_bytes: bytes) -> list[dict]:
    """Parse a QIF file (``!Type:Invest`` or a basic bank type) into rows.

    Records are separated by ``^``. Returns ``[]`` when nothing usable is
    found.
    """
    text = file_bytes.decode("utf-8-sig", errors="ignore")
    rows: list[dict] = []
    acct_type: str | None = None
    current: dict[str, str] = {}

    for raw in text.splitlines():
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        if line.startswith("!"):
            header = line[1:].strip().lower()
            if header.startswith("type:"):
                acct_type = "invest" if "invest" in header else "bank"
            # Ignore !Account / !Option / etc. headers.
            continue
        code = line[0]
        value = line[1:].strip()
        if code == "^":
            row = _build_qif_row(current, acct_type)
            if row:
                rows.append(row)
            current = {}
            continue
        current[code] = value

    # Flush a trailing record with no closing '^'.
    if current:
        row = _build_qif_row(current, acct_type)
        if row:
            rows.append(row)

    return rows


# ---------------------------------------------------------------------------
# Import — delegate to the shared holding/transaction creation logic
# ---------------------------------------------------------------------------

async def import_statement(
    rows: list[dict],
    portfolio_id: int,
    db: AsyncSession,
) -> dict:
    """Create holdings/transactions from parsed OFX/QIF rows.

    Delegates to ``excel_service.import_to_portfolio`` so creation logic is
    shared with the Excel/CSV importers.
    """
    return await import_to_portfolio(rows, portfolio_id, db)
