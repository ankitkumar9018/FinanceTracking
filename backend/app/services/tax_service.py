"""Tax service: Indian STCG/LTCG and German Abgeltungssteuer calculation."""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.tax_record import TaxRecord
from app.models.transaction import Transaction

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Indian tax constants
# ---------------------------------------------------------------------------
INDIA_STCG_RATE = 0.20  # 20 % flat
INDIA_LTCG_RATE = 0.125  # 12.5 %
INDIA_LTCG_EXEMPTION = 125_000.0  # Rs 1.25 lakh per FY

# ---------------------------------------------------------------------------
# German tax constants
# ---------------------------------------------------------------------------
GERMANY_KAP_RATE = 0.25  # 25 % Kapitalertragsteuer
GERMANY_SOLI_RATE = 0.055  # 5.5 % Solidaritaetszuschlag on the base tax
GERMANY_CHURCH_RATE = 0.08  # 8 % Kirchensteuer on the base tax (default)
GERMANY_DEFAULT_FREIBETRAG = 1000.0  # EUR 1000 for singles

# Exchange -> jurisdiction mapping
EXCHANGE_JURISDICTION_MAP: dict[str, str] = {
    "NSE": "IN",
    "BSE": "IN",
    "XETRA": "DE",
    "NYSE": "US",
    "NASDAQ": "US",
}

# Exchange -> currency mapping
EXCHANGE_CURRENCY_MAP: dict[str, str] = {
    "NSE": "INR",
    "BSE": "INR",
    "XETRA": "EUR",
    "NYSE": "USD",
    "NASDAQ": "USD",
}


# ---------------------------------------------------------------------------
# Financial year helpers
# ---------------------------------------------------------------------------

def get_financial_year(d: date, jurisdiction: str = "IN") -> str:
    """Return the financial year string for a given date.

    India uses April-March FY (e.g. ``"2024-25"`` for April 2024 - March 2025).
    Germany uses the calendar year (e.g. ``"2024"``).
    """
    if jurisdiction == "DE":
        return str(d.year)

    # Indian FY: April-March
    if d.month >= 4:
        return f"{d.year}-{str(d.year + 1)[-2:]}"
    return f"{d.year - 1}-{str(d.year)[-2:]}"


# ---------------------------------------------------------------------------
# Gain classification
# ---------------------------------------------------------------------------

def classify_gain_type(purchase_date: date, sale_date: date, jurisdiction: str) -> str:
    """Classify the capital gain type based on holding period and jurisdiction.

    India:
        <12 months  -> STCG
        >=12 months -> LTCG
    Germany:
        Always ABGELTUNGSSTEUER (flat tax on capital gains).
    """
    if jurisdiction == "DE":
        return "ABGELTUNGSSTEUER"

    holding_days = (sale_date - purchase_date).days
    if holding_days < 365:
        return "STCG"
    return "LTCG"


# ---------------------------------------------------------------------------
# Indian tax calculation
# ---------------------------------------------------------------------------

def calculate_indian_tax(
    gain_amount: float,
    gain_type: str,
    fy_ltcg_exemption_used: float = 0.0,
) -> dict:
    """Calculate Indian capital gains tax.

    Parameters
    ----------
    gain_amount : float
        The capital gain (positive = profit, negative = loss).
    gain_type : str
        ``"STCG"`` or ``"LTCG"``.
    fy_ltcg_exemption_used : float
        How much of the Rs 1.25 lakh LTCG exemption has already been used
        in this financial year.

    Returns
    -------
    dict
        ``tax_amount``, ``rate_applied``, ``exemption_used``.
    """
    if gain_amount <= 0:
        return {"tax_amount": 0.0, "rate_applied": 0.0, "exemption_used": 0.0}

    if gain_type == "STCG":
        tax = round(gain_amount * INDIA_STCG_RATE, 2)
        return {"tax_amount": tax, "rate_applied": INDIA_STCG_RATE, "exemption_used": 0.0}

    # LTCG: 12.5 % on gains above Rs 1.25 lakh exemption
    remaining_exemption = max(INDIA_LTCG_EXEMPTION - fy_ltcg_exemption_used, 0.0)
    exemption_used = min(gain_amount, remaining_exemption)
    taxable_gain = gain_amount - exemption_used

    tax = round(taxable_gain * INDIA_LTCG_RATE, 2) if taxable_gain > 0 else 0.0
    rate_applied = INDIA_LTCG_RATE if taxable_gain > 0 else 0.0

    return {
        "tax_amount": tax,
        "rate_applied": rate_applied,
        "exemption_used": exemption_used,
    }


# ---------------------------------------------------------------------------
# German tax calculation
# ---------------------------------------------------------------------------

def calculate_german_tax(
    gain_amount: float,
    freibetrag_remaining: float = GERMANY_DEFAULT_FREIBETRAG,
    church_tax: bool = False,
) -> dict:
    """Calculate German capital gains tax (Abgeltungssteuer).

    Base: 25 % Kapitalertragsteuer
    Plus 5.5 % Solidaritaetszuschlag on the base tax = effective 26.375 %
    Plus optional 8 % Kirchensteuer on the base tax.

    Parameters
    ----------
    gain_amount : float
        Capital gain (positive = profit).
    freibetrag_remaining : float
        Remaining Sparer-Pauschbetrag (EUR 1000 single, EUR 2000 joint).
    church_tax : bool
        Whether to apply Kirchensteuer (default 8 % on base tax).

    Returns
    -------
    dict
        ``tax_amount``, ``rate_applied``, ``freibetrag_used``, ``breakdown``.
    """
    if gain_amount <= 0:
        return {
            "tax_amount": 0.0,
            "rate_applied": 0.0,
            "freibetrag_used": 0.0,
            "breakdown": {
                "kapitalertragsteuer": 0.0,
                "solidaritaetszuschlag": 0.0,
                "kirchensteuer": 0.0,
            },
        }

    # Apply Freibetrag
    freibetrag_used = min(gain_amount, max(freibetrag_remaining, 0.0))
    taxable_gain = gain_amount - freibetrag_used

    if taxable_gain <= 0:
        return {
            "tax_amount": 0.0,
            "rate_applied": 0.0,
            "freibetrag_used": freibetrag_used,
            "breakdown": {
                "kapitalertragsteuer": 0.0,
                "solidaritaetszuschlag": 0.0,
                "kirchensteuer": 0.0,
            },
        }

    # Base tax
    kap = round(taxable_gain * GERMANY_KAP_RATE, 2)
    soli = round(kap * GERMANY_SOLI_RATE, 2)
    kirchen = round(kap * GERMANY_CHURCH_RATE, 2) if church_tax else 0.0

    total_tax = round(kap + soli + kirchen, 2)

    # Effective rate
    effective_rate = GERMANY_KAP_RATE * (1 + GERMANY_SOLI_RATE)
    if church_tax:
        effective_rate = GERMANY_KAP_RATE * (1 + GERMANY_SOLI_RATE + GERMANY_CHURCH_RATE)

    return {
        "tax_amount": total_tax,
        "rate_applied": round(effective_rate, 5),
        "freibetrag_used": freibetrag_used,
        "breakdown": {
            "kapitalertragsteuer": kap,
            "solidaritaetszuschlag": soli,
            "kirchensteuer": kirchen,
        },
    }


# ---------------------------------------------------------------------------
# Compute tax for a specific SELL transaction
# ---------------------------------------------------------------------------

async def compute_tax_for_transaction(
    transaction_id: int,
    user_id: int,
    db: AsyncSession,
) -> TaxRecord:
    """Load a SELL transaction, compute the capital gain and tax, and persist
    a ``TaxRecord``.

    Raises
    ------
    ValueError
        If the transaction is not found, does not belong to the user, or is
        not a SELL transaction.
    """
    # Load transaction with holding eagerly
    result = await db.execute(
        select(Transaction)
        .options(selectinload(Transaction.holding))
        .where(Transaction.id == transaction_id)
    )
    txn = result.scalar_one_or_none()

    if txn is None:
        raise ValueError("Transaction not found")

    # Verify ownership via holding -> portfolio -> user
    holding = txn.holding
    port_result = await db.execute(
        select(Portfolio).where(
            Portfolio.id == holding.portfolio_id,
            Portfolio.user_id == user_id,
        )
    )
    if port_result.scalar_one_or_none() is None:
        raise ValueError("Transaction does not belong to the current user")

    if txn.transaction_type != "SELL":
        raise ValueError("Tax computation is only applicable to SELL transactions")

    # Determine jurisdiction and currency from exchange
    exchange = holding.exchange.upper()
    jurisdiction = EXCHANGE_JURISDICTION_MAP.get(exchange, "IN")
    currency = EXCHANGE_CURRENCY_MAP.get(exchange, "INR")

    # Determine dates and holding period
    sale_date = txn.date
    # Use the earliest BUY transaction date as purchase_date approximation
    buy_result = await db.execute(
        select(Transaction)
        .where(
            Transaction.holding_id == holding.id,
            Transaction.transaction_type == "BUY",
        )
        .order_by(Transaction.date.asc())
        .limit(1)
    )
    earliest_buy = buy_result.scalar_one_or_none()
    purchase_date = earliest_buy.date if earliest_buy else sale_date

    holding_period_days = (sale_date - purchase_date).days

    # Calculate gain
    avg_price = float(holding.average_price)
    sale_price = float(txn.price)
    quantity = float(txn.quantity)
    gain_amount = round((sale_price - avg_price) * quantity, 4)

    # Classify gain type
    gain_type = classify_gain_type(purchase_date, sale_date, jurisdiction)

    # Determine financial year
    fy = get_financial_year(sale_date, jurisdiction)

    # Calculate tax based on jurisdiction
    if jurisdiction == "IN":
        # Check how much LTCG exemption has already been used in this FY
        existing_result = await db.execute(
            select(TaxRecord).where(
                TaxRecord.user_id == user_id,
                TaxRecord.financial_year == fy,
                TaxRecord.tax_jurisdiction == "IN",
                TaxRecord.gain_type == "LTCG",
            )
        )
        existing_records = existing_result.scalars().all()
        fy_ltcg_exemption_used = sum(
            float(r.gain_amount) for r in existing_records
            if r.gain_amount is not None and float(r.gain_amount) > 0
        )
        fy_ltcg_exemption_used = min(fy_ltcg_exemption_used, INDIA_LTCG_EXEMPTION)

        tax_info = calculate_indian_tax(gain_amount, gain_type, fy_ltcg_exemption_used)
    else:
        # German: check remaining Freibetrag for this FY
        existing_result = await db.execute(
            select(TaxRecord).where(
                TaxRecord.user_id == user_id,
                TaxRecord.financial_year == fy,
                TaxRecord.tax_jurisdiction == "DE",
            )
        )
        existing_records = existing_result.scalars().all()
        freibetrag_used = min(
            sum(
                float(r.gain_amount) for r in existing_records
                if r.gain_amount is not None and float(r.gain_amount) > 0
            ),
            GERMANY_DEFAULT_FREIBETRAG,
        )
        freibetrag_remaining = max(GERMANY_DEFAULT_FREIBETRAG - freibetrag_used, 0.0)

        tax_info = calculate_german_tax(gain_amount, freibetrag_remaining)

    tax_amount = tax_info["tax_amount"]

    # Create the tax record
    tax_record = TaxRecord(
        user_id=user_id,
        transaction_id=transaction_id,
        financial_year=fy,
        tax_jurisdiction=jurisdiction,
        gain_type=gain_type,
        purchase_date=purchase_date,
        sale_date=sale_date,
        purchase_price=round(avg_price * quantity, 4),
        sale_price=round(sale_price * quantity, 4),
        gain_amount=gain_amount,
        tax_amount=tax_amount,
        holding_period_days=holding_period_days,
        currency=currency,
    )
    db.add(tax_record)
    await db.flush()
    await db.refresh(tax_record)

    logger.info(
        "Tax record created: id=%d txn=%d gain=%.2f tax=%.2f (%s/%s)",
        tax_record.id,
        transaction_id,
        gain_amount,
        tax_amount,
        jurisdiction,
        gain_type,
    )
    return tax_record


# ---------------------------------------------------------------------------
# Generate tax summary for a financial year
# ---------------------------------------------------------------------------

async def generate_tax_summary(
    user_id: int,
    financial_year: str,
    jurisdiction: str,
    db: AsyncSession,
) -> dict:
    """Aggregate all tax records for a given FY and jurisdiction.

    Returns a summary dict with totals and breakdown by gain type.
    """
    result = await db.execute(
        select(TaxRecord).where(
            TaxRecord.user_id == user_id,
            TaxRecord.financial_year == financial_year,
            TaxRecord.tax_jurisdiction == jurisdiction,
        )
    )
    records = result.scalars().all()

    total_stcg = 0.0
    total_ltcg = 0.0
    total_tax = 0.0
    exemption_used = 0.0

    for r in records:
        gain = float(r.gain_amount) if r.gain_amount is not None else 0.0
        tax = float(r.tax_amount) if r.tax_amount is not None else 0.0

        if r.gain_type in ("STCG",):
            total_stcg += gain
        elif r.gain_type in ("LTCG", "ABGELTUNGSSTEUER", "VORABPAUSCHALE"):
            total_ltcg += gain

        total_tax += tax

    # Calculate exemption used for the FY
    if jurisdiction == "IN":
        ltcg_gains = sum(
            float(r.gain_amount)
            for r in records
            if r.gain_type == "LTCG"
            and r.gain_amount is not None
            and float(r.gain_amount) > 0
        )
        exemption_used = min(ltcg_gains, INDIA_LTCG_EXEMPTION)
    elif jurisdiction == "DE":
        total_gains = sum(
            float(r.gain_amount)
            for r in records
            if r.gain_amount is not None and float(r.gain_amount) > 0
        )
        exemption_used = min(total_gains, GERMANY_DEFAULT_FREIBETRAG)

    return {
        "financial_year": financial_year,
        "tax_jurisdiction": jurisdiction,
        "total_stcg": round(total_stcg, 2),
        "total_ltcg": round(total_ltcg, 2),
        "total_tax": round(total_tax, 2),
        "exemption_used": round(exemption_used, 2),
        "records_count": len(records),
    }


# ---------------------------------------------------------------------------
# Tax-loss harvesting suggestions
# ---------------------------------------------------------------------------

async def get_harvesting_suggestions(
    user_id: int,
    jurisdiction: str,
    db: AsyncSession,
) -> list[dict]:
    """Find holdings with unrealized losses and calculate potential tax savings.

    Returns a list sorted by highest potential tax saving first.
    """
    # Get all holdings for the user in the relevant jurisdiction
    exchange_list = [
        ex for ex, jur in EXCHANGE_JURISDICTION_MAP.items() if jur == jurisdiction
    ]
    if not exchange_list:
        return []

    result = await db.execute(
        select(Holding)
        .join(Portfolio, Holding.portfolio_id == Portfolio.id)
        .where(
            Portfolio.user_id == user_id,
            Holding.exchange.in_(exchange_list),
            Holding.current_price.isnot(None),
            Holding.cumulative_quantity > 0,
        )
    )
    holdings = result.scalars().all()

    suggestions: list[dict] = []
    for h in holdings:
        current_price = float(h.current_price)  # type: ignore[arg-type]
        avg_price = float(h.average_price)
        quantity = float(h.cumulative_quantity)

        if current_price >= avg_price:
            continue  # No unrealized loss

        unrealized_loss = round((avg_price - current_price) * quantity, 2)

        # Estimate potential tax saving
        if jurisdiction == "IN":
            # Determine gain type based on a hypothetical sale today
            gain_type = "STCG"  # Conservative: assume short-term for max saving
            tax_rate = INDIA_STCG_RATE
            potential_saving = round(unrealized_loss * tax_rate, 2)
        else:
            gain_type = "ABGELTUNGSSTEUER"
            # Effective German rate including Soli
            effective_rate = GERMANY_KAP_RATE * (1 + GERMANY_SOLI_RATE)
            potential_saving = round(unrealized_loss * effective_rate, 2)

        suggestions.append({
            "holding_id": h.id,
            "stock_symbol": h.stock_symbol,
            "unrealized_loss": unrealized_loss,
            "potential_tax_saving": potential_saving,
            "gain_type": gain_type,
        })

    # Sort by highest potential tax saving first
    suggestions.sort(key=lambda s: s["potential_tax_saving"], reverse=True)
    return suggestions
