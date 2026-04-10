"""CSV import service — parse CSV files for holdings, dividends, mutual funds, and tax records."""

from __future__ import annotations

import csv
import io
import logging
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dividend import Dividend
from app.models.holding import Holding
from app.models.mutual_fund import MutualFund
from app.models.tax_record import TaxRecord

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
# Helpers
# ---------------------------------------------------------------------------

def _parse_date(value: object) -> date | None:
    """Parse a date from string, datetime, or date object."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        return None
    s = str(value).strip()
    if not s or s in ("-", "N/A", ""):
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _safe_float(value: object) -> float | None:
    """Convert value to float, return None on failure."""
    if value is None:
        return None
    try:
        s = str(value).replace(",", "").replace("₹", "").replace("$", "").replace("€", "").strip()
        if not s:
            return None
        return float(s)
    except (ValueError, TypeError):
        return None


def _parse_bool(value: object) -> bool:
    """Parse a boolean from various representations."""
    if isinstance(value, bool):
        return value
    s = str(value).strip().lower()
    return s in ("yes", "true", "1", "y")


def _read_csv(file_bytes: bytes) -> list[dict]:
    """Read CSV bytes into a list of row dicts with normalized header names."""
    text = file_bytes.decode("utf-8-sig")  # Handle BOM from Excel-exported CSVs
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

    Returns the same list[dict] structure as parse_excel() so that
    import_to_portfolio() can be reused directly.
    """
    rows = _read_csv(file_bytes)
    parsed: list[dict] = []

    for row in rows:
        symbol = row.get("stock_symbol")
        name = row.get("stock_name")
        exchange = row.get("exchange")
        tx_type = row.get("transaction_type")
        tx_date = row.get("date")
        qty = row.get("quantity")
        price = row.get("price")

        if not all([symbol, name, exchange, tx_type, tx_date, qty, price]):
            logger.warning("Skipping CSV row with missing required fields: %s", row)
            continue

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

        try:
            row["quantity"] = float(str(qty).replace(",", ""))
            row["price"] = float(str(price).replace(",", ""))
            row["brokerage"] = float(str(row.get("brokerage") or "0").replace(",", ""))
        except (ValueError, TypeError):
            logger.warning("Non-numeric quantity/price in CSV row, skipping: %s", row)
            continue

        # Optional numeric fields
        for field in (
            "lower_mid_range_1", "lower_mid_range_2",
            "upper_mid_range_1", "upper_mid_range_2",
            "base_level", "top_level",
        ):
            row[field] = _safe_float(row.get(field))

        row["sector"] = str(row.get("sector", "")).strip() or None
        row["notes"] = str(row.get("notes", "")).strip() or None

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

        if not all([symbol, exchange, ex_date, amount_per_share is not None, total_amount is not None]):
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
    """Import dividend records, looking up holdings by symbol+exchange."""
    result = await db.execute(
        select(Holding).where(Holding.portfolio_id == portfolio_id)
    )
    holdings = result.scalars().all()
    holding_map = {f"{h.stock_symbol}|{h.exchange}": h for h in holdings}

    created = 0
    skipped = 0

    for row in parsed_data:
        key = f"{row['stock_symbol']}|{row['exchange']}"
        holding = holding_map.get(key)
        if holding is None:
            logger.warning("No holding found for %s, skipping dividend", key)
            skipped += 1
            continue

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

        if not all([scheme_code, scheme_name, units is not None, nav is not None, invested is not None]):
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

        if not all([fy, jurisdiction, gain_type, purchase_date, purchase_price is not None, currency]):
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


async def import_tax_records(
    parsed_data: list[dict], user_id: int, db: AsyncSession
) -> dict:
    """Import tax records (always inserts, no dedup)."""
    created = 0

    for row in parsed_data:
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

    await db.flush()
    return {"tax_records_created": created}


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
