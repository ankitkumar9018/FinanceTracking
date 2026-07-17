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

def _add_months(d: date, months: int) -> date:
    """Add calendar months to a date, clamping the day (Jan 31 + 1m = Feb 28)."""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    # Clamp to the last valid day of the target month
    for day in (d.day, 30, 29, 28):
        try:
            return date(year, month, day)
        except ValueError:
            continue
    raise ValueError(f"Cannot add {months} months to {d}")


def classify_gain_type(purchase_date: date, sale_date: date, jurisdiction: str) -> str:
    """Classify the capital gain type based on holding period and jurisdiction.

    India (listed equity):
        held for MORE than 12 calendar months -> LTCG, otherwise STCG.
        (Calendar months, not 365 days — a 365-day hold across a leap year
        is still under 12 months and stays STCG.)
    Germany:
        Always ABGELTUNGSSTEUER (flat tax on capital gains).
    """
    if jurisdiction == "DE":
        return "ABGELTUNGSSTEUER"

    if sale_date > _add_months(purchase_date, 12):
        return "LTCG"
    return "STCG"


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

def _build_consumed_lots(
    transactions: list[Transaction],
    taxed_txn_id: int,
) -> list[dict]:
    """Replay BUY/SELL transactions in date order, consuming lots FIFO, and
    return the lots (with matched quantity, buy price, buy date) that the taxed
    SELL consumes.

    The lot queue is built from BUY transactions in chronological order. Every
    SELL up to and including the taxed one is replayed against that queue,
    consuming lots from the front (first-in, first-out). For the taxed SELL we
    record exactly which lots — and how much of each — it draws from.
    """
    # Ordered by (date, id) so a BUY and SELL on the same day resolve
    # deterministically (earlier-created first).
    ordered = sorted(transactions, key=lambda t: (t.date, t.id))

    # Each lot: {"qty": remaining, "price": buy price, "date": buy date}
    lots: list[dict] = []
    consumed: list[dict] = []

    for t in ordered:
        if t.transaction_type == "BUY":
            lots.append(
                {
                    "qty": float(t.quantity),
                    "price": float(t.price),
                    "date": t.date,
                }
            )
            continue

        if t.transaction_type != "SELL":
            continue

        # Consume this SELL's quantity FIFO from the front of the queue.
        remaining = float(t.quantity)
        is_taxed = t.id == taxed_txn_id
        while remaining > 1e-12 and lots:
            lot = lots[0]
            matched = min(remaining, lot["qty"])
            if is_taxed and matched > 0:
                consumed.append(
                    {
                        "qty": matched,
                        "price": lot["price"],
                        "date": lot["date"],
                    }
                )
            lot["qty"] -= matched
            remaining -= matched
            if lot["qty"] <= 1e-12:
                lots.pop(0)

        if is_taxed:
            # We only care up to and including the taxed SELL.
            break

    return consumed


async def compute_tax_for_transaction(
    transaction_id: int,
    user_id: int,
    db: AsyncSession,
) -> list[TaxRecord]:
    """Load a SELL transaction, compute the per-lot FIFO capital gain and tax,
    and persist one ``TaxRecord`` per gain-type bucket.

    A single SELL matched against multiple buy lots may straddle the STCG/LTCG
    boundary (India), producing BOTH an STCG record and an LTCG record. Germany
    has no split (a single ``ABGELTUNGSSTEUER`` record) but still uses the
    per-lot FIFO cost basis.

    Returns
    -------
    list[TaxRecord]
        One record per non-empty gain-type bucket. Empty if the SELL matched
        no available buy lots.

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

    # Idempotent recompute: drop any records previously produced for this SELL
    # before creating new ones. Otherwise a recompute would double-count gains
    # AND deplete the LTCG exemption / Freibetrag twice, overtaxing later sales
    # in the same FY.
    existing_rec = await db.execute(
        select(TaxRecord).where(TaxRecord.transaction_id == transaction_id)
    )
    for old in existing_rec.scalars().all():
        await db.delete(old)
    await db.flush()

    # Determine jurisdiction and currency from exchange
    exchange = holding.exchange.upper()
    jurisdiction = EXCHANGE_JURISDICTION_MAP.get(exchange, "IN")
    currency = EXCHANGE_CURRENCY_MAP.get(exchange, "INR")

    if jurisdiction not in ("IN", "DE"):
        # Only the Indian and German regimes are implemented. Producing a
        # number for other jurisdictions would silently mix Indian FY +
        # gain types with the German formula — worse than no answer.
        raise ValueError(
            f"Tax computation for {exchange}-listed holdings ({jurisdiction}) "
            "is not supported yet — only Indian (NSE/BSE) and German (XETRA) "
            "regimes are implemented."
        )

    sale_date = txn.date
    sale_price = float(txn.price)
    fy = get_financial_year(sale_date, jurisdiction)

    # ── FIFO: figure out which buy lots this SELL consumes ─────────────
    all_txns_result = await db.execute(
        select(Transaction).where(Transaction.holding_id == holding.id)
    )
    all_txns = list(all_txns_result.scalars().all())
    consumed_lots = _build_consumed_lots(all_txns, transaction_id)

    if not consumed_lots:
        # No matching buy lots (e.g. an oversell with no history). Nothing to
        # tax — return no records rather than fabricate a cost basis.
        logger.info(
            "Tax compute: txn=%d consumed no buy lots — no tax records created",
            transaction_id,
        )
        return []

    # ── Aggregate consumed lots into per-gain-type buckets ─────────────
    # Each bucket: qty, cost basis, proceeds, gain, earliest consumed buy date.
    buckets: dict[str, dict] = {}
    for lot in consumed_lots:
        gain_type = classify_gain_type(lot["date"], sale_date, jurisdiction)
        matched_qty = lot["qty"]
        cost = lot["price"] * matched_qty
        proceeds = sale_price * matched_qty
        gain = (sale_price - lot["price"]) * matched_qty

        bucket = buckets.setdefault(
            gain_type,
            {
                "qty": 0.0,
                "cost": 0.0,
                "proceeds": 0.0,
                "gain": 0.0,
                "earliest_buy": lot["date"],
            },
        )
        bucket["qty"] += matched_qty
        bucket["cost"] += cost
        bucket["proceeds"] += proceeds
        bucket["gain"] += gain
        if lot["date"] < bucket["earliest_buy"]:
            bucket["earliest_buy"] = lot["date"]

    # Deterministic record order: STCG before LTCG (India), single bucket (DE).
    ordering = ["STCG", "LTCG", "ABGELTUNGSSTEUER"]
    ordered_types = sorted(
        buckets.keys(),
        key=lambda g: ordering.index(g) if g in ordering else len(ordering),
    )

    tax_records: list[TaxRecord] = []
    for gain_type in ordered_types:
        bucket = buckets[gain_type]
        gain_amount = round(bucket["gain"], 4)
        purchase_date = bucket["earliest_buy"]
        holding_period_days = (sale_date - purchase_date).days

        # Tax calculation with FY exemption / Freibetrag netting. Records
        # already created earlier in this same call (e.g. an STCG bucket) do
        # not affect the LTCG exemption, but must be flushed so the FY netting
        # query below sees any prior sales in the FY.
        if jurisdiction == "IN":
            existing_result = await db.execute(
                select(TaxRecord).where(
                    TaxRecord.user_id == user_id,
                    TaxRecord.financial_year == fy,
                    TaxRecord.tax_jurisdiction == "IN",
                    TaxRecord.gain_type == "LTCG",
                )
            )
            existing_records = existing_result.scalars().all()
            # Net LTCG for the FY: losses set off against gains before the
            # exemption is consumed.
            net_ltcg = sum(
                float(r.gain_amount) for r in existing_records
                if r.gain_amount is not None
            )
            fy_ltcg_exemption_used = min(max(net_ltcg, 0.0), INDIA_LTCG_EXEMPTION)
            tax_info = calculate_indian_tax(
                gain_amount, gain_type, fy_ltcg_exemption_used
            )
        else:
            existing_result = await db.execute(
                select(TaxRecord).where(
                    TaxRecord.user_id == user_id,
                    TaxRecord.financial_year == fy,
                    TaxRecord.tax_jurisdiction == "DE",
                )
            )
            existing_records = existing_result.scalars().all()
            net_gains = sum(
                float(r.gain_amount) for r in existing_records
                if r.gain_amount is not None
            )
            freibetrag_used = min(max(net_gains, 0.0), GERMANY_DEFAULT_FREIBETRAG)
            freibetrag_remaining = max(
                GERMANY_DEFAULT_FREIBETRAG - freibetrag_used, 0.0
            )
            tax_info = calculate_german_tax(gain_amount, freibetrag_remaining)

        tax_amount = tax_info["tax_amount"]

        tax_record = TaxRecord(
            user_id=user_id,
            transaction_id=transaction_id,
            financial_year=fy,
            tax_jurisdiction=jurisdiction,
            gain_type=gain_type,
            purchase_date=purchase_date,
            sale_date=sale_date,
            purchase_price=round(bucket["cost"], 4),
            sale_price=round(bucket["proceeds"], 4),
            gain_amount=gain_amount,
            tax_amount=tax_amount,
            holding_period_days=holding_period_days,
            currency=currency,
        )
        db.add(tax_record)
        # Flush each record before computing the next bucket so the FY netting
        # query above reflects records created within this call.
        await db.flush()
        await db.refresh(tax_record)
        tax_records.append(tax_record)

        logger.info(
            "Tax record created: id=%d txn=%d qty=%.4f gain=%.2f tax=%.2f (%s/%s)",
            tax_record.id,
            transaction_id,
            bucket["qty"],
            gain_amount,
            tax_amount,
            jurisdiction,
            gain_type,
        )

    return tax_records


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

    # Calculate exemption used for the FY (net of losses, floored at zero)
    if jurisdiction == "IN":
        net_ltcg = sum(
            float(r.gain_amount)
            for r in records
            if r.gain_type == "LTCG" and r.gain_amount is not None
        )
        exemption_used = min(max(net_ltcg, 0.0), INDIA_LTCG_EXEMPTION)
    elif jurisdiction == "DE":
        net_gains = sum(
            float(r.gain_amount)
            for r in records
            if r.gain_amount is not None
        )
        exemption_used = min(max(net_gains, 0.0), GERMANY_DEFAULT_FREIBETRAG)

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
