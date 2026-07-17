"""Tax service: Indian STCG/LTCG and German Abgeltungssteuer calculation."""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.dividend import Dividend
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.tax_record import TaxRecord
from app.models.transaction import Transaction
from app.models.user_preferences import UserPreferences

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

# Sparer-Pauschbetrag (saver's allowance) per financial (calendar) year.
SPARER_PAUSCHBETRAG_SINGLE = 1000.0  # EUR 1000 for a single filer
SPARER_PAUSCHBETRAG_JOINT = 2000.0  # EUR 2000 for jointly-assessed spouses

# German investment-fund partial-exemption (Teilfreistellung) percentages by
# fund class (§20 InvStG). A share of fund gains/dividends is tax-free based on
# the fund's equity / real-estate content. STOCK and individual bond ETFs get 0.
TEILFREISTELLUNG_BY_FUND_TYPE: dict[str, float] = {
    "EQUITY_ETF": 30.0,
    "MIXED_ETF": 15.0,
    "REAL_ESTATE_ETF": 60.0,
    "BOND_ETF": 0.0,
    "STOCK": 0.0,
}

# German Basiszins (base interest rate) per tax year, published annually by the
# Bundesministerium der Finanzen, used for the Vorabpauschale. 2021 (-0.45 %) and
# 2022 (-0.05 %) had negative published rates → floored to 0 (no Vorabpauschale).
BASISZINS_BY_YEAR: dict[int, float] = {
    2018: 0.87,
    2019: 0.52,
    2020: 0.07,
    2021: 0.0,
    2022: 0.0,
    2023: 2.55,
    2024: 2.29,
    2025: 2.53,
}
BASISZINS_DEFAULT = 2.29  # documented fallback (2024 rate) for unknown years

# ── Indian LTCG grandfathering (31-Jan-2018) ──────────────────────────────
# Lots bought BEFORE this date qualify for grandfathered cost basis.
GRANDFATHER_LOT_CUTOFF = date(2018, 2, 1)
# The fair-market-value reference date whose close we look up.
FMV_2018_DATE = date(2018, 1, 31)
# yfinance suffix per exchange (mirrors market_data_service._EXCHANGE_SUFFIX).
_EXCHANGE_YF_SUFFIX: dict[str, str] = {
    "NSE": ".NS",
    "BSE": ".BO",
    "XETRA": ".DE",
    "NYSE": "",
    "NASDAQ": "",
}
# Process-level cache of 31-Jan-2018 closes keyed by "SYMBOL:EXCHANGE".
# A cached ``None`` means "unavailable" — callers fall back to the actual cost.
_FMV_2018_CACHE: dict[str, float | None] = {}

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
# German Teilfreistellung / Basiszins helpers
# ---------------------------------------------------------------------------

def teilfreistellung_for_fund_type(fund_type: str | None) -> float:
    """German Teilfreistellung (partial-exemption) percentage for a fund class.

    Under §20 InvStG a fraction of investment-fund gains/dividends is tax-free
    based on the fund's equity / real-estate content::

        EQUITY_ETF      -> 30 %
        MIXED_ETF       -> 15 %
        REAL_ESTATE_ETF -> 60 %
        BOND_ETF        -> 0 %
        STOCK / None    -> 0 %

    Returns the percentage as a float (e.g. ``30.0``), ``0.0`` for unknown or
    missing fund types.
    """
    if not fund_type:
        return 0.0
    return TEILFREISTELLUNG_BY_FUND_TYPE.get(fund_type.upper(), 0.0)


def basiszins_for_year(year: int) -> float:
    """Return the German Basiszins (base interest rate) for a tax year, in %.

    Published annually by the Bundesministerium der Finanzen. Years with a
    negative published rate are floored to 0 % (a negative Basisertrag produces
    no Vorabpauschale). Unknown years fall back to the documented default
    (2024's 2.29 %).
    """
    return BASISZINS_BY_YEAR.get(year, BASISZINS_DEFAULT)


async def get_fmv_31jan2018(symbol: str, exchange: str) -> float | None:
    """Fetch (and cache) the 31-Jan-2018 closing price for an equity symbol.

    Used for Indian LTCG grandfathering. Best-effort: returns ``None`` when the
    price cannot be fetched (network down, delisted, symbol absent on yfinance),
    in which case callers MUST fall back to the actual cost so grandfathering can
    only ever lower the taxable gain, never raise it.
    """
    cache_key = f"{symbol.upper()}:{exchange.upper()}"
    if cache_key in _FMV_2018_CACHE:
        return _FMV_2018_CACHE[cache_key]

    import asyncio

    def _sync_fetch() -> float | None:
        try:
            import yfinance as yf  # type: ignore[import-untyped]
        except Exception:
            return None
        suffix = _EXCHANGE_YF_SUFFIX.get(exchange.upper(), "")
        ticker = yf.Ticker(f"{symbol}{suffix}")
        # 31 Jan 2018 was a trading day, but scan a small window to be robust
        # against holidays / missing rows, then take the close ON 31-Jan-2018
        # (or the nearest trading day before it within the window).
        hist = ticker.history(start="2018-01-25", end="2018-02-02")
        if hist is None or hist.empty:
            return None
        exact: float | None = None
        best_before: tuple[date, float] | None = None
        for idx, row in hist.iterrows():
            d = idx.date() if hasattr(idx, "date") else idx
            close = float(row["Close"])
            if d == FMV_2018_DATE:
                exact = close
                break
            if d < FMV_2018_DATE and (best_before is None or d > best_before[0]):
                best_before = (d, close)
        if exact is not None:
            return exact
        if best_before is not None:
            return best_before[1]
        return None

    try:
        fmv = await asyncio.wait_for(asyncio.to_thread(_sync_fetch), timeout=10.0)
    except Exception as exc:  # pragma: no cover - network/best-effort path
        logger.warning(
            "FMV 31-Jan-2018 fetch failed for %s/%s: %s", symbol, exchange, exc
        )
        fmv = None

    _FMV_2018_CACHE[cache_key] = fmv
    return fmv


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
    teilfreistellung_pct: float = 0.0,
) -> dict:
    """Calculate German capital gains tax (Abgeltungssteuer).

    Base: 25 % Kapitalertragsteuer
    Plus 5.5 % Solidaritaetszuschlag on the base tax = effective 26.375 %
    Plus optional 8 % Kirchensteuer on the base tax.

    Order of operations for a fund gain:
        1. Teilfreistellung (partial exemption) reduces the gross gain.
        2. Sparer-Pauschbetrag (Freibetrag) is applied to the reduced gain.
        3. Abgeltungssteuer (+ Soli, + optional church tax) is charged.

    Parameters
    ----------
    gain_amount : float
        Gross capital gain (positive = profit).
    freibetrag_remaining : float
        Remaining Sparer-Pauschbetrag (EUR 1000 single, EUR 2000 joint).
    church_tax : bool
        Whether to apply Kirchensteuer (default 8 % on base tax).
    teilfreistellung_pct : float
        German fund partial-exemption percentage applied to the gross gain
        BEFORE the Freibetrag and Abgeltungssteuer (equity ETF 30, mixed 15,
        real-estate 60, bond/stock 0). Default ``0`` keeps existing
        (non-fund) callers unchanged.

    Returns
    -------
    dict
        ``tax_amount``, ``rate_applied``, ``freibetrag_used``,
        ``teilfreistellung_exempt``, ``breakdown``.
    """
    if gain_amount <= 0:
        return {
            "tax_amount": 0.0,
            "rate_applied": 0.0,
            "freibetrag_used": 0.0,
            "teilfreistellung_exempt": 0.0,
            "breakdown": {
                "kapitalertragsteuer": 0.0,
                "solidaritaetszuschlag": 0.0,
                "kirchensteuer": 0.0,
            },
        }

    # Teilfreistellung: a fraction of the fund gain is tax-free, applied before
    # the Freibetrag and Abgeltungssteuer.
    teil_pct = max(0.0, min(teilfreistellung_pct, 100.0))
    teilfreistellung_exempt = round(gain_amount * teil_pct / 100.0, 4)
    gain_after_teil = gain_amount - teilfreistellung_exempt

    # Apply Freibetrag to the post-Teilfreistellung gain
    freibetrag_used = min(gain_after_teil, max(freibetrag_remaining, 0.0))
    taxable_gain = gain_after_teil - freibetrag_used

    if taxable_gain <= 0:
        return {
            "tax_amount": 0.0,
            "rate_applied": 0.0,
            "freibetrag_used": freibetrag_used,
            "teilfreistellung_exempt": teilfreistellung_exempt,
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
        "teilfreistellung_exempt": teilfreistellung_exempt,
        "breakdown": {
            "kapitalertragsteuer": kap,
            "solidaritaetszuschlag": soli,
            "kirchensteuer": kirchen,
        },
    }


# ---------------------------------------------------------------------------
# German Vorabpauschale (advance lump-sum tax on accumulating funds)
# ---------------------------------------------------------------------------

def compute_vorabpauschale(
    value_start: float,
    value_end: float,
    distributions: float,
    basiszins_pct: float,
    fund_type: str | None = None,
    months_held: int = 12,
) -> dict:
    """Estimate the German Vorabpauschale (advance lump-sum tax) for one fund.

    Formula (§18 InvStG)::

        Basisertrag    = value_start * (basiszins_pct/100) * 0.7 * (months_held/12)
        Vorabpauschale = max(0, min(Basisertrag - distributions,
                                    value_end - value_start))

    The Vorabpauschale is then reduced by Teilfreistellung and taxed at the flat
    Abgeltungssteuer (25 % + 5.5 % Soli = 26.375 %; church tax excluded from this
    estimate). A loss year (value_end < value_start) yields a Vorabpauschale of 0.

    This is an ESTIMATE. Returns a dict with the gross Vorabpauschale, the
    post-Teilfreistellung taxable amount, and the estimated tax.
    """
    months = max(0, min(int(months_held), 12))
    basisertrag = value_start * (basiszins_pct / 100.0) * 0.7 * (months / 12.0)
    appreciation = value_end - value_start
    vorab_gross = max(0.0, min(basisertrag - distributions, appreciation))

    teil_pct = teilfreistellung_for_fund_type(fund_type)
    taxable = round(vorab_gross * (1.0 - teil_pct / 100.0), 2)
    tax_info = calculate_german_tax(
        vorab_gross, freibetrag_remaining=0.0, teilfreistellung_pct=teil_pct
    )

    return {
        "basisertrag": round(basisertrag, 2),
        "vorabpauschale": round(vorab_gross, 2),
        "taxable_vorabpauschale": taxable,
        "tax_amount": tax_info["tax_amount"],
        "teilfreistellung_pct": teil_pct,
        "basiszins_pct": basiszins_pct,
        "months_held": months,
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

    # ── Indian LTCG grandfathering (31-Jan-2018) ───────────────────────
    # Income-tax Act §55(2)(ac): for equity / equity-MF lots acquired BEFORE
    # 1 Feb 2018, the LTCG cost of acquisition is the HIGHER of the actual cost
    # and the LOWER of the 31-Jan-2018 fair-market value and the sale price:
    #     grandfathered_basis = max(actual_cost, min(fmv_31jan2018, sale_price))
    # This can only RAISE the cost basis (LOWER the gain), never worsen it. STCG
    # is unaffected. The FMV is best-effort — if it can't be fetched we fall back
    # to the actual cost so the number is never worse than reality.
    grandfather_fmv: float | None = None
    if jurisdiction == "IN" and any(
        lot["date"] < GRANDFATHER_LOT_CUTOFF
        and classify_gain_type(lot["date"], sale_date, "IN") == "LTCG"
        for lot in consumed_lots
    ):
        grandfather_fmv = await get_fmv_31jan2018(holding.stock_symbol, exchange)

    # ── Aggregate consumed lots into per-gain-type buckets ─────────────
    # Each bucket: qty, cost basis, proceeds, gain, earliest consumed buy date.
    buckets: dict[str, dict] = {}
    for lot in consumed_lots:
        gain_type = classify_gain_type(lot["date"], sale_date, jurisdiction)
        matched_qty = lot["qty"]

        # Effective per-share cost basis, grandfathered for pre-2018 Indian LTCG.
        cost_price = lot["price"]
        if (
            jurisdiction == "IN"
            and gain_type == "LTCG"
            and lot["date"] < GRANDFATHER_LOT_CUTOFF
            and grandfather_fmv is not None
        ):
            cost_price = max(lot["price"], min(grandfather_fmv, sale_price))

        cost = cost_price * matched_qty
        proceeds = sale_price * matched_qty
        gain = (sale_price - cost_price) * matched_qty

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

            # Total Freibetrag depends on the user's filing status:
            # EUR 1000 single / EUR 2000 jointly-assessed spouses. Keep it
            # consistent with the standalone allowance tracker.
            prefs_res = await db.execute(
                select(UserPreferences).where(UserPreferences.user_id == user_id)
            )
            prefs = prefs_res.scalar_one_or_none()
            filing = ((prefs.tax_settings if prefs else None) or {}).get("filing", "single")
            total_freibetrag = (
                SPARER_PAUSCHBETRAG_JOINT if filing == "joint"
                else SPARER_PAUSCHBETRAG_SINGLE
            )

            # Prior German sales consume the Freibetrag by their TAXABLE amount
            # (after Teilfreistellung), not their gross gain — so reduce each
            # prior record by its fund's partial-exemption rate.
            prior_txn_ids = [
                r.transaction_id for r in existing_records if r.transaction_id is not None
            ]
            fund_type_by_txn: dict[int, str | None] = {}
            if prior_txn_ids:
                ft_res = await db.execute(
                    select(Transaction.id, Holding.fund_type)
                    .join(Holding, Transaction.holding_id == Holding.id)
                    .where(Transaction.id.in_(prior_txn_ids))
                )
                for txn_id, ft in ft_res.all():
                    fund_type_by_txn[txn_id] = ft
            net_gains = 0.0
            for r in existing_records:
                if r.gain_amount is None:
                    continue
                teil = teilfreistellung_for_fund_type(fund_type_by_txn.get(r.transaction_id))
                net_gains += float(r.gain_amount) * (1.0 - teil / 100.0)
            freibetrag_used = min(max(net_gains, 0.0), total_freibetrag)
            freibetrag_remaining = max(total_freibetrag - freibetrag_used, 0.0)
            # Teilfreistellung partial exemption by the holding's fund class.
            # gain_amount is the GROSS economic gain (what the record stores);
            # calculate_german_tax applies the exemption before charging tax.
            teil_pct = teilfreistellung_for_fund_type(getattr(holding, "fund_type", None))
            tax_info = calculate_german_tax(
                gain_amount, freibetrag_remaining, teilfreistellung_pct=teil_pct
            )

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
# German Sparer-Pauschbetrag / Freistellungsauftrag allowance tracker
# ---------------------------------------------------------------------------

async def compute_german_allowance(
    user_id: int,
    financial_year: str,
    db: AsyncSession,
    filing: str | None = None,
) -> dict:
    """Track use of the German Sparer-Pauschbetrag (saver's allowance) for a FY.

    Allowance is EUR 1000 (single) / EUR 2000 (jointly-assessed spouses), read
    from ``user_preferences.tax_settings['filing']`` unless ``filing`` is passed.

    "Used" = positive net German capital gains for the year + German dividends,
    both reduced by Teilfreistellung (so fund gains/dividends only consume the
    allowance on their taxable portion). Losses net against gains (floored at 0);
    dividends are added on top. The allowance caps how much is offset.

    Germany's financial year is the calendar year, so ``financial_year`` is a
    plain year string like ``"2024"``.

    Returns ``{total_allowance, used, remaining, filing}``.
    """
    # Determine filing status (single/joint) from stored tax settings.
    if filing is None:
        prefs_res = await db.execute(
            select(UserPreferences).where(UserPreferences.user_id == user_id)
        )
        prefs = prefs_res.scalar_one_or_none()
        tax_settings = (prefs.tax_settings if prefs else None) or {}
        filing = tax_settings.get("filing", "single")

    filing = "joint" if filing == "joint" else "single"
    total_allowance = (
        SPARER_PAUSCHBETRAG_JOINT if filing == "joint" else SPARER_PAUSCHBETRAG_SINGLE
    )

    # ── German capital-gains records for the FY, reduced by Teilfreistellung ──
    rec_res = await db.execute(
        select(TaxRecord).where(
            TaxRecord.user_id == user_id,
            TaxRecord.financial_year == financial_year,
            TaxRecord.tax_jurisdiction == "DE",
        )
    )
    records = list(rec_res.scalars().all())

    # Map transaction_id -> fund_type so per-record Teilfreistellung matches the
    # exemption applied at tax-computation time.
    txn_ids = [r.transaction_id for r in records if r.transaction_id is not None]
    fund_type_by_txn: dict[int, str | None] = {}
    if txn_ids:
        ft_res = await db.execute(
            select(Transaction.id, Holding.fund_type)
            .join(Holding, Transaction.holding_id == Holding.id)
            .where(Transaction.id.in_(txn_ids))
        )
        for txn_id, ft in ft_res.all():
            fund_type_by_txn[txn_id] = ft

    net_gains = 0.0
    for r in records:
        gain = float(r.gain_amount) if r.gain_amount is not None else 0.0
        teil = teilfreistellung_for_fund_type(fund_type_by_txn.get(r.transaction_id))
        net_gains += gain * (1.0 - teil / 100.0)
    gains_component = max(net_gains, 0.0)

    # ── German dividends for the FY (calendar year), Teilfreistellung-reduced ──
    year = int(financial_year) if financial_year.isdigit() else None
    dividends_component = 0.0
    if year is not None:
        div_res = await db.execute(
            select(Dividend.total_amount, Dividend.ex_date, Holding.fund_type)
            .join(Holding, Dividend.holding_id == Holding.id)
            .join(Portfolio, Holding.portfolio_id == Portfolio.id)
            .where(
                Portfolio.user_id == user_id,
                Holding.exchange == "XETRA",
            )
        )
        for total, ex_date, ft in div_res.all():
            if ex_date is not None and ex_date.year == year:
                teil = teilfreistellung_for_fund_type(ft)
                dividends_component += float(total) * (1.0 - teil / 100.0)

    used = min(total_allowance, gains_component + dividends_component)
    remaining = max(total_allowance - used, 0.0)

    return {
        "total_allowance": round(total_allowance, 2),
        "used": round(used, 2),
        "remaining": round(remaining, 2),
        "filing": filing,
    }


# ---------------------------------------------------------------------------
# German Vorabpauschale — per-portfolio estimate
# ---------------------------------------------------------------------------

async def estimate_portfolio_vorabpauschale(
    portfolio_id: int,
    db: AsyncSession,
    year: int | None = None,
) -> dict:
    """Estimate the German Vorabpauschale for a portfolio's fund holdings.

    This is an ESTIMATE: exact start-of-year and end-of-year fund values are not
    stored, so the cost basis (average_price × quantity) is used as a proxy for
    the year-start value and the current market value as the year-end value. Only
    German (XETRA) fund holdings with a Teilfreistellung-eligible fund_type are
    included (individual stocks have no Vorabpauschale).

    Returns per-fund estimates plus totals; caller must verify portfolio access.
    """
    from datetime import date as _date

    year = year or _date.today().year
    basiszins = basiszins_for_year(year)

    result = await db.execute(
        select(Holding).where(
            Holding.portfolio_id == portfolio_id,
            Holding.exchange == "XETRA",
            Holding.fund_type.in_(["EQUITY_ETF", "MIXED_ETF", "BOND_ETF", "REAL_ESTATE_ETF"]),
        )
    )
    holdings = list(result.scalars().all())

    funds: list[dict] = []
    total_vorab = 0.0
    total_taxable = 0.0
    total_tax = 0.0

    for h in holdings:
        qty = float(h.cumulative_quantity)
        cost_basis = float(h.average_price) * qty
        current_value = (
            float(h.current_price) * qty if h.current_price is not None else cost_basis
        )
        est = compute_vorabpauschale(
            value_start=cost_basis,
            value_end=current_value,
            distributions=0.0,
            basiszins_pct=basiszins,
            fund_type=h.fund_type,
            months_held=12,
        )
        funds.append(
            {
                "holding_id": h.id,
                "stock_symbol": h.stock_symbol,
                "fund_type": h.fund_type,
                "value_start": round(cost_basis, 2),
                "value_end": round(current_value, 2),
                "vorabpauschale": est["vorabpauschale"],
                "taxable_vorabpauschale": est["taxable_vorabpauschale"],
                "tax_amount": est["tax_amount"],
                "teilfreistellung_pct": est["teilfreistellung_pct"],
            }
        )
        total_vorab += est["vorabpauschale"]
        total_taxable += est["taxable_vorabpauschale"]
        total_tax += est["tax_amount"]

    return {
        "portfolio_id": portfolio_id,
        "year": year,
        "basiszins_pct": basiszins,
        "is_estimate": True,
        "funds": funds,
        "total_vorabpauschale": round(total_vorab, 2),
        "total_taxable_vorabpauschale": round(total_taxable, 2),
        "total_estimated_tax": round(total_tax, 2),
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
