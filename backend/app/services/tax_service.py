"""Tax service: Indian STCG/LTCG and German Abgeltungssteuer calculation."""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import and_, func, or_, select
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
INDIA_STCG_RATE = 0.20  # 20 % flat        (current law)
INDIA_LTCG_RATE = 0.125  # 12.5 %          (current law)
INDIA_LTCG_EXEMPTION = 125_000.0  # Rs 1.25 lakh per FY (current law)

# ── Finance (No. 2) Act 2024 rate cutover ──────────────────────────────────
# The new s.111A / s.112A rates apply to TRANSFERS made ON OR AFTER this date;
# a transfer on 22-Jul-2024 is still taxed at the old 15 % / 10 %.
FINANCE_ACT_2024_CUTOVER = date(2024, 7, 23)

# Rates by transfer date: (stcg_rate, ltcg_rate).
INDIA_RATES_PRE_2024 = (0.15, 0.10)
INDIA_RATES_FROM_2024 = (INDIA_STCG_RATE, INDIA_LTCG_RATE)

# The s.112A exemption is an ANNUAL per-FY pool, not a per-transfer
# entitlement, so it is keyed to the financial year and NOT to the transfer
# date. CBDT clarified that the enhanced Rs 1,25,000 limit applies for the
# whole of FY 2024-25 (AY 2025-26), including transfers made 1-Apr-2024 to
# 22-Jul-2024 that are still rate-taxed at 10 % — ITR-2 Schedule 112A applies a
# single deduction across both rate slices. Keying the pool to the transfer
# date instead would make the pool size depend on the order in which sales are
# computed inside the straddling year, destroying the order-independence
# invariant of the FY netting.
INDIA_LTCG_EXEMPTION_PRE_FY2024 = 100_000.0  # FY 2023-24 and earlier
INDIA_LTCG_EXEMPTION_FROM_FY2024 = INDIA_LTCG_EXEMPTION  # FY 2024-25 onwards

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


def india_rates_for(sale_date: date | None) -> tuple[float, float]:
    """``(stcg_rate, ltcg_rate)`` for an Indian transfer made on ``sale_date``.

    Finance (No. 2) Act 2024 raised s.111A STCG 15 % -> 20 % and s.112A LTCG
    10 % -> 12.5 % for transfers ON OR AFTER 23-Jul-2024. ``None`` means
    "current law", which is what every caller that deliberately models a
    hypothetical sale made TODAY relies on.
    """
    if sale_date is not None and sale_date < FINANCE_ACT_2024_CUTOVER:
        return INDIA_RATES_PRE_2024
    return INDIA_RATES_FROM_2024


def india_ltcg_exemption_for_fy(financial_year: str | None) -> float:
    """Annual s.112A exemption pool for an Indian FY string like ``"2023-24"``.

    Rs 1,00,000 up to and including FY 2023-24, Rs 1,25,000 from FY 2024-25.
    ``None`` means "current law". An unparseable value also falls back to
    current law but is logged — this function's whole job is historical
    accuracy, so a silently-assumed regime is worth a line in the log.
    """
    if not financial_year:
        return INDIA_LTCG_EXEMPTION_FROM_FY2024
    try:
        start = int(financial_year.split("-")[0])
    except ValueError:
        logger.warning(
            "Unparseable Indian financial year %r — assuming current-law "
            "s.112A exemption of %.0f",
            financial_year,
            INDIA_LTCG_EXEMPTION_FROM_FY2024,
        )
        return INDIA_LTCG_EXEMPTION_FROM_FY2024
    return (
        INDIA_LTCG_EXEMPTION_FROM_FY2024
        if start >= 2024
        else INDIA_LTCG_EXEMPTION_PRE_FY2024
    )


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
    *,
    sale_date: date | None = None,
) -> dict:
    """Calculate Indian capital gains tax.

    Parameters
    ----------
    gain_amount : float
        The capital gain (positive = profit, negative = loss). Callers that
        apply intra-head set-off must pass the gain ALREADY reduced by the
        losses set off against it — this function taxes what it is given.
    gain_type : str
        ``"STCG"`` or ``"LTCG"``.
    fy_ltcg_exemption_used : float
        How much of the annual s.112A LTCG exemption has already been used
        in this financial year.
    sale_date : date | None
        The TRANSFER date, which selects the rate regime (15 %/10 % before
        23-Jul-2024, 20 %/12.5 % on or after) and, via its financial year, the
        size of the annual exemption pool. Omitting it means "current law" —
        the right default for a hypothetical sale made today, and what every
        pre-existing caller relies on.

    Returns
    -------
    dict
        ``tax_amount``, ``rate_applied``, ``exemption_used``.
    """
    if gain_amount <= 0:
        return {"tax_amount": 0.0, "rate_applied": 0.0, "exemption_used": 0.0}

    stcg_rate, ltcg_rate = india_rates_for(sale_date)

    if gain_type == "STCG":
        tax = round(gain_amount * stcg_rate, 2)
        return {"tax_amount": tax, "rate_applied": stcg_rate, "exemption_used": 0.0}

    # LTCG: taxed above the annual s.112A exemption for the transfer's FY.
    exemption = india_ltcg_exemption_for_fy(
        get_financial_year(sale_date, "IN") if sale_date else None
    )
    remaining_exemption = max(exemption - fy_ltcg_exemption_used, 0.0)
    exemption_used = min(gain_amount, remaining_exemption)
    taxable_gain = gain_amount - exemption_used

    tax = round(taxable_gain * ltcg_rate, 2) if taxable_gain > 0 else 0.0
    rate_applied = ltcg_rate if taxable_gain > 0 else 0.0

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
# Intra-head loss set-off allocators (annual, whole financial year)
# ---------------------------------------------------------------------------
# Capital-gains set-off is an ANNUAL exercise, not a chronological one: a loss
# realized in December sets off a gain realized in September just as well as
# the other way round. Both allocators therefore take EVERY record of one
# (user, financial year, jurisdiction) and return the tax for each of them, so
# a single sale can never be taxed in isolation of the year it belongs to.
#
# Row shape (plain dicts so the allocators stay pure and unit-testable):
#   India   {"key", "gain_type": "STCG"|"LTCG", "gain", "sale_date",
#            "transaction_id", "owned"}
#   Germany {"key", "gain", "teil_pct", "pot": "SHARE"|"OTHER"|None,
#            "sale_date", "transaction_id", "owned"}
# ``owned`` (default True) marks a record this service computed and may
# rewrite; see the allocator docstrings.


def _fy_regime_date(financial_year: str | None) -> date | None:
    """A representative transfer date for an Indian FY, for rate selection.

    Used only for records that carry no ``sale_date`` (CSV-imported or
    backup-restored rows). 1 January of the FY's ending calendar year sits
    inside every FY and lands on the correct side of the 23-Jul-2024 cutover
    for both FY 2023-24 and FY 2024-25.
    """
    if not financial_year:
        return None
    try:
        start = int(financial_year.split("-")[0])
    except ValueError:
        return None
    return date(start + 1, 1, 1)


def _row_float(row: dict, field: str) -> float:
    """Read a possibly-``None``/``Decimal`` numeric off an allocator row."""
    value = row.get(field)
    return float(value) if value is not None else 0.0


def allocate_fy_tax_in(
    rows: list[dict],
    financial_year: str | None = None,
) -> dict:
    """Allocate one Indian financial year's capital-gains tax across its rows.

    Implements ss.70/71 read with s.112A:

    * a short-term capital LOSS sets off against BOTH STCG and LTCG (s.70(2));
    * a long-term capital LOSS sets off ONLY against LTCG (s.70(3)) — a net
      LTCL may never touch STCG;
    * the STCL pool is spent on the HIGHEST-taxed bucket first (STCG at 20 %
      before LTCG at 12.5 %), which is the taxpayer's own allocation and can
      be worth thousands versus a naive chronological pass;
    * the annual s.112A exemption is then applied CHRONOLOGICALLY to what
      survives, so the earliest disposal of the year consumes it first. (Rate
      order would matter only inside FY 2024-25, which straddles the
      23-Jul-2024 change; chronological is the documented behaviour of this
      service, is what a record imported from a filed statement has already
      assumed, and does not depend on an unverified reading of how the ITR
      utility splits one deduction across two rate slices.)

    Rows flagged ``"owned": False`` are records this service did not compute —
    imported from a statement, restored from a backup, or orphaned by a
    deleted transaction. They are real disposals, so their losses feed the
    pools and their gains consume the exemption, but no relief is allocated to
    them and no tax is returned for them: their stored figure is the user's,
    not ours, and silently rewriting it would destroy filed data.

    Unabsorbed losses are reported, not silently claimed as used: India allows
    an 8-year carry-forward that this service does not model.

    Returns ``{tax_by_key, exemption_used, total_tax, unabsorbed_stcl,
    unabsorbed_ltcl}``.
    """
    n = len(rows)
    fallback_date = _fy_regime_date(financial_year)
    sale_dates = [rows[i].get("sale_date") or fallback_date for i in range(n)]
    types = [rows[i].get("gain_type") or "" for i in range(n)]
    gains = [_row_float(rows[i], "gain") for i in range(n)]

    def _rate(i: int) -> float:
        stcg_rate, ltcg_rate = india_rates_for(sale_dates[i])
        return stcg_rate if types[i] == "STCG" else ltcg_rate

    owned = [bool(rows[i].get("owned", True)) for i in range(n)]

    def _chrono(i: int) -> tuple:
        return (
            sale_dates[i] or date.max,
            rows[i].get("transaction_id") or 0,
            types[i],
            i,
        )

    # Loss relief goes to the highest-taxed bucket first — that is where a
    # rupee of loss is worth most. The exemption is spent chronologically.
    relief_order = sorted(range(n), key=lambda i: (-_rate(i), *_chrono(i)))
    chrono_order = sorted(range(n), key=_chrono)

    stcl_pool = sum(-g for i, g in enumerate(gains) if types[i] == "STCG" and g < 0)
    ltcl_pool = sum(-g for i, g in enumerate(gains) if types[i] == "LTCG" and g < 0)
    taxable = [max(g, 0.0) for g in gains]

    def _absorb(pool: float, target_type: str) -> float:
        for i in relief_order:
            if pool <= 0:
                break
            if not owned[i] or types[i] != target_type or taxable[i] <= 0:
                continue
            used = min(pool, taxable[i])
            taxable[i] -= used
            pool -= used
        return pool

    # s.70(2): STCL against STCG first (20 %), only the remainder spills to
    # LTCG. s.70(3): LTCL can only ever reach LTCG.
    stcl_pool = _absorb(stcl_pool, "STCG")
    ltcl_pool = _absorb(ltcl_pool, "LTCG")
    stcl_pool = _absorb(stcl_pool, "LTCG")

    tax_by_key: dict = {}
    exemption_used = 0.0
    total_tax = 0.0
    for i in chrono_order:
        info = calculate_indian_tax(
            taxable[i], types[i], exemption_used, sale_date=sale_dates[i]
        )
        # A foreign row still consumes the statutory pool — it is a real
        # disposal of the year — but we do not restate its tax.
        exemption_used += info["exemption_used"]
        if owned[i]:
            tax_by_key[rows[i]["key"]] = info["tax_amount"]
            total_tax += info["tax_amount"]

    return {
        "tax_by_key": tax_by_key,
        "exemption_used": round(exemption_used, 2),
        "total_tax": round(total_tax, 2),
        "unabsorbed_stcl": round(stcl_pool, 2),
        "unabsorbed_ltcl": round(ltcl_pool, 2),
    }


def allocate_fy_tax_de(
    rows: list[dict],
    total_freibetrag: float = SPARER_PAUSCHBETRAG_SINGLE,
    dividends_used: float = 0.0,
) -> dict:
    """Allocate one German calendar year's Abgeltungssteuer across its rows.

    Implements §20(6) EStG with §20 InvStG:

    * Teilfreistellung applies to fund LOSSES as well as gains, so both
      Verlustverrechnungstöpfe are kept in post-Teilfreistellung terms;
    * losses from the sale of SHARES may only be set off against gains from
      the sale of shares (§20(6) Satz 4) — the Aktien pot;
    * every other capital loss sits in the "Sonstige" pot and may be set off
      against any other capital income, share gains included;
    * set-off happens BEFORE the Sparer-Pauschbetrag, so a year that nets to
      zero or below consumes none of the allowance.

    Rows flagged ``"owned": False`` keep their stored tax for the same reason
    as in :func:`allocate_fy_tax_in`, while still consuming the
    Sparer-Pauschbetrag and feeding the loss pots.

    ``pot`` is ``None`` when a holding's ``fund_type`` is unset — the default
    state of a real user's holdings, where an unclassified position may be a
    share or an ETF. Guessing either way is a real mis-charge (a bond ETF
    treated as a share blocks a legal offset; an unclassified equity ETF
    treated as a share creates an illegal one), so a year containing ANY
    unclassified row falls back to a single pot rather than inventing a
    classification.

    Returns ``{tax_by_key, total_tax, net_positive, allowance_used,
    two_pot, unabsorbed_share_loss, unabsorbed_other_loss}``.
    """
    n = len(rows)
    order = sorted(
        range(n),
        key=lambda i: (
            rows[i].get("sale_date") or date.max,
            rows[i].get("transaction_id") or 0,
            i,
        ),
    )
    pots = [rows[i].get("pot") for i in range(n)]
    two_pot = all(p in ("SHARE", "OTHER") for p in pots)
    if not two_pot:
        pots = ["OTHER"] * n

    net = []
    for i in range(n):
        teil = max(0.0, min(_row_float(rows[i], "teil_pct"), 100.0))
        net.append(_row_float(rows[i], "gain") * (1.0 - teil / 100.0))

    share_pool = sum(-v for i, v in enumerate(net) if v < 0 and pots[i] == "SHARE")
    other_pool = sum(-v for i, v in enumerate(net) if v < 0 and pots[i] == "OTHER")
    taxable = [max(v, 0.0) for v in net]

    owned = [bool(rows[i].get("owned", True)) for i in range(n)]

    def _absorb(pool: float, target_pot: str) -> float:
        for i in order:
            if pool <= 0:
                break
            if not owned[i] or pots[i] != target_pot or taxable[i] <= 0:
                continue
            used = min(pool, taxable[i])
            taxable[i] -= used
            pool -= used
        return pool

    share_pool = _absorb(share_pool, "SHARE")
    other_pool = _absorb(other_pool, "OTHER")
    # A non-share loss may also cover a share gain; the reverse is barred.
    other_pool = _absorb(other_pool, "SHARE")

    # Dividends consume the Sparer-Pauschbetrag alongside gains.
    freibetrag_pool = max(total_freibetrag - min(dividends_used, total_freibetrag), 0.0)

    tax_by_key: dict = {}
    total_tax = 0.0
    allowance_used_by_gains = 0.0
    for i in order:
        info = calculate_german_tax(
            taxable[i], freibetrag_pool, teilfreistellung_pct=0.0
        )
        freibetrag_pool = max(freibetrag_pool - info["freibetrag_used"], 0.0)
        allowance_used_by_gains += info["freibetrag_used"]
        if owned[i]:
            tax_by_key[rows[i]["key"]] = info["tax_amount"]
            total_tax += info["tax_amount"]

    net_positive = sum(taxable)
    return {
        "tax_by_key": tax_by_key,
        "total_tax": round(total_tax, 2),
        "net_positive": round(net_positive, 2),
        "allowance_used": round(
            min(total_freibetrag, net_positive + dividends_used), 2
        ),
        "two_pot": two_pot,
        "unabsorbed_share_loss": round(share_pool, 2),
        "unabsorbed_other_loss": round(other_pool, 2),
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
    ordered by ``(date, BUY-before-SELL, id)``. Sorting BUYs ahead of SELLs
    within the same day matters: an intraday buy-then-sell whose SELL row
    happens to carry the lower id would otherwise be replayed BEFORE its own
    buy lot existed, matching nothing and silently losing a real realized gain.
    Every SELL is then replayed against the queue, consuming lots from the
    front (first-in, first-out).

    Each lot is ``{"qty": remaining, "price": buy price, "date": buy date,
    "brokerage_per_unit": purchase brokerage / bought quantity}``.

    Returns ``(open_lots, consumed)``:

    - ``open_lots`` — the lots still UNSOLD after the replay, oldest buy first
      (which is also the LTCG-clock order); a partially-sold lot keeps only
      its remaining quantity.
    - ``consumed`` — the lots (with matched quantity) that the SELL identified
      by ``taxed_txn_id`` draws from. When ``taxed_txn_id`` is given, the
      replay stops after that SELL; with ``None`` the whole history is
      replayed and ``consumed`` is empty.
    """
    # BUY sorts before SELL on the same date (0 < 1) so a same-day buy lot is
    # always available to a same-day sale regardless of insertion order.
    ordered = sorted(
        transactions,
        key=lambda t: (t.date, 0 if t.transaction_type == "BUY" else 1, t.id),
    )

    lots: list[dict] = []
    consumed: list[dict] = []

    for t in ordered:
        if t.transaction_type == "BUY":
            buy_qty = float(t.quantity)
            # getattr keeps the helper usable with the lightweight stand-ins
            # tests build (SimpleNamespace rows without a brokerage field).
            buy_brokerage = float(getattr(t, "brokerage", 0) or 0)
            lots.append(
                {
                    "qty": buy_qty,
                    "price": float(t.price),
                    "date": t.date,
                    # Purchase brokerage spread per unit so a lot consumed in
                    # pieces contributes only its share to each sale's basis.
                    # The guard matters: corporate actions inject synthetic
                    # BUYs whose quantity can be zero or negative.
                    "brokerage_per_unit": (buy_brokerage / buy_qty) if buy_qty else 0.0,
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
                        "brokerage_per_unit": lot.get("brokerage_per_unit", 0.0),
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


# German loss pots (§20(6) Satz 4 EStG): share losses may only be set off
# against share gains, every other capital loss goes in the "Sonstige" pot.
_DE_SHARE_FUND_TYPES = {"STOCK"}
_DE_FUND_FUND_TYPES = {"EQUITY_ETF", "MIXED_ETF", "REAL_ESTATE_ETF", "BOND_ETF"}


def de_loss_pot_for_fund_type(
    fund_type: str | None, gain_type: str | None = None
) -> str | None:
    """Verlustverrechnungstopf for a holding: ``"SHARE"``, ``"OTHER"``, or None.

    ``None`` means "cannot tell" — ``Holding.fund_type`` is nullable with no
    default and is only ever set through ``PUT /tax/fund-type/{holding_id}``,
    so an unset value is the NORMAL state and may equally be an individual
    share or an unclassified ETF. Callers must not guess: see
    :func:`allocate_fy_tax_de`, which falls back to a single pot for a year
    that contains any unclassified row.
    """
    if gain_type == "VORABPAUSCHALE":
        # Advance lump-sum fund income is never a share gain.
        return "OTHER"
    if not fund_type:
        return None
    ft = fund_type.upper()
    if ft in _DE_SHARE_FUND_TYPES:
        return "SHARE"
    if ft in _DE_FUND_FUND_TYPES:
        return "OTHER"
    return None


async def _de_allocation_rows(
    records: list[TaxRecord], db: AsyncSession
) -> list[dict]:
    """Build :func:`allocate_fy_tax_de` rows from stored German tax records.

    Each record's Teilfreistellung rate and loss pot come from the holding
    behind its transaction — the same join the allowance tracker and the sale
    path both need, so neither can drift from the other.
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

    rows: list[dict] = []
    for r in records:
        fund_type = (
            fund_type_by_txn.get(r.transaction_id)
            if r.transaction_id is not None
            else None
        )
        rows.append(
            {
                "key": r.id,
                "gain": float(r.gain_amount) if r.gain_amount is not None else 0.0,
                "teil_pct": teilfreistellung_for_fund_type(fund_type),
                "pot": de_loss_pot_for_fund_type(fund_type, r.gain_type),
                "sale_date": r.sale_date,
                "transaction_id": r.transaction_id,
                "owned": r.transaction_id is not None,
            }
        )
    return rows


async def _de_dividend_allowance_used(
    user_id: int, financial_year: str, db: AsyncSession
) -> float:
    """Teilfreistellung-reduced German (XETRA) dividends for a financial year.

    Germany's financial year is the calendar year, so ``financial_year`` must
    be a plain year string (anything else yields ``0.0``). These dividends
    consume the Sparer-Pauschbetrag alongside capital gains, so both the
    standalone allowance tracker AND the sale-path Freibetrag netting must
    subtract them — both go through this single helper.

    German investment income is attributed by the **Zuflussprinzip**: it
    belongs to the tax year the money actually ARRIVES (the payment date), not
    the year the share went ex-dividend. A dividend with a December ex-date and
    a January payment date therefore consumes the FOLLOWING year's
    Sparer-Pauschbetrag. ``ex_date`` is used only as a fallback when no payment
    date is recorded.
    """
    year = int(financial_year) if financial_year.isdigit() else None
    if year is None:
        return 0.0
    div_res = await db.execute(
        select(
            Dividend.total_amount,
            Dividend.ex_date,
            Dividend.payment_date,
            Holding.fund_type,
        )
        .join(Holding, Dividend.holding_id == Holding.id)
        .join(Portfolio, Holding.portfolio_id == Portfolio.id)
        .where(
            Portfolio.user_id == user_id,
            Holding.exchange == "XETRA",
        )
    )
    total = 0.0
    for amount, ex_date, payment_date, ft in div_res.all():
        inflow_date = payment_date or ex_date
        if inflow_date is not None and inflow_date.year == year:
            teil = teilfreistellung_for_fund_type(ft)
            total += float(amount) * (1.0 - teil / 100.0)
    return total


async def _fy_allocation(
    user_id: int,
    financial_year: str,
    jurisdiction: str,
    db: AsyncSession,
    filing: str | None = None,
) -> dict | None:
    """Run the annual intra-head set-off over a stored financial year.

    Reads every ``TaxRecord`` of one (user, FY, jurisdiction) — the
    jurisdiction filter is what stops rupee losses from netting against euro
    gains — and returns the allocator's answer plus the records themselves.
    Read-only: use :func:`_reallocate_financial_year` to persist it.

    ``None`` for a jurisdiction with no implemented regime.
    """
    if jurisdiction not in ("IN", "DE"):
        return None

    result = await db.execute(
        select(TaxRecord).where(
            TaxRecord.user_id == user_id,
            TaxRecord.financial_year == financial_year,
            TaxRecord.tax_jurisdiction == jurisdiction,
        )
    )
    records = list(result.scalars().all())

    if jurisdiction == "IN":
        rows = [
            {
                "key": r.id,
                "gain_type": r.gain_type,
                "gain": float(r.gain_amount) if r.gain_amount is not None else 0.0,
                "sale_date": r.sale_date,
                "transaction_id": r.transaction_id,
                "owned": r.transaction_id is not None,
            }
            for r in records
        ]
        alloc = allocate_fy_tax_in(rows, financial_year)
    else:
        rows = await _de_allocation_rows(records, db)
        filing_status = await _resolve_filing(user_id, db, filing)
        total_allowance = (
            SPARER_PAUSCHBETRAG_JOINT
            if filing_status == "joint"
            else SPARER_PAUSCHBETRAG_SINGLE
        )
        dividends_used = await _de_dividend_allowance_used(
            user_id, financial_year, db
        )
        alloc = allocate_fy_tax_de(
            rows,
            total_freibetrag=total_allowance,
            dividends_used=dividends_used,
        )
        alloc["filing"] = filing_status
        alloc["total_allowance"] = total_allowance

    alloc["records"] = records
    return alloc


async def _reallocate_financial_year(
    user_id: int,
    financial_year: str,
    jurisdiction: str,
    db: AsyncSession,
) -> dict | None:
    """Re-run the FY set-off and write the allocated tax onto every record.

    Only ``tax_amount`` is rewritten. Each record's ``gain_amount`` is a pure
    FIFO fact of its own sale and of the transactions BEFORE it, so a later
    sale can never change an earlier one's gain — but it can change what that
    gain is taxed at, which is exactly what set-off is.
    """
    alloc = await _fy_allocation(user_id, financial_year, jurisdiction, db)
    if alloc is None:
        return None

    tax_by_key = alloc["tax_by_key"]
    changed = False
    for record in alloc["records"]:
        new_tax = tax_by_key.get(record.id)
        if new_tax is None:
            continue
        if record.tax_amount is None or float(record.tax_amount) != new_tax:
            record.tax_amount = new_tax
            changed = True
    if changed:
        await db.flush()
    return alloc


# ── Stale-record invalidation ──────────────────────────────────────────────
# A TaxRecord is a DERIVED artifact of one SELL replayed against its holding's
# FIFO ledger. Editing or deleting any transaction changes that ledger, so the
# records derived from it must be re-derived or destroyed. They previously
# survived untouched: correcting a sale price left the old tax figure in the
# ITR report, and deleting a sale left a ghost record (transaction_id is
# ondelete=SET NULL) that kept consuming the annual exemption forever.

# sale_date is nullable on TaxRecord, so the anchor must admit None.
# Only (financial_year, jurisdiction) drive the re-derive; the date is
# carried for diagnostics and ordering context.
Anchor = tuple[str, str, "date | None", int]


async def _drop_records(
    transaction_id: int, user_id: int, db: AsyncSession
) -> list[Anchor]:
    """Delete one transaction's TaxRecords, returning where they sat."""
    res = await db.execute(
        select(TaxRecord).where(
            TaxRecord.transaction_id == transaction_id,
            TaxRecord.user_id == user_id,
        )
    )
    anchors: list[Anchor] = []
    for rec in res.scalars().all():
        anchors.append(
            (rec.financial_year, rec.tax_jurisdiction, rec.sale_date, transaction_id)
        )
        await db.delete(rec)
    await db.flush()
    return anchors


async def snapshot_tax_anchors(
    holding_id: int,
    user_id: int,
    db: AsyncSession,
    *,
    dropping_transaction_id: int | None = None,
) -> list[Anchor]:
    """Record where a holding's TaxRecords sit BEFORE its ledger is mutated.

    Must be called BEFORE the change. The anchors name the (FY, jurisdiction)
    pairs that need re-deriving afterwards — including the FY a sale is about
    to LEAVE when its date is edited across a year boundary, which the new
    state can no longer tell us.

    ``dropping_transaction_id`` deletes that transaction's records here, while
    the foreign key still points at it. Deleting the transaction first would
    NULL the link and strand the records beyond reach.
    """
    res = await db.execute(
        select(
            TaxRecord.financial_year,
            TaxRecord.tax_jurisdiction,
            TaxRecord.sale_date,
            TaxRecord.transaction_id,
        )
        .join(Transaction, Transaction.id == TaxRecord.transaction_id)
        .where(TaxRecord.user_id == user_id, Transaction.holding_id == holding_id)
    )
    anchors: list[Anchor] = [
        (fy, juris, sale_date, txn_id) for fy, juris, sale_date, txn_id in res.all()
    ]
    if dropping_transaction_id is not None:
        await _drop_records(dropping_transaction_id, user_id, db)
    return anchors


async def recompute_tax_after_ledger_change(
    anchors: list[Anchor], user_id: int, db: AsyncSession
) -> None:
    """Re-derive every FY touched by a ledger change.

    Recomputing the EARLIEST surviving computed sell in each affected FY is
    enough: ``compute_tax_for_transaction`` cascades over every later sell in
    that year and then reallocates the whole year's set-off. When a year has no
    computed sells left, its allocation is still refreshed so a deleted sale
    stops consuming the exemption.
    """
    for fy, jurisdiction in sorted({(a[0], a[1]) for a in anchors}):
        earliest = (
            await db.execute(
                select(TaxRecord.transaction_id)
                .where(
                    TaxRecord.user_id == user_id,
                    TaxRecord.financial_year == fy,
                    TaxRecord.tax_jurisdiction == jurisdiction,
                    TaxRecord.transaction_id.isnot(None),
                )
                .order_by(TaxRecord.sale_date, TaxRecord.transaction_id)
                .limit(1)
            )
        ).scalar_one_or_none()

        if earliest is not None:
            try:
                await compute_tax_for_transaction(earliest, user_id, db)
                continue
            except ValueError as exc:
                logger.warning(
                    "Tax re-derive: FY %s (%s) anchor txn=%s could not be "
                    "recomputed (%s); reallocating what remains",
                    fy, jurisdiction, earliest, exc,
                )
        await _reallocate_financial_year(user_id, fy, jurisdiction, db)


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

    Two things happen after this sale's own records are written, and they are
    deliberately different jobs:

    * every LATER computed SELL in the same financial year is fully recomputed
      (in order), because editing a sale shifts the FIFO lots — and therefore
      the gain, the gain TYPE and the record count — of the sales after it;
    * the whole financial year is then re-allocated, because intra-head loss
      set-off is ANNUAL: a loss realized in December sets off a gain realized
      in September, so a sale can never be taxed in isolation. Earlier sales'
      ``gain_amount`` cannot change (FIFO is chronological), only their tax.

    A consequence worth knowing: recording a sale rewrites ``tax_amount`` on
    records the user may already have seen or exported. That is what the law
    requires, but it is a visible change.

    Returns
    -------
    list[TaxRecord]
        One record per non-empty gain-type bucket (for THIS transaction).

    Raises
    ------
    ValueError
        If the transaction is not found, does not belong to the user, is not a
        SELL transaction, or matches no available FIFO buy lot. The last case
        used to return an empty list, which quietly recorded zero tax on a real
        realized gain — it is now an error the API surfaces as a 400.
    """
    records, fy, jurisdiction, sale_date = await _compute_tax_single(
        transaction_id, user_id, db, reallocate=False
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
        try:
            await _compute_tax_single(later_txn_id, user_id, db, reallocate=False)
        except ValueError as exc:
            # A later sale that can no longer be matched (its purchases were
            # deleted, say) must not abort THIS sale's computation. Drop its
            # records explicitly: _compute_tax_single raises BEFORE its own
            # drop step on the "not found"/"not a SELL" paths, so without this
            # the warning below claimed a removal that never happened.
            await _drop_records(later_txn_id, user_id, db)
            logger.warning(
                "Tax cascade: recompute of later txn=%d failed (%s); "
                "its stale records were removed",
                later_txn_id,
                exc,
            )

    # ── Annual set-off: allocate the whole FY once, after every gain in it
    # is final. Doing it here rather than inside the per-sale compute keeps
    # the cascade to a single allocation instead of one per recomputed sale.
    await _reallocate_financial_year(user_id, fy, jurisdiction, db)

    return records


async def _compute_tax_single(
    transaction_id: int,
    user_id: int,
    db: AsyncSession,
    reallocate: bool = True,
) -> tuple[list[TaxRecord], str, str, date]:
    """Compute and persist the tax records for ONE SELL transaction.

    Does NOT cascade to later sells — that is the public wrapper's job
    (:func:`compute_tax_for_transaction`), keeping this function safe to call
    in a loop without recursion.

    Brokerage is part of the round trip: the stored ``purchase_price`` is the
    deductible side — cost of acquisition (including the lot's apportioned
    PURCHASE brokerage) plus the apportioned SALE brokerage as an expense of
    transfer — while ``sale_price`` stays the GROSS full value of
    consideration. ``gain_amount`` is therefore net of both.

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

    # Sale brokerage is an expense of transfer (s.48 India, §20(4) EStG
    # Germany): deductible, but NOT netted off the full value of consideration.
    # It is spread per unit so it lands on each consumed lot in proportion to
    # the quantity that lot contributed, then added to the deductible cost
    # AFTER grandfathering — which keeps ``sale_price`` on the record the gross
    # consideration the ITR schedules (and ``export_service``) expect.
    sale_qty = float(txn.quantity)
    sale_brokerage_per_unit = (
        float(txn.brokerage or 0) / sale_qty if sale_qty else 0.0
    )

    # ── FIFO: figure out which buy lots this SELL consumes ─────────────
    all_txns_result = await db.execute(
        select(Transaction).where(Transaction.holding_id == holding.id)
    )
    all_txns = list(all_txns_result.scalars().all())
    consumed_lots = _build_consumed_lots(all_txns, transaction_id)

    if not consumed_lots:
        # No matching buy lots (e.g. an oversell, or a SELL imported without
        # its purchase history). Silently returning zero records used to make a
        # real realized gain vanish from /tax/summary and the ITR report, so
        # fail loudly instead — the route maps this to a 400 the user can see.
        logger.warning(
            "Tax compute: txn=%d consumed no buy lots — refusing to record zero tax",
            transaction_id,
        )
        raise ValueError(
            "No purchase lots available to match this sale — the holding has no "
            "unsold BUY transactions on or before the sale date. Import or add "
            "the matching purchase before computing tax."
        )

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

        # Effective per-share acquisition cost. Purchase brokerage is part of
        # the cost of acquisition (s.55 / Anschaffungsnebenkosten), so it sits
        # INSIDE the actual-cost arm of the s.55(2)(ac) grandfathering max().
        acq_price = lot["price"] + lot.get("brokerage_per_unit", 0.0)
        if (
            jurisdiction == "IN"
            and gain_type == "LTCG"
            and lot["date"] < GRANDFATHER_LOT_CUTOFF
            and grandfather_fmv is not None
        ):
            # The full-value-of-consideration arm stays GROSS: expenses of
            # transfer are deducted under s.48, not inside s.55(2)(ac). When
            # the deemed FMV basis wins it subsumes the purchase brokerage.
            acq_price = max(acq_price, min(grandfather_fmv, sale_price))

        # Deductible side = cost of acquisition + expense of transfer.
        cost_price = acq_price + sale_brokerage_per_unit

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

    # Records carry the GAIN facts of this sale; the tax on them is decided
    # by the whole financial year (intra-head loss set-off is annual), so it
    # is filled in by the FY allocator below rather than per bucket here.
    tax_records: list[TaxRecord] = []
    for gain_type in ordered_types:
        bucket = buckets[gain_type]
        gain_amount = round(bucket["gain"], 4)
        purchase_date = bucket["earliest_buy"]

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
            tax_amount=0.0,
            holding_period_days=(sale_date - purchase_date).days,
            currency=currency,
        )
        db.add(tax_record)
        tax_records.append(tax_record)

    # One flush for the batch: the records need ids (the allocator keys on
    # them) and ``created_at`` before the API can serialize them.
    await db.flush()
    for tax_record in tax_records:
        await db.refresh(tax_record)

    if reallocate:
        await _reallocate_financial_year(user_id, fy, jurisdiction, db)

    for tax_record, gain_type in zip(tax_records, ordered_types, strict=True):
        logger.info(
            "Tax record created: id=%d txn=%d qty=%.4f gain=%.2f tax=%.2f (%s/%s)",
            tax_record.id,
            transaction_id,
            buckets[gain_type]["qty"],
            float(tax_record.gain_amount or 0.0),
            float(tax_record.tax_amount or 0.0),
            jurisdiction,
            gain_type,
        )

    return tax_records, fy, jurisdiction, sale_date


# ---------------------------------------------------------------------------
# Repairing tax records stored BEFORE the compute path was fixed
# ---------------------------------------------------------------------------
# A TaxRecord is a snapshot of what the compute path believed at the moment it
# ran. Seven defects have since been fixed in that path — brokerage was left
# out of the cost basis and of the expenses of transfer, the annual intra-head
# loss set-off was never applied, the Finance (No. 2) Act 2024 rates were used
# for transfers made before 23-Jul-2024, and a stock split recorded as a
# zero-cost adjustment lot fabricated both a loss and a short-term gain — but
# every record written before those fixes still holds the OLD numbers.
#
# ``/tax/summary`` and the ITR-ready export both read the STORED figures (see
# ``generate_tax_summary``), so a user keeps seeing the wrong tax until the
# records are re-derived. Nothing in the compute path does that on its own:
# it only re-derives when the LEDGER changes.
#
# The functions below are that missing re-derive, driven explicitly by the
# user through ``POST /api/v1/tax/recompute``.


async def _tax_record_groups(
    user_id: int,
    db: AsyncSession,
    financial_year: str | None = None,
) -> list[tuple[str, str]]:
    """Every ``(financial_year, jurisdiction)`` this user has records in.

    The jurisdiction is part of the key because set-off, exemptions and even
    the meaning of "financial year" are per-regime — an Indian FY and a German
    calendar year that share a label are two different pools, and netting
    across them would net rupees against euros.
    """
    stmt = (
        select(TaxRecord.financial_year, TaxRecord.tax_jurisdiction)
        .where(TaxRecord.user_id == user_id)
        .distinct()
    )
    if financial_year is not None:
        stmt = stmt.where(TaxRecord.financial_year == financial_year)
    result = await db.execute(stmt)
    return sorted((fy, jurisdiction) for fy, jurisdiction in result.all())


async def _group_snapshot(
    user_id: int,
    financial_year: str,
    jurisdiction: str,
    db: AsyncSession,
) -> dict:
    """Totals for one (FY, jurisdiction) as currently STORED.

    Taken before and after the re-derive so the caller can show the user the
    correction rather than silently applying it. ``currency`` is ``None``
    rather than a guess when a group somehow mixes currencies — a single
    summed figure would be meaningless there.
    """
    result = await db.execute(
        select(TaxRecord).where(
            TaxRecord.user_id == user_id,
            TaxRecord.financial_year == financial_year,
            TaxRecord.tax_jurisdiction == jurisdiction,
        )
    )
    records = list(result.scalars().all())
    currencies = {r.currency for r in records if r.currency}
    return {
        "records": len(records),
        "linked": sum(1 for r in records if r.transaction_id is not None),
        "unlinked": sum(1 for r in records if r.transaction_id is None),
        "total_tax": round(
            sum(float(r.tax_amount) for r in records if r.tax_amount is not None), 2
        ),
        "total_gain": round(
            sum(float(r.gain_amount) for r in records if r.gain_amount is not None), 2
        ),
        "currency": currencies.pop() if len(currencies) == 1 else None,
    }


async def _drop_orphaned_tax_records(
    user_id: int,
    financial_year: str,
    jurisdiction: str,
    db: AsyncSession,
) -> list[dict]:
    """Delete records whose linked transaction can no longer produce them.

    An orphan is PROVABLE: the record still names a ``transaction_id``, but
    that row is gone, is no longer a SELL, or no longer hangs off a portfolio
    of this user. Such a record cannot be re-derived and must not stand — it
    keeps consuming the s.112A exemption / Sparer-Pauschbetrag of everything
    else in the year, so leaving it silently overtaxes the records that are
    still real.

    Records with a NULL ``transaction_id`` are deliberately NOT touched. That
    is exactly the shape a CSV-imported or backup-restored record has
    (``csv_import_service`` and ``backup_service`` both create them without a
    transaction), and their figures are the user's own filed data — the FY
    allocators already refuse to rewrite them (``owned=False``). A ghost left
    by a deletion made before the ledger-invalidation fix has that same shape,
    and destroying a filed statement to remove a possible ghost is a far worse
    trade than reporting it: the caller gets an ``unlinked_records`` count so
    the user can look.
    """
    result = await db.execute(
        select(
            TaxRecord,
            Transaction.id,
            Transaction.transaction_type,
            Portfolio.user_id,
        )
        .outerjoin(Transaction, Transaction.id == TaxRecord.transaction_id)
        .outerjoin(Holding, Holding.id == Transaction.holding_id)
        .outerjoin(Portfolio, Portfolio.id == Holding.portfolio_id)
        .where(
            TaxRecord.user_id == user_id,
            TaxRecord.financial_year == financial_year,
            TaxRecord.tax_jurisdiction == jurisdiction,
            TaxRecord.transaction_id.isnot(None),
        )
        .order_by(TaxRecord.id)
    )

    dropped: list[dict] = []
    for record, txn_id, txn_type, owner_id in result.all():
        if txn_id is None:
            reason = "the sale it was derived from no longer exists"
        elif txn_type != "SELL":
            reason = f"its transaction is a {txn_type}, not a SELL"
        elif owner_id is None:
            reason = "its holding or portfolio no longer exists"
        elif owner_id != user_id:
            reason = "its transaction now belongs to a different user"
        else:
            continue

        dropped.append(
            {
                "record_id": record.id,
                "transaction_id": record.transaction_id,
                "gain_type": record.gain_type,
                "tax_amount": (
                    float(record.tax_amount) if record.tax_amount is not None else 0.0
                ),
                "reason": reason,
            }
        )
        await db.delete(record)

    if dropped:
        await db.flush()
        logger.warning(
            "Tax repair: dropped %d orphaned record(s) in FY %s (%s) for user %d",
            len(dropped),
            financial_year,
            jurisdiction,
            user_id,
        )
    return dropped


async def _recompute_financial_year(
    user_id: int,
    financial_year: str,
    jurisdiction: str,
    db: AsyncSession,
) -> dict:
    """Re-derive one stored (FY, jurisdiction) and report what moved.

    Recomputing the EARLIEST computed sell of the year is enough:
    ``compute_tax_for_transaction`` cascades over every later computed sell in
    the same year (FIFO makes each later sale depend on the ones before it)
    and then re-runs the annual set-off across the whole year. Anchoring
    anywhere later would leave the sales before the anchor on their old
    numbers.

    A sale that can no longer be re-derived at all (its purchase history is
    gone, so there is nothing to match FIFO against) is reported as a failure
    and its stale records are removed rather than left to stand as a figure
    this service can no longer justify; the next sale in the year becomes the
    anchor.
    """
    before = await _group_snapshot(user_id, financial_year, jurisdiction, db)
    orphans = await _drop_orphaned_tax_records(
        user_id, financial_year, jurisdiction, db
    )

    result = await db.execute(
        select(TaxRecord.transaction_id)
        .where(
            TaxRecord.user_id == user_id,
            TaxRecord.financial_year == financial_year,
            TaxRecord.tax_jurisdiction == jurisdiction,
            TaxRecord.transaction_id.isnot(None),
        )
        .order_by(TaxRecord.sale_date, TaxRecord.transaction_id)
    )
    candidates: list[int] = []
    for (txn_id,) in result.all():
        if txn_id not in candidates:
            candidates.append(txn_id)

    failures: list[dict] = []
    anchor: int | None = None
    for txn_id in candidates:
        # Counted BEFORE the attempt: _compute_tax_single drops the sale's own
        # records on its way to raising, so counting the removal afterwards
        # would report zero for records that really did go.
        held = (
            await db.execute(
                select(func.count())
                .select_from(TaxRecord)
                .where(
                    TaxRecord.transaction_id == txn_id,
                    TaxRecord.user_id == user_id,
                )
            )
        ).scalar_one()
        try:
            await compute_tax_for_transaction(txn_id, user_id, db)
        except ValueError as exc:
            # Belt and braces: the paths that raise before that drop step
            # (transaction missing, not a SELL) leave the records behind.
            await _drop_records(txn_id, user_id, db)
            failures.append(
                {
                    "transaction_id": txn_id,
                    "records_dropped": int(held),
                    "reason": str(exc),
                }
            )
            logger.warning(
                "Tax repair: FY %s (%s) sale txn=%d could not be re-derived "
                "(%s); its stale records were removed",
                financial_year,
                jurisdiction,
                txn_id,
                exc,
            )
            continue
        anchor = txn_id
        break

    # Always re-run the year's own allocation, even when an anchor succeeded:
    # a sale whose DATE was edited into a different financial year without the
    # ledger invalidation running lands its new records in the OTHER year, and
    # this year's set-off still has to be redone without it.
    await _reallocate_financial_year(user_id, financial_year, jurisdiction, db)

    after = await _group_snapshot(user_id, financial_year, jurisdiction, db)

    tax_delta = round(after["total_tax"] - before["total_tax"], 2)
    gain_delta = round(after["total_gain"] - before["total_gain"], 2)
    return {
        "financial_year": financial_year,
        "jurisdiction": jurisdiction,
        "currency": after["currency"] or before["currency"],
        "records_before": before["records"],
        "records_after": after["records"],
        # An anchor recompute re-derives every linked record left in the year,
        # via the cascade; with no anchor nothing was re-derived.
        "records_recomputed": after["linked"] if anchor is not None else 0,
        "orphans_dropped": len(orphans),
        "unlinked_records": after["unlinked"],
        "total_tax_before": before["total_tax"],
        "total_tax_after": after["total_tax"],
        "total_tax_delta": tax_delta,
        "total_gain_before": before["total_gain"],
        "total_gain_after": after["total_gain"],
        "changed": (
            before["records"] != after["records"]
            or abs(tax_delta) > 0.005
            or abs(gain_delta) > 0.005
        ),
        "orphans": orphans,
        "failures": failures,
    }


async def recompute_stored_tax_records(
    user_id: int,
    db: AsyncSession,
    financial_year: str | None = None,
) -> dict:
    """Re-derive a user's stored tax records and report the correction.

    ``financial_year=None`` covers every year the user has records in;
    otherwise only that label (in every jurisdiction that uses it).

    This is the repair path for records computed before the tax fixes landed.
    It is deliberately explicit — the user asks for it and is shown what
    changed — because a recompute rewrites capital-gains figures for years the
    user may already have FILED.

    No cross-year or cross-jurisdiction total is returned: an Indian FY is in
    rupees and a German one in euros, and one summed "total tax" over both is
    a number that means nothing. Each year carries its own before/after and
    its own currency.

    Returns ``{financial_year, years_scanned, years_changed, records_recomputed,
    orphans_dropped, unlinked_records, years: [...]}``.
    """
    groups = await _tax_record_groups(user_id, db, financial_year)

    years: list[dict] = []
    for fy, jurisdiction in groups:
        years.append(await _recompute_financial_year(user_id, fy, jurisdiction, db))

    return {
        "financial_year": financial_year,
        "years_scanned": len(years),
        "years_changed": sum(1 for y in years if y["changed"]),
        "records_recomputed": sum(y["records_recomputed"] for y in years),
        "orphans_dropped": sum(y["orphans_dropped"] for y in years),
        "unlinked_records": sum(y["unlinked_records"] for y in years),
        "years": years,
    }


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

    ``exemption_used`` comes from the SAME annual set-off allocation that
    writes each record's ``tax_amount``, so the statement cannot contradict
    the rows it is built from — the old summary netted losses for the
    exemption while the records it summed had been taxed one at a time, which
    is how a report ends up printing an implied tax rate that exists in no
    statute.

    ``total_tax`` stays the sum of the STORED figures: for records this
    service computed they are the allocation's own output, and for records a
    user imported from a broker or a CA statement their figure is the answer,
    not ours. Rows written before the set-off fix therefore keep their stale
    tax until that financial year is recomputed.

    Returns a summary dict with totals and breakdown by gain type.
    """
    alloc = await _fy_allocation(user_id, financial_year, jurisdiction, db)
    if alloc is not None:
        records = alloc["records"]
    else:
        result = await db.execute(
            select(TaxRecord).where(
                TaxRecord.user_id == user_id,
                TaxRecord.financial_year == financial_year,
                TaxRecord.tax_jurisdiction == jurisdiction,
            )
        )
        records = list(result.scalars().all())

    total_stcg = 0.0
    total_ltcg = 0.0
    total_tax = 0.0
    exemption_used = 0.0

    for r in records:
        gain = float(r.gain_amount) if r.gain_amount is not None else 0.0

        if r.gain_type in ("STCG",):
            total_stcg += gain
        elif r.gain_type in ("LTCG", "ABGELTUNGSSTEUER", "VORABPAUSCHALE"):
            total_ltcg += gain

        total_tax += float(r.tax_amount) if r.tax_amount is not None else 0.0

    if jurisdiction == "IN" and alloc is not None:
        # The exemption the allocation actually spent, after intra-head
        # set-off — the same figure the records were taxed on.
        exemption_used = alloc["exemption_used"]
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
    allowance on their taxable portion). Losses are set off against gains FIRST
    (§20(6) EStG, share losses only against share gains), so a year that nets
    to zero or below consumes none of the allowance; dividends are added on
    top. The allowance caps how much is offset.

    Germany's financial year is the calendar year, so ``financial_year`` is a
    plain year string like ``"2024"``.

    Returns ``{total_allowance, used, remaining, filing}``.
    """
    # The FY allocation resolves the filing status, applies Teilfreistellung,
    # runs the two-pot loss set-off and adds the year's German dividends — so
    # the tracker, the summary and the sale path can never disagree about what
    # the allowance was spent on.
    alloc = await _fy_allocation(user_id, financial_year, "DE", db, filing)
    if alloc is None:  # pragma: no cover - jurisdiction is hardcoded "DE"
        raise ValueError("German allowance requires the DE jurisdiction")

    total_allowance = alloc["total_allowance"]
    used = alloc["allowance_used"]

    return {
        "total_allowance": round(total_allowance, 2),
        "used": round(used, 2),
        "remaining": round(max(total_allowance - used, 0.0), 2),
        "filing": alloc["filing"],
    }


# ---------------------------------------------------------------------------
# German Vorabpauschale — per-portfolio estimate
# ---------------------------------------------------------------------------

def _vorab_months_held(first_buy: date | None, year: int) -> int:
    """Months counted for the §18 InvStG Vorabpauschale pro-rating.

    The Vorabpauschale is reduced by 1/12 for every full month that PRECEDES
    the month of acquisition, so a fund acquired in March counts 10 months
    (13 − 3). A fund already held on 1 January counts the full 12; one whose
    first purchase falls after the year in question counts 0.

    ``None`` (no BUY transaction recorded at all) falls back to 12 — the
    previous behaviour — rather than silently zeroing out the estimate.
    """
    if first_buy is None:
        return 12
    if first_buy.year < year:
        return 12
    if first_buy.year > year:
        return 0
    return 13 - first_buy.month


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

    Two §18 InvStG reductions are applied from stored data rather than assumed
    away:

    * **Distributions** — the fund's payouts during the year reduce the
      Basisertrag one-for-one. Taken from the ``dividends`` table, attributed by
      inflow date (``payment_date``, falling back to ``ex_date``).
    * **Months held** — the Vorabpauschale is reduced by 1/12 for every full
      month preceding the month of acquisition. Derived from the earliest BUY
      transaction; a fund already held on 1 January counts a full 12 months, and
      one first bought after the year counts 0.

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
    holding_ids = [h.id for h in holdings]

    # ── Distributions paid out during the year, per holding ────────────
    distributions_by_holding: dict[int, float] = {}
    if holding_ids:
        div_res = await db.execute(
            select(
                Dividend.holding_id,
                Dividend.total_amount,
                Dividend.ex_date,
                Dividend.payment_date,
            ).where(Dividend.holding_id.in_(holding_ids))
        )
        for hid, amount, ex_date, payment_date in div_res.all():
            inflow_date = payment_date or ex_date
            if inflow_date is not None and inflow_date.year == year:
                distributions_by_holding[hid] = (
                    distributions_by_holding.get(hid, 0.0) + float(amount)
                )

    # ── Earliest BUY per holding, for the months-held pro-rating ───────
    first_buy_by_holding: dict[int, date] = {}
    if holding_ids:
        buy_res = await db.execute(
            select(Transaction.holding_id, Transaction.date).where(
                Transaction.holding_id.in_(holding_ids),
                Transaction.transaction_type == "BUY",
            )
        )
        for hid, txn_date in buy_res.all():
            current = first_buy_by_holding.get(hid)
            if current is None or txn_date < current:
                first_buy_by_holding[hid] = txn_date

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
        distributions = distributions_by_holding.get(h.id, 0.0)
        months_held = _vorab_months_held(first_buy_by_holding.get(h.id), year)
        est = compute_vorabpauschale(
            value_start=cost_basis,
            value_end=current_value,
            distributions=distributions,
            basiszins_pct=basiszins,
            fund_type=h.fund_type,
            months_held=months_held,
        )
        funds.append(
            {
                "holding_id": h.id,
                "stock_symbol": h.stock_symbol,
                "fund_type": h.fund_type,
                "value_start": round(cost_basis, 2),
                "value_end": round(current_value, 2),
                "distributions": round(distributions, 2),
                "months_held": est["months_held"],
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

    For Indian holdings the estimate is taxed the way the engine would
    actually tax the sale, per FIFO lot:

    * a lot held for MORE than 12 months realizes a LONG-term loss, worth the
      s.112A rate (12.5 %) it can shelter, not the s.111A rate (20 %). The old
      code labelled every suggestion "STCG" and priced it at 20 %, advertising
      a saving the compute path then delivered as a smaller number or zero;
    * FIFO gives no lot choice, so a position whose older lots are in profit
      cannot be harvested without realizing that profit first. Gain buckets
      are therefore netted against loss buckets AT THEIR OWN RATES, and a
      position that is not a net loss is not suggested at all;
    * the cost basis is the FIFO open lots, not ``average_price`` — the
      weighted average diverges from FIFO after any partial sale, and it is
      the FIFO number the tax engine will use.

    ``potential_tax_saving`` remains a CEILING: it is only realisable if the
    year has enough compatible gains to absorb the loss (an LTCL needs LTCG
    above the annual exemption; an STCL can also land on LTCG at the lower
    rate). Germany is unchanged — since 2009 the Abgeltungssteuer has no
    holding-period split.

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
        .options(selectinload(Holding.transactions))
        .where(
            Portfolio.user_id == user_id,
            Holding.exchange.in_(exchange_list),
            Holding.current_price.isnot(None),
            Holding.cumulative_quantity > 0,
        )
    )
    holdings = result.scalars().all()

    today = date.today()
    stcg_rate, ltcg_rate = india_rates_for(today)

    suggestions: list[dict] = []
    for h in holdings:
        current_price = float(h.current_price)  # type: ignore[arg-type]
        avg_price = float(h.average_price)
        quantity = float(h.cumulative_quantity)

        if jurisdiction != "IN":
            if current_price >= avg_price:
                continue  # No unrealized loss
            unrealized_loss = round((avg_price - current_price) * quantity, 2)
            effective_rate = GERMANY_KAP_RATE * (1 + GERMANY_SOLI_RATE)
            suggestions.append({
                "holding_id": h.id,
                "stock_symbol": h.stock_symbol,
                "unrealized_loss": unrealized_loss,
                "short_term_loss": 0.0,
                "long_term_loss": 0.0,
                "potential_tax_saving": round(unrealized_loss * effective_rate, 2),
                "gain_type": "ABGELTUNGSSTEUER",
                "lots_known": True,
            })
            continue

        # India: bucket the still-open FIFO lots exactly as a sale today would
        # be taxed. A ledger that does not add up to the stored quantity (a
        # broker-synced position, or one with only part of its history
        # imported) cannot be bucketed honestly, so fall back to the
        # weighted-average estimate and SAY so rather than under-reporting.
        lots = build_open_lots(list(h.transactions))
        lot_qty = sum(lot["qty"] for lot in lots)
        lots_known = bool(lots) and abs(lot_qty - quantity) <= 1e-6
        buckets = {"STCG": 0.0, "LTCG": 0.0}
        if lots_known:
            for lot in lots:
                gain_type = classify_gain_type(lot["date"], today, "IN")
                buckets[gain_type] += (current_price - lot["price"]) * lot["qty"]
        else:
            buckets["STCG"] = (current_price - avg_price) * quantity

        st_net, lt_net = buckets["STCG"], buckets["LTCG"]
        if st_net + lt_net >= 0:
            continue  # the position as a whole is not at a loss

        # Note the argument order: max(0.0, -x) — max(-0.0, 0.0) is -0.0.
        st_loss = max(0.0, -st_net)
        lt_loss = max(0.0, -lt_net)
        # A forced gain in the other bucket costs tax at ITS own rate.
        potential_saving = round(-(st_net * stcg_rate + lt_net * ltcg_rate), 2)
        if potential_saving <= 0:
            continue  # harvesting this position would cost tax, not save it

        if st_loss and lt_loss:
            gain_type = "MIXED"
        elif lt_loss:
            gain_type = "LTCL"
        else:
            gain_type = "STCL"

        suggestions.append({
            "holding_id": h.id,
            "stock_symbol": h.stock_symbol,
            "unrealized_loss": round(-(st_net + lt_net), 2),
            "short_term_loss": round(st_loss, 2),
            "long_term_loss": round(lt_loss, 2),
            "potential_tax_saving": potential_saving,
            "gain_type": gain_type,
            "lots_known": lots_known,
        })

    # Sort by highest potential tax saving first
    suggestions.sort(key=lambda s: s["potential_tax_saving"], reverse=True)
    return suggestions
