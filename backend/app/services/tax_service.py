"""Tax service: Indian STCG/LTCG and German Abgeltungssteuer calculation."""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core import markets
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
# Process-level cache of 31-Jan-2018 closes keyed by "SYMBOL:EXCHANGE".
# Only SUCCESSFUL (non-None) lookups are cached. A failed lookup is deliberately
# NOT cached so a transient failure (network down, rate limit) is retried on the
# next call rather than permanently disabling grandfathering for that symbol.
_FMV_2018_CACHE: dict[str, float] = {}

# Exchange metadata now lives in ``app.core.markets``; the module-level names
# are kept as re-exported aliases for existing importers (``app.api.v1.tax``
# imports EXCHANGE_JURISDICTION_MAP, tests import all three).
_EXCHANGE_YF_SUFFIX: dict[str, str] = markets.YF_SUFFIX
EXCHANGE_JURISDICTION_MAP: dict[str, str] = markets.JURISDICTION
EXCHANGE_CURRENCY_MAP: dict[str, str] = markets.CURRENCY


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
        ticker = yf.Ticker(markets.ticker_symbol(symbol, exchange))
        # 31 Jan 2018 was a trading day, but scan a small window to be robust
        # against holidays / missing rows, then take the close ON 31-Jan-2018
        # (or the nearest trading day before it within the window).
        #
        # auto_adjust=False is essential: yfinance defaults to dividend/split-
        # adjusted closes, which deflate the historical 31-Jan-2018 price by
        # every dividend paid since — understating the grandfathered basis and
        # overstating the taxable LTCG. The raw "Close" is the actual close.
        hist = ticker.history(start="2018-01-25", end="2018-02-02", auto_adjust=False)
        if hist is None or hist.empty:
            return None
        exact: float | None = None
        best_before: tuple[date, float] | None = None
        for idx, row in hist.iterrows():
            d = idx.date() if hasattr(idx, "date") else idx
            try:
                close = float(row["Close"])
            except (KeyError, TypeError, ValueError):
                # Guard against a missing/renamed Close column.
                continue
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

    # Only cache a successful lookup — never a failure, so transient errors are
    # retried on the next call instead of being memoised for the process life.
    if fmv is not None:
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
    church_tax_rate: float = GERMANY_CHURCH_RATE,
) -> dict:
    """Calculate German capital gains tax (Abgeltungssteuer).

    Base: 25 % Kapitalertragsteuer
    Plus 5.5 % Solidaritaetszuschlag on the base tax = effective 26.375 %.

    When Kirchensteuer applies it is deductible as a Sonderausgabe, which lowers
    the Kapitalertragsteuer itself (§ 32d Abs. 1 EStG). The reduced base tax is::

        KapESt = taxable_gain * 0.25 / (1 + 0.25 * KiSt_rate)

    (equivalently ``taxable_gain / (4 + KiSt_rate)``), with KiSt_rate 0.08 or
    0.09. Soli and church tax are then charged on that reduced KapESt. With
    ``church_tax=False`` the denominator is 1 and the result is the plain 25 %
    base — so the default path is numerically unchanged.

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
        Whether to apply Kirchensteuer (via the reduced-rate formula above).
    teilfreistellung_pct : float
        German fund partial-exemption percentage applied to the gross gain
        BEFORE the Freibetrag and Abgeltungssteuer (equity ETF 30, mixed 15,
        real-estate 60, bond/stock 0). Default ``0`` keeps existing
        (non-fund) callers unchanged.
    church_tax_rate : float
        Kirchensteuer rate (0.08 in most states, 0.09 in Bavaria and
        Baden-Wuerttemberg). Only used when ``church_tax`` is True.

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

    # Base tax. Church tax is deductible (Sonderausgabenabzug), so it reduces
    # the Kapitalertragsteuer via KapESt = gain * 0.25 / (1 + 0.25 * KiSt_rate).
    # Without church tax the denominator is 1 -> plain 25 % (unchanged).
    if church_tax:
        kist_rate = church_tax_rate
        kap = round(
            taxable_gain * GERMANY_KAP_RATE / (1 + GERMANY_KAP_RATE * kist_rate),
            2,
        )
        kirchen = round(kap * kist_rate, 2)
    else:
        kap = round(taxable_gain * GERMANY_KAP_RATE, 2)
        kirchen = 0.0
    soli = round(kap * GERMANY_SOLI_RATE, 2)

    total_tax = round(kap + soli + kirchen, 2)

    # Effective rate (share of the taxable gain paid as total tax).
    if church_tax:
        kap_rate = GERMANY_KAP_RATE / (1 + GERMANY_KAP_RATE * church_tax_rate)
        effective_rate = kap_rate * (1 + GERMANY_SOLI_RATE + church_tax_rate)
    else:
        effective_rate = GERMANY_KAP_RATE * (1 + GERMANY_SOLI_RATE)

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

def _replay_fifo(
    transactions: list[Transaction],
    taxed_txn_id: int | None = None,
) -> tuple[list[dict], list[dict]]:
    """Replay BUY/SELL transactions in date order, consuming lots FIFO.

    The lot queue is built from BUY transactions in chronological order —
    ordered by ``(date, id)`` so a BUY and SELL on the same day resolve
    deterministically (earlier-created first). Every SELL is replayed against
    the queue, consuming lots from the front (first-in, first-out).

    Each lot is ``{"qty": remaining, "price": buy price, "date": buy date}``.

    Returns ``(open_lots, consumed)``:

    - ``open_lots`` — the lots still UNSOLD after the replay, oldest buy first
      (which is also the LTCG-clock order); a partially-sold lot keeps only
      its remaining quantity.
    - ``consumed`` — the lots (with matched quantity) that the SELL identified
      by ``taxed_txn_id`` draws from. When ``taxed_txn_id`` is given, the
      replay stops after that SELL; with ``None`` the whole history is
      replayed and ``consumed`` is empty.
    """
    ordered = sorted(transactions, key=lambda t: (t.date, t.id))

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
        is_taxed = taxed_txn_id is not None and t.id == taxed_txn_id
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

    # Defensive: drop any lot rounded down to (effectively) zero.
    return [lot for lot in lots if lot["qty"] > 1e-12], consumed


def _build_consumed_lots(
    transactions: list[Transaction],
    taxed_txn_id: int,
) -> list[dict]:
    """The lots (matched quantity, buy price, buy date) a taxed SELL consumes."""
    return _replay_fifo(transactions, taxed_txn_id)[1]


def build_open_lots(transactions: list[Transaction]) -> list[dict]:
    """Replay BUY/SELL transactions FIFO and return the still-open buy lots."""
    return _replay_fifo(transactions)[0]


async def _resolve_filing(
    user_id: int, db: AsyncSession, filing: str | None = None
) -> str:
    """German filing status (``single``/``joint``) from stored tax settings."""
    if filing is None:
        prefs_res = await db.execute(
            select(UserPreferences).where(UserPreferences.user_id == user_id)
        )
        prefs = prefs_res.scalar_one_or_none()
        filing = ((prefs.tax_settings if prefs else None) or {}).get("filing", "single")
    return "joint" if filing == "joint" else "single"


async def _teilfreistellung_net_gains(
    records: list[TaxRecord], db: AsyncSession
) -> float:
    """Net German gains reduced by each record's fund Teilfreistellung.

    The Sparer-Pauschbetrag is consumed by the TAXABLE portion of each gain
    (after the fund partial exemption), not the gross gain — so each record's
    gain is reduced by its holding's Teilfreistellung rate before summing.
    Losses net against gains; callers floor the sum at zero.

    Shared by the sale-path Freibetrag netting and the standalone allowance
    tracker (previously two divergent copies of the same logic).
    """
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
        if r.gain_amount is None:
            continue
        fund_type = (
            fund_type_by_txn.get(r.transaction_id)
            if r.transaction_id is not None
            else None
        )
        teil = teilfreistellung_for_fund_type(fund_type)
        net_gains += float(r.gain_amount) * (1.0 - teil / 100.0)
    return net_gains


async def _de_dividend_allowance_used(
    user_id: int, financial_year: str, db: AsyncSession
) -> float:
    """Teilfreistellung-reduced German (XETRA) dividends for a financial year.

    Germany's financial year is the calendar year, so ``financial_year`` must
    be a plain year string (anything else yields ``0.0``). These dividends
    consume the Sparer-Pauschbetrag alongside capital gains, so both the
    standalone allowance tracker AND the sale-path Freibetrag netting must
    subtract them.
    """
    year = int(financial_year) if financial_year.isdigit() else None
    if year is None:
        return 0.0
    div_res = await db.execute(
        select(Dividend.total_amount, Dividend.ex_date, Holding.fund_type)
        .join(Holding, Dividend.holding_id == Holding.id)
        .join(Portfolio, Holding.portfolio_id == Portfolio.id)
        .where(
            Portfolio.user_id == user_id,
            Holding.exchange == "XETRA",
        )
    )
    total = 0.0
    for amount, ex_date, ft in div_res.all():
        if ex_date is not None and ex_date.year == year:
            teil = teilfreistellung_for_fund_type(ft)
            total += float(amount) * (1.0 - teil / 100.0)
    return total


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

    FY exemption / Freibetrag netting is strictly order-based: each sale nets
    only against records that PRECEDE it in ``(sale_date, transaction_id)``
    order. After this sale's records are written, every LATER computed SELL in
    the same financial year is recomputed (in order) so the year's allocation
    is always identical to computing the sales chronologically — recomputing
    an earlier sale can no longer misallocate the exemption.

    Returns
    -------
    list[TaxRecord]
        One record per non-empty gain-type bucket (for THIS transaction).
        Empty if the SELL matched no available buy lots.

    Raises
    ------
    ValueError
        If the transaction is not found, does not belong to the user, or is
        not a SELL transaction.
    """
    records, fy, jurisdiction, sale_date = await _compute_tax_single(
        transaction_id, user_id, db
    )

    # ── Cascade: recompute later computed SELLs in the same FY ─────────────
    # An explicit loop over the non-cascading single-sale compute — no
    # recursion. Only sells that already have TaxRecords are replayed;
    # never-computed sells are not given records as a side effect.
    later_res = await db.execute(
        select(TaxRecord.transaction_id, TaxRecord.sale_date)
        .where(
            TaxRecord.user_id == user_id,
            TaxRecord.financial_year == fy,
            TaxRecord.tax_jurisdiction == jurisdiction,
            TaxRecord.transaction_id.isnot(None),
            or_(
                TaxRecord.sale_date > sale_date,
                and_(
                    TaxRecord.sale_date == sale_date,
                    TaxRecord.transaction_id > transaction_id,
                ),
            ),
        )
        .order_by(TaxRecord.sale_date, TaxRecord.transaction_id)
    )
    later_txn_ids: list[int] = []
    for later_txn_id, _sale_date in later_res.all():
        if later_txn_id not in later_txn_ids:
            later_txn_ids.append(later_txn_id)

    for later_txn_id in later_txn_ids:
        await _compute_tax_single(later_txn_id, user_id, db)

    return records


async def _compute_tax_single(
    transaction_id: int,
    user_id: int,
    db: AsyncSession,
) -> tuple[list[TaxRecord], str, str, date]:
    """Compute and persist the tax records for ONE SELL transaction.

    Does NOT cascade to later sells — that is the public wrapper's job
    (:func:`compute_tax_for_transaction`), keeping this function safe to call
    in a loop without recursion.

    Returns ``(records, financial_year, jurisdiction, sale_date)``.
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
        return [], fy, jurisdiction, sale_date

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

    # Records that PRECEDE this sale in (sale_date, transaction_id) order.
    # Netting strictly against earlier sales makes the FY allocation
    # independent of the order in which sales are (re)computed; the public
    # wrapper cascades a recompute over the later sales. Records for this
    # very transaction (deleted and recreated above) never match: strict
    # inequality excludes the same (sale_date, transaction_id).
    precedes = or_(
        TaxRecord.sale_date < sale_date,
        and_(
            TaxRecord.sale_date == sale_date,
            TaxRecord.transaction_id < transaction_id,
        ),
    )

    tax_records: list[TaxRecord] = []
    for gain_type in ordered_types:
        bucket = buckets[gain_type]
        gain_amount = round(bucket["gain"], 4)
        purchase_date = bucket["earliest_buy"]
        holding_period_days = (sale_date - purchase_date).days

        # Tax calculation with FY exemption / Freibetrag netting against the
        # PRECEDING records only.
        if jurisdiction == "IN":
            existing_result = await db.execute(
                select(TaxRecord).where(
                    TaxRecord.user_id == user_id,
                    TaxRecord.financial_year == fy,
                    TaxRecord.tax_jurisdiction == "IN",
                    TaxRecord.gain_type == "LTCG",
                    precedes,
                )
            )
            existing_records = list(existing_result.scalars().all())
            # Net LTCG for the FY so far: losses set off against gains before
            # the exemption is consumed.
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
                    precedes,
                )
            )
            existing_records = list(existing_result.scalars().all())

            # Total Freibetrag depends on the user's filing status:
            # EUR 1000 single / EUR 2000 jointly-assessed spouses. Keep it
            # consistent with the standalone allowance tracker.
            filing = await _resolve_filing(user_id, db)
            total_freibetrag = (
                SPARER_PAUSCHBETRAG_JOINT if filing == "joint"
                else SPARER_PAUSCHBETRAG_SINGLE
            )

            # Preceding German sales consume the Freibetrag by their TAXABLE
            # amount (after Teilfreistellung), not their gross gain — and
            # German dividends consume it too (same components as
            # compute_german_allowance, so the sale path and the standalone
            # tracker can never disagree).
            net_gains = await _teilfreistellung_net_gains(existing_records, db)
            dividends_used = await _de_dividend_allowance_used(user_id, fy, db)
            allowance_used = min(
                max(net_gains, 0.0) + dividends_used, total_freibetrag
            )
            freibetrag_remaining = max(total_freibetrag - allowance_used, 0.0)
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

    return tax_records, fy, jurisdiction, sale_date


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
        # Delegate to the allowance tracker so the summary agrees with the
        # compute path: filing-aware (EUR 1000 single / 2000 joint),
        # Teilfreistellung-reduced gains, and German dividends included —
        # instead of the old hardcoded €1000 cap over gross gains.
        allowance = await compute_german_allowance(user_id, financial_year, db)
        exemption_used = allowance["used"]

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
    filing = await _resolve_filing(user_id, db, filing)
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

    gains_component = max(await _teilfreistellung_net_gains(records, db), 0.0)

    # ── German dividends for the FY (calendar year), Teilfreistellung-reduced ──
    dividends_component = await _de_dividend_allowance_used(
        user_id, financial_year, db
    )

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
