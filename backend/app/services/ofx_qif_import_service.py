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
from app.utils.dates import infer_dayfirst, parse_date
from app.utils.numbers import parse_number

logger = logging.getLogger(__name__)

# Exchange is not reliably carried by OFX/QIF investment records; default to the
# app's primary market. Cash/bank fallback rows use a distinct "CASH" exchange.
_DEFAULT_EXCHANGE = "NSE"

# Bank-statement lines are parsed (so a caller can see what a file contains and
# report it), but they are NOT positions: the "symbol" is a payee, the quantity
# is a placeholder 1.0 and the "price" is a cash amount. Feeding them to
# ``import_to_portfolio`` would create one junk holding per payee and add every
# credit to Total Invested — see :func:`split_cash_rows`.
CASH_EXCHANGE = "CASH"

# Numeric fields are parsed with the shared locale-aware parser so European
# statements ("1234,56") are read as 1234.56 rather than 123456.0.
_safe_float = parse_number


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
    mapping each cash movement to a single-unit pseudo-transaction tagged
    ``exchange == "CASH"``. Those cash rows are reported, not imported — see
    :func:`import_statement`. Returns ``[]`` when nothing usable is found.
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
            "exchange": CASH_EXCHANGE,
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

def _normalize_qif_date(value: str) -> str:
    """Normalize a raw QIF date string: strip spaces and rewrite the classic
    Quicken apostrophe year separator (``01/15'24`` → ``01/15/24``)."""
    return value.strip().replace(" ", "").replace("'", "/")


def _parse_qif_date(value: str | None, *, dayfirst: bool = True) -> date | None:
    """Parse a QIF date (``MM/DD'YY``, ``MM/DD/YYYY``, ``D/M/YYYY``, …) using
    one consistent day/month convention for the whole file.

    ``dayfirst`` comes from :func:`infer_dayfirst` over all of the file's
    D-records (defaulting to day-first when ambiguous — the app's primary
    markets are India/Germany), so ``13/04`` and ``05/04`` in the same file
    are read with a single convention instead of per-row format guessing.
    """
    if not value:
        return None
    s = _normalize_qif_date(value)
    parts = s.split("/")
    if len(parts) == 3 and len(parts[2]) <= 2:
        # Two-digit year (e.g. "01/15/24" from "01/15'24"): handle locally —
        # strptime's %Y would happily read "24" as the year 24 AD.
        fmts = ("%d/%m/%y", "%m/%d/%y") if dayfirst else ("%m/%d/%y", "%d/%m/%y")
        for fmt in fmts:
            try:
                return datetime.strptime(s, fmt).date()
            except ValueError:
                continue
        return None
    return parse_date(s, dayfirst=dayfirst)


def _build_qif_row(
    fields: dict[str, str],
    acct_type: str | None,
    *,
    dayfirst: bool = True,
) -> dict | None:
    """Turn one QIF record's field map into an import row (or None to skip)."""
    dt = _parse_qif_date(fields.get("D"), dayfirst=dayfirst)
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
        "exchange": CASH_EXCHANGE,
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

    Dates are parsed with a single day/month convention for the whole file:
    all D-records are collected first, :func:`infer_dayfirst` decides the
    convention once (day-first when ambiguous), and every row is parsed with
    it — a per-row format guess would silently mix ``MM/DD`` and ``DD/MM``
    within one statement.
    """
    text = file_bytes.decode("utf-8-sig", errors="ignore")

    # ── Pass 1: collect records (field map + account type in effect) ──
    records: list[tuple[dict[str, str], str | None]] = []
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
            if current:
                records.append((current, acct_type))
            current = {}
            continue
        current[code] = value

    # Flush a trailing record with no closing '^'.
    if current:
        records.append((current, acct_type))

    # ── Decide the file-wide date convention once ─────────────────────
    date_strings = [
        _normalize_qif_date(fields["D"]) for fields, _ in records if fields.get("D")
    ]
    inferred = infer_dayfirst(date_strings)
    dayfirst = True if inferred is None else inferred

    # ── Pass 2: build rows with the fixed convention ──────────────────
    rows: list[dict] = []
    for fields, rec_type in records:
        row = _build_qif_row(fields, rec_type, dayfirst=dayfirst)
        if row:
            rows.append(row)

    return rows


# ---------------------------------------------------------------------------
# Import — delegate to the shared holding/transaction creation logic
# ---------------------------------------------------------------------------

def is_cash_row(row: dict) -> bool:
    """True when a parsed row came from a bank/cash statement line."""
    return str(row.get("exchange") or "").strip().upper() == CASH_EXCHANGE


def split_cash_rows(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split parsed statement rows into ``(investment_rows, cash_rows)``.

    A bank line describes a cash movement to a payee, not a trade in a
    security, so it must never reach the holdings table.
    """
    investment = [row for row in rows if not is_cash_row(row)]
    cash = [row for row in rows if is_cash_row(row)]
    return investment, cash


async def import_statement(
    rows: list[dict],
    portfolio_id: int,
    db: AsyncSession,
    *,
    source: str = "OFX",
) -> dict:
    """Create holdings/transactions from parsed OFX/QIF rows.

    Delegates to ``excel_service.import_to_portfolio`` so creation logic is
    shared with the Excel/CSV importers. ``source`` ("OFX" or "QIF") is
    stamped on every created transaction for provenance.

    Bank/cash rows (``exchange == "CASH"``) are **not** imported: they would
    become one holding per payee, with each credit's full amount landing in
    ``cumulative_quantity``/``average_price`` and therefore in Total Invested
    and Net Worth, and each debit becoming a SELL against a lot that never
    existed. Their count is reported as ``cash_rows_skipped`` so the caller can
    tell the user what was left out instead of silently dropping it.
    """
    investment_rows, cash_rows = split_cash_rows(rows)
    if cash_rows:
        logger.info(
            "%s import: skipping %d bank/cash statement line(s) — not positions",
            source, len(cash_rows),
        )
    summary = await import_to_portfolio(
        investment_rows, portfolio_id, db, source=source
    )
    summary["cash_rows_skipped"] = len(cash_rows)
    return summary
