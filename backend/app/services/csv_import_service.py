"""CSV import service — parse CSV files for holdings, dividends, mutual funds, and tax records."""

from __future__ import annotations

import csv
import io
import logging
import re
from collections import defaultdict
from collections.abc import Mapping
from datetime import date as date_cls
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dividend import Dividend
from app.models.holding import Holding
from app.models.mutual_fund import MutualFund
from app.models.tax_record import TaxRecord
from app.utils.dates import parse_date
from app.utils.numbers import parse_number

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column definitions
# ---------------------------------------------------------------------------

_HOLDINGS_COLUMNS = [
    "stock_symbol", "stock_name", "exchange", "transaction_type", "date",
    "quantity", "price", "brokerage", "lower_mid_range_1", "lower_mid_range_2",
    "upper_mid_range_1", "upper_mid_range_2", "base_level", "top_level",
    "sector", "notes",
]

_DIVIDEND_COLUMNS = [
    "stock_symbol", "exchange", "ex_date", "payment_date",
    "amount_per_share", "total_amount", "is_reinvested",
    "reinvest_price", "reinvest_shares",
]

_MUTUAL_FUND_COLUMNS = [
    "scheme_code", "scheme_name", "folio_number",
    "units", "nav", "invested_amount",
]

_TAX_RECORD_COLUMNS = [
    "financial_year", "tax_jurisdiction", "gain_type", "purchase_date",
    "sale_date", "purchase_price", "sale_price", "gain_amount",
    "tax_amount", "currency",
]


# ---------------------------------------------------------------------------
# Header aliasing — the single source of truth for BOTH importers
# ---------------------------------------------------------------------------
#
# Our own exports write human-readable headers ("Stock Symbol", "Avg Price",
# "Type"), while the import templates use machine keys ("stock_symbol",
# "price", "transaction_type").  Without aliasing, re-importing an export
# fails with "No valid data rows found".  ``excel_service`` imports these
# helpers rather than duplicating the map.
#
# Keys are the *normalized* header form produced by :func:`_normalize_header`
# (lowercase, punctuation dropped, words space-separated).  Anything not in
# the map falls back to ``"_".join(words)``, which reproduces the previous
# ``header.strip().lower().replace(" ", "_")`` behaviour — so every existing
# template header keeps mapping to itself (zero regression).
_COLUMN_ALIASES: dict[str, str] = {
    # identity/canonical
    "stock symbol": "stock_symbol",
    "stock name": "stock_name",
    "transaction type": "transaction_type",
    # symbol
    "symbol": "stock_symbol",
    "ticker": "stock_symbol",
    "scrip": "stock_symbol",
    "instrument": "stock_symbol",
    # name
    "name": "stock_name",
    "company": "stock_name",
    "company name": "stock_name",
    "security name": "stock_name",
    # exchange
    "exchange": "exchange",
    "exchange code": "exchange",
    # transaction type  (NB: "action" is deliberately NOT aliased — the
    # holdings export uses it for the action-needed zone, not BUY/SELL)
    "type": "transaction_type",
    "trade type": "transaction_type",
    "txn type": "transaction_type",
    "order type": "transaction_type",
    # date
    "date": "date",
    "transaction date": "date",
    "trade date": "date",
    "txn date": "date",
    # quantity
    "quantity": "quantity",
    "qty": "quantity",
    "shares": "quantity",
    "no of shares": "quantity",
    # price
    "price": "price",
    "avg price": "price",
    "average price": "price",
    "avg cost": "price",
    "average cost": "price",
    "buy price": "price",
    "unit price": "price",
    "price per unit": "price",
    "rate": "price",
    # brokerage
    "brokerage": "brokerage",
    "fees": "brokerage",
    "fee": "brokerage",
    "commission": "brokerage",
    "charges": "brokerage",
    # range levels (Excel export shortens the template names)
    "lower mid 1": "lower_mid_range_1",
    "lower mid 2": "lower_mid_range_2",
    "upper mid 1": "upper_mid_range_1",
    "upper mid 2": "upper_mid_range_2",
    # free text
    "sector": "sector",
    "notes": "notes",
    "note": "notes",
    "remarks": "notes",
    "comment": "notes",
    "comments": "notes",
}

_NON_ALNUM = re.compile(r"[^0-9a-z]+")


def _normalize_header(header: object) -> str:
    """Lowercase a header and reduce it to space-separated alphanumeric words.

    ``"P&L %"`` → ``"p l"``, ``"Avg Price"`` → ``"avg price"``,
    ``"stock_symbol"`` → ``"stock symbol"``.
    """
    if header is None:
        return ""
    return _NON_ALNUM.sub(" ", str(header).strip().lower()).strip()


def canonical_column(header: object) -> str:
    """Map any supported spelling of a column header to its canonical key.

    Unknown headers are snake_cased and passed through untouched so extra
    export-only columns (``current_price``, ``rsi``, ``action_needed``, …)
    are simply ignored downstream instead of breaking the import.
    """
    words = _normalize_header(header)
    if not words:
        return ""
    return _COLUMN_ALIASES.get(words, words.replace(" ", "_"))


def canonicalize_row(row: Mapping) -> dict:
    """Return a copy of ``row`` with its keys mapped to canonical column keys.

    When two source columns collapse onto the same canonical key, the first
    non-blank value wins (e.g. a file carrying both ``price`` and
    ``avg_price``).
    """
    out: dict = {}
    for key, value in row.items():
        canonical = canonical_column(key)
        if not canonical:
            continue
        if canonical in out and not is_blank(out[canonical]):
            continue
        out[canonical] = value
    return out


def is_blank(value: object) -> bool:
    """True when a cell carries no data.

    A numeric ``0`` is *not* blank — a bonus/IPO allotment at price 0 is a
    legitimate row.
    """
    return value is None or (isinstance(value, str) and not value.strip())


def text_or_none(value: object) -> str | None:
    """Stringify a free-text cell, collapsing blanks (and ``None``) to ``None``."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_transaction_fields(row: dict) -> str:
    """Fill in the fields a position snapshot omits; classify the row.

    Returns one of:

    ``"transaction"``
        A full ledger row (type + date present) — imported as-is.
    ``"snapshot"``
        A position-snapshot row (our holdings CSV / the "Holdings" sheet):
        quantity + average price with **no** transaction type or date.  It is
        materialised as a single opening ``BUY`` of ``quantity`` at the
        average price, dated **today** — the export carries no acquisition
        date, and today is the only defensible stand-in (it is also the date
        on which the snapshot was taken).  Consequence to be aware of:
        re-importing the same snapshot on a *later* day creates a second
        opening BUY, because the transaction-fingerprint dedup in
        ``excel_service.import_to_portfolio`` includes the date.  Same-day
        re-imports are deduped correctly.
    ``"invalid"``
        A partial row (type without date, or date without type) — the caller
        skips it, exactly as before.

    ``stock_name`` is defaulted to ``stock_symbol`` when absent, because the
    transactions export identifies a position by symbol + exchange and does
    not repeat the display name.
    """
    if is_blank(row.get("stock_name")):
        row["stock_name"] = row.get("stock_symbol")

    has_type = not is_blank(row.get("transaction_type"))
    has_date = not is_blank(row.get("date"))
    if has_type and has_date:
        return "transaction"
    if has_type or has_date:
        return "invalid"

    row["transaction_type"] = "BUY"
    row["date"] = date_cls.today()
    return "snapshot"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Date/number parsing now lives in the shared utils (they were ported from
# this module verbatim); the local names are kept for compatibility with
# existing imports and call sites.
_parse_date = parse_date
_safe_float = parse_number


def _parse_bool(value: object) -> bool:
    """Parse a boolean from various representations."""
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    return s in ("yes", "true", "1", "y")


_QUANT4 = Decimal("0.0001")


def _round4_variants(value: object) -> tuple[object, ...]:
    """Every scale-4 form a value may take once the database has stored it.

    The money columns natural keys are built from are ``Numeric(18, 4)``, so a
    full-precision CSV float has to be normalised to scale 4 before it can be
    compared with what comes back out of the column. The catch is that the two
    backends round a tie differently, and the CSV side cannot know which one it
    is talking to:

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


def _round4(value: object) -> object:
    """Canonical scale-4 form of a numeric — see :func:`_round4_variants`.

    Values read back from the database are already at scale 4, so quantizing
    them again is the identity and this single form is exact for them.
    """
    return _round4_variants(value)[0]


def _decode_csv_bytes(file_bytes: bytes) -> str:
    """Decode raw CSV bytes using a tolerant fallback chain.

    Tries ``utf-8-sig`` first (handles the BOM Excel prepends), then the common
    Windows/Western-European single-byte encodings ``cp1252`` and ``latin-1``.
    ``latin-1`` maps every byte, so it never raises — guaranteeing we return a
    string instead of a 500 UnicodeDecodeError on non-UTF-8 broker exports.
    """
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    # Should be unreachable (latin-1 accepts all bytes) — last-resort safety net.
    return file_bytes.decode("utf-8", errors="replace")


def _read_csv(file_bytes: bytes) -> list[dict]:
    """Read CSV bytes into a list of row dicts with normalized header names."""
    text = _decode_csv_bytes(file_bytes)
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict] = []
    for raw_row in reader:
        row: dict = {}
        for key, value in raw_row.items():
            if key is None:
                continue
            normalized_key = key.strip().lower().replace(" ", "_")
            row[normalized_key] = value.strip() if isinstance(value, str) else value
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Parse CSV — Holdings / Transactions (same format as Excel)
# ---------------------------------------------------------------------------

def parse_csv(file_bytes: bytes) -> list[dict]:
    """Parse a CSV file with the same column layout as the Excel template.

    Header spellings are canonicalised (see :func:`canonical_column`), so both
    the import template (``stock_symbol``, ``transaction_type``, …) and our own
    human-readable exports (``Stock Symbol``, ``Type``, ``Avg Price``, …) are
    accepted.  A row with neither a transaction type nor a date is treated as a
    position snapshot — see :func:`normalize_transaction_fields`.

    Returns the same list[dict] structure as parse_excel() so that
    import_to_portfolio() can be reused directly.
    """
    rows = _read_csv(file_bytes)
    parsed: list[dict] = []

    for raw_row in rows:
        row = canonicalize_row(raw_row)
        symbol = row.get("stock_symbol")
        exchange = row.get("exchange")
        qty = row.get("quantity")
        price = row.get("price")

        if any(is_blank(v) for v in (symbol, exchange, qty, price)):
            logger.warning("Skipping CSV row with missing required fields: %s", row)
            continue

        kind = normalize_transaction_fields(row)
        if kind == "invalid":
            logger.warning("Skipping CSV row with a partial transaction: %s", row)
            continue

        name = row["stock_name"]
        tx_type = row["transaction_type"]
        tx_date = row["date"]

        row["stock_symbol"] = str(symbol).strip().upper()
        row["stock_name"] = str(name).strip()
        row["exchange"] = str(exchange).strip().upper()
        row["transaction_type"] = str(tx_type).strip().upper()
        if row["transaction_type"] not in ("BUY", "SELL"):
            logger.warning("Invalid transaction type '%s' in CSV row, skipping", tx_type)
            continue

        parsed_date = _parse_date(tx_date)
        if parsed_date is None:
            logger.warning("Invalid date '%s' in CSV row, skipping", tx_date)
            continue
        row["date"] = parsed_date

        # Locale-aware parse (handles "1234,56" and "1.234,56" as well as US).
        qty_val = _safe_float(qty)
        price_val = _safe_float(price)
        if qty_val is None or price_val is None:
            logger.warning("Non-numeric quantity/price in CSV row, skipping: %s", row)
            continue
        if qty_val == 0:
            # A zero-quantity row carries no position and no trade (a fully
            # exited holding still appears in the holdings export).
            logger.info("Skipping zero-quantity CSV row: %s", symbol)
            continue
        row["quantity"] = qty_val
        row["price"] = price_val
        brokerage_val = _safe_float(row.get("brokerage"))
        row["brokerage"] = brokerage_val if brokerage_val is not None else 0.0

        # Optional numeric fields
        for field in (
            "lower_mid_range_1", "lower_mid_range_2",
            "upper_mid_range_1", "upper_mid_range_2",
            "base_level", "top_level",
        ):
            row[field] = _safe_float(row.get(field))

        row["sector"] = text_or_none(row.get("sector"))
        row["notes"] = text_or_none(row.get("notes"))

        parsed.append(row)

    return parsed


def generate_csv_template() -> str:
    """Generate a CSV template string with headers and a sample row."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_HOLDINGS_COLUMNS)
    writer.writerow([
        "RELIANCE", "Reliance Industries Ltd", "NSE", "BUY", "2024-01-15",
        10, 2500.00, 50.00, 2300.00, 2100.00, 2700.00, 2900.00,
        2000.00, 3000.00, "Energy", "Initial purchase",
    ])
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Parse & Import CSV — Dividends
# ---------------------------------------------------------------------------

def parse_csv_dividends(file_bytes: bytes) -> list[dict]:
    """Parse a CSV file containing dividend records."""
    rows = _read_csv(file_bytes)
    parsed: list[dict] = []

    for row in rows:
        symbol = row.get("stock_symbol")
        exchange = row.get("exchange")
        ex_date = _parse_date(row.get("ex_date"))
        amount_per_share = _safe_float(row.get("amount_per_share"))
        total_amount = _safe_float(row.get("total_amount"))

        if not all(
            [symbol, exchange, ex_date, amount_per_share is not None, total_amount is not None]
        ):
            logger.warning("Skipping dividend CSV row with missing fields: %s", row)
            continue

        parsed.append({
            "stock_symbol": str(symbol).strip().upper(),
            "exchange": str(exchange).strip().upper(),
            "ex_date": ex_date,
            "payment_date": _parse_date(row.get("payment_date")),
            "amount_per_share": amount_per_share,
            "total_amount": total_amount,
            "is_reinvested": _parse_bool(row.get("is_reinvested", "no")),
            "reinvest_price": _safe_float(row.get("reinvest_price")),
            "reinvest_shares": _safe_float(row.get("reinvest_shares")),
        })

    return parsed


async def import_dividends(
    parsed_data: list[dict], portfolio_id: int, db: AsyncSession
) -> dict:
    """Import dividend records, looking up holdings by symbol+exchange.

    Re-importing the same file must not double-count: rows matching an
    existing dividend on (holding, ex_date, total_amount) are skipped and
    reported via ``dividends_skipped``.
    """
    result = await db.execute(
        select(Holding).where(Holding.portfolio_id == portfolio_id)
    )
    holdings = result.scalars().all()
    holding_map = {f"{h.stock_symbol}|{h.exchange}": h for h in holdings}

    # Preload existing dividend fingerprints for this portfolio's holdings so
    # a re-import of the same CSV skips instead of inserting duplicates.
    seen: set[tuple[int, object, float]] = set()
    if holdings:
        existing = await db.execute(
            select(Dividend).where(
                Dividend.holding_id.in_([h.id for h in holdings])
            )
        )
        for d in existing.scalars().all():
            seen.add((d.holding_id, d.ex_date, round(float(d.total_amount), 4)))

    created = 0
    skipped = 0

    for row in parsed_data:
        key = f"{row['stock_symbol']}|{row['exchange']}"
        holding = holding_map.get(key)
        if holding is None:
            logger.warning("No holding found for %s, skipping dividend", key)
            skipped += 1
            continue

        fingerprint = (
            holding.id,
            row["ex_date"],
            round(float(row["total_amount"]), 4),
        )
        if fingerprint in seen:
            skipped += 1
            continue
        seen.add(fingerprint)

        div = Dividend(
            holding_id=holding.id,
            ex_date=row["ex_date"],
            payment_date=row["payment_date"],
            amount_per_share=row["amount_per_share"],
            total_amount=row["total_amount"],
            is_reinvested=row["is_reinvested"],
            reinvest_price=row["reinvest_price"],
            reinvest_shares=row["reinvest_shares"],
        )
        db.add(div)
        created += 1

    await db.flush()
    return {"dividends_created": created, "dividends_skipped": skipped}


def generate_dividend_template() -> str:
    """Generate a CSV template for dividend imports."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_DIVIDEND_COLUMNS)
    writer.writerow([
        "RELIANCE", "NSE", "2024-06-15", "2024-07-01",
        10.50, 105.00, "no", "", "",
    ])
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Parse & Import CSV — Mutual Funds
# ---------------------------------------------------------------------------

def parse_csv_mutual_funds(file_bytes: bytes) -> list[dict]:
    """Parse a CSV file containing mutual fund records."""
    rows = _read_csv(file_bytes)
    parsed: list[dict] = []

    for row in rows:
        scheme_code = row.get("scheme_code")
        scheme_name = row.get("scheme_name")
        units = _safe_float(row.get("units"))
        nav = _safe_float(row.get("nav"))
        invested = _safe_float(row.get("invested_amount"))

        if not all(
            [scheme_code, scheme_name, units is not None, nav is not None, invested is not None]
        ):
            logger.warning("Skipping MF CSV row with missing fields: %s", row)
            continue

        parsed.append({
            "scheme_code": str(scheme_code).strip(),
            "scheme_name": str(scheme_name).strip(),
            "folio_number": str(row.get("folio_number", "")).strip() or None,
            "units": units,
            "nav": nav,
            "invested_amount": invested,
        })

    return parsed


async def import_mutual_funds(
    parsed_data: list[dict], portfolio_id: int, db: AsyncSession
) -> dict:
    """Import mutual fund records, upserting by scheme_code + folio_number."""
    result = await db.execute(
        select(MutualFund).where(MutualFund.portfolio_id == portfolio_id)
    )
    existing = result.scalars().all()
    mf_map = {
        f"{mf.scheme_code}|{mf.folio_number or ''}": mf for mf in existing
    }

    created = 0
    updated = 0

    for row in parsed_data:
        key = f"{row['scheme_code']}|{row['folio_number'] or ''}"
        existing_mf = mf_map.get(key)

        if existing_mf:
            existing_mf.units = row["units"]
            existing_mf.nav = row["nav"]
            existing_mf.invested_amount = row["invested_amount"]
            if row["scheme_name"]:
                existing_mf.scheme_name = row["scheme_name"]
            updated += 1
        else:
            mf = MutualFund(
                portfolio_id=portfolio_id,
                scheme_code=row["scheme_code"],
                scheme_name=row["scheme_name"],
                folio_number=row["folio_number"],
                units=row["units"],
                nav=row["nav"],
                invested_amount=row["invested_amount"],
            )
            db.add(mf)
            created += 1

    await db.flush()
    return {"mutual_funds_created": created, "mutual_funds_updated": updated}


def generate_mutual_fund_template() -> str:
    """Generate a CSV template for mutual fund imports."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_MUTUAL_FUND_COLUMNS)
    writer.writerow([
        "119551", "Axis Bluechip Fund - Direct Growth", "1234567890",
        150.500, 52.35, 7500.00,
    ])
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Parse & Import CSV — Tax Records
# ---------------------------------------------------------------------------

def parse_csv_tax_records(file_bytes: bytes) -> list[dict]:
    """Parse a CSV file containing tax records."""
    rows = _read_csv(file_bytes)
    parsed: list[dict] = []

    for row in rows:
        fy = row.get("financial_year")
        jurisdiction = row.get("tax_jurisdiction")
        gain_type = row.get("gain_type")
        purchase_date = _parse_date(row.get("purchase_date"))
        purchase_price = _safe_float(row.get("purchase_price"))
        currency = row.get("currency")

        if not all(
            [fy, jurisdiction, gain_type, purchase_date, purchase_price is not None, currency]
        ):
            logger.warning("Skipping tax record CSV row with missing fields: %s", row)
            continue

        parsed.append({
            "financial_year": str(fy).strip(),
            "tax_jurisdiction": str(jurisdiction).strip().upper(),
            "gain_type": str(gain_type).strip().upper(),
            "purchase_date": purchase_date,
            "sale_date": _parse_date(row.get("sale_date")),
            "purchase_price": purchase_price,
            "sale_price": _safe_float(row.get("sale_price")),
            "gain_amount": _safe_float(row.get("gain_amount")),
            "tax_amount": _safe_float(row.get("tax_amount")),
            "currency": str(currency).strip().upper(),
        })

    return parsed


def _tax_fingerprint(
    financial_year: object,
    tax_jurisdiction: object,
    gain_type: object,
    purchase_date: object,
    sale_date: object,
    purchase_price: object,
    sale_price: object,
    gain_amount: object,
    currency: object,
) -> tuple[object, ...]:
    """Natural key identifying a tax record for import dedup.

    Same shape ``backup_service`` uses for the very same table, widened by
    jurisdiction / gain type / proceeds / currency — widening only ever reduces
    false skips, so the two write paths stay compatible.

    ``tax_amount`` is deliberately NOT part of the key: a broker that reissues
    a statement with a corrected tax figure for the same disposal must update
    that row, not insert a second copy of the gain.  (``import_tax_records``
    refreshes ``tax_amount`` on a match — see there.)  The model carries no
    symbol or quantity column, so ``purchase_price`` (the aggregated cost
    basis) is the best available stand-in for lot identity.
    """
    return (
        str(financial_year),
        str(tax_jurisdiction).upper(),
        str(gain_type).upper(),
        purchase_date,
        sale_date,
        _round4(purchase_price),
        _round4(sale_price),
        _round4(gain_amount),
        str(currency).upper(),
    )


def _tax_fingerprint_candidates(row: Mapping) -> list[tuple[object, ...]]:
    """Every natural key a parsed CSV row could match an existing record under.

    One per combination of the scale-4 roundings in :func:`_round4_variants` —
    a single key in all but the exact-half tie cases, where the CSV float and
    the stored column can legitimately disagree in the 4th decimal.
    """
    head = (
        str(row["financial_year"]),
        str(row["tax_jurisdiction"]).upper(),
        str(row["gain_type"]).upper(),
        row["purchase_date"],
        row["sale_date"],
    )
    tail = (str(row["currency"]).upper(),)
    candidates: list[tuple[object, ...]] = []
    for purchase in _round4_variants(row["purchase_price"]):
        for sale in _round4_variants(row["sale_price"]):
            for gain in _round4_variants(row["gain_amount"]):
                key = (*head, purchase, sale, gain, *tail)
                if key not in candidates:
                    candidates.append(key)
    return candidates


def _describe_tax_row(row: Mapping) -> str:
    """One-line human description of a CSV row, for the skipped-rows report."""
    sale = row.get("sale_date")
    return (
        f"{row.get('gain_type')} {row.get('purchase_date')}"
        f"->{sale if sale else 'open'} "
        f"gain {row.get('gain_amount')} {row.get('currency')} "
        f"({row.get('financial_year')}/{row.get('tax_jurisdiction')})"
    )


# Cap on how many skipped rows are echoed back, so a huge re-upload cannot
# return a megabyte of detail.
_MAX_SKIP_DETAIL = 25


async def import_tax_records(
    parsed_data: list[dict],
    user_id: int,
    db: AsyncSession,
    allow_duplicates: bool = False,
) -> dict:
    """Import tax records, skipping rows the user already has.

    Re-importing the same file must not double-count.  A row matching an
    existing *imported* record on the natural key (financial year, jurisdiction,
    gain type, purchase/sale dates, cost basis, proceeds, gain, currency) is
    skipped instead of inserted, so a second upload of the same statement is a
    no-op and the FY summary / ITR export are unchanged.  This matters in money:
    the Rs 1,25,000 s.112A exemption and the EUR 1,000 Sparer-Pauschbetrag are
    both per-assessee-per-year, so a duplicated row wrongly consumes an
    allowance that a later, genuine disposal then has to pay tax on.

    Multiplicity is preserved — matching is a multiset drain, not a set
    membership test — so a file that legitimately contains two identical
    disposals still creates two records on the first upload and skips both on
    the second.

    Only records with ``transaction_id IS NULL`` (i.e. previously imported ones)
    are candidates for a match.  Records the FIFO engine computed from the
    user's own transactions are deliberately excluded: they are deleted and
    rewritten whenever the underlying sale is recomputed, so letting one absorb
    a CSV row would make the imported disposal vanish on the next recompute.
    Over-reporting a gain is visible and repairable; silently dropping one is
    neither.

    On a match the stored ``tax_amount`` is refreshed from the CSV when the file
    carries a different (non-blank) figure, so a corrected broker statement
    still lands without duplicating the gain; the count is reported separately
    as ``tax_records_updated``.

    Pass ``allow_duplicates=True`` to bypass matching entirely — the escape
    hatch for two genuinely distinct disposals whose numbers coincide, which
    this schema cannot otherwise tell apart from a re-upload.

    Returns ``tax_records_created`` / ``tax_records_skipped`` /
    ``tax_records_updated`` plus ``tax_records_skipped_detail``, a capped list
    of one-line descriptions so a partial or repeated import is visible rather
    than silent.
    """
    created = 0
    skipped = 0
    updated = 0
    detail: list[str] = []

    if not parsed_data:
        return {
            "tax_records_created": 0,
            "tax_records_skipped": 0,
            "tax_records_updated": 0,
            "tax_records_skipped_detail": detail,
        }

    # Preload the user's existing IMPORTED records for just the financial years
    # and jurisdictions this file touches — one indexed query per import.
    existing_by_key: dict[tuple[object, ...], list[TaxRecord]] = defaultdict(list)
    if not allow_duplicates:
        result = await db.execute(
            select(TaxRecord).where(
                TaxRecord.user_id == user_id,
                TaxRecord.transaction_id.is_(None),
                TaxRecord.financial_year.in_(
                    {r["financial_year"] for r in parsed_data}
                ),
                TaxRecord.tax_jurisdiction.in_(
                    {r["tax_jurisdiction"] for r in parsed_data}
                ),
            )
        )
        for tr in result.scalars().all():
            existing_by_key[
                _tax_fingerprint(
                    tr.financial_year, tr.tax_jurisdiction, tr.gain_type,
                    tr.purchase_date, tr.sale_date, tr.purchase_price,
                    tr.sale_price, tr.gain_amount, tr.currency,
                )
            ].append(tr)

    for row in parsed_data:
        bucket = next(
            (
                b
                for key in _tax_fingerprint_candidates(row)
                if (b := existing_by_key.get(key))
            ),
            None,
        )
        if bucket:
            # Drain the multiset: this CSV row is accounted for by that record,
            # and a second identical row in the same file will need its own.
            match = bucket.pop()
            skipped += 1
            note = "already imported"
            incoming_tax = row["tax_amount"]
            if incoming_tax is not None and not (
                set(_round4_variants(incoming_tax))
                & set(_round4_variants(match.tax_amount))
            ):
                # Correction to an existing disposal: refresh the tax figure
                # rather than leave a stale number in the ITR export. A blank
                # tax column never wipes a stored value.
                match.tax_amount = incoming_tax
                updated += 1
                note = "already imported; tax_amount updated"
            description = f"{_describe_tax_row(row)} - {note}"
            logger.info("Tax record import skipped: %s", description)
            if len(detail) < _MAX_SKIP_DETAIL:
                detail.append(description)
            continue

        tr = TaxRecord(
            user_id=user_id,
            financial_year=row["financial_year"],
            tax_jurisdiction=row["tax_jurisdiction"],
            gain_type=row["gain_type"],
            purchase_date=row["purchase_date"],
            sale_date=row["sale_date"],
            purchase_price=row["purchase_price"],
            sale_price=row["sale_price"],
            gain_amount=row["gain_amount"],
            tax_amount=row["tax_amount"],
            currency=row["currency"],
        )
        db.add(tr)
        created += 1

    if skipped > len(detail):
        detail.append(f"...and {skipped - len(detail)} more skipped row(s)")

    await db.flush()
    return {
        "tax_records_created": created,
        "tax_records_skipped": skipped,
        "tax_records_updated": updated,
        "tax_records_skipped_detail": detail,
    }


def generate_tax_record_template() -> str:
    """Generate a CSV template for tax record imports."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_TAX_RECORD_COLUMNS)
    writer.writerow([
        "2024-25", "IN", "LTCG", "2023-01-15",
        "2024-06-20", 25000.00, 35000.00, 10000.00, 1250.00, "INR",
    ])
    return buf.getvalue()
