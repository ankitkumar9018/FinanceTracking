"""Portfolio Concentration & Diversification Service.

Scores how well-spread a portfolio is across single names, sectors, market-cap
buckets, and exchanges.  The overall score is anchored on the
Herfindahl-Hirschman Index (HHI) of holding weights.

Valuation
---------
Each holding is valued at ``cumulative_quantity * (current_price or
average_price)`` — the same convention used by the drift and sector-rotation
services.

Scoring formula
---------------
Let ``w_i`` be each holding's *fractional* weight (0-1) of total portfolio
value.  The HHI is ``sum(w_i ** 2)`` and the *effective number of holdings* is
``N_eff = 1 / HHI`` (equals N for N equally-weighted holdings, collapses toward
1 as one name dominates).  We combine three sub-scores into a 0-100 result:

    diversification  = min(N_eff / TARGET_HOLDINGS, 1) * 100      (weight 0.50)
    sector_spread    = min(sector_N_eff / TARGET_SECTORS, 1) * 100 (weight 0.25)
    top_holding      = (1 - min(top_weight / TOP_WEIGHT_CAP, 1)) * 100 (weight 0.25)

    overall = 0.50 * diversification + 0.25 * sector_spread + 0.25 * top_holding

More holdings, an even spread, wider sector coverage, and a small largest
position all push the score up.  A single-name portfolio lands near 0 (grade F);
~15 evenly-weighted holdings across ~8 sectors approaches 100 (grade A).
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.holding import Holding
from app.services.market_data_service import _ticker_symbol

logger = logging.getLogger(__name__)

# Defaults (percentage points)
DEFAULT_SINGLE_NAME_THRESHOLD: float = 15.0
DEFAULT_SECTOR_THRESHOLD: float = 40.0

_UNKNOWN = "Unknown"

# Scoring targets — "full marks" reference points.
_TARGET_HOLDINGS: float = 15.0  # effective holdings for max diversification score
_TARGET_SECTORS: float = 8.0    # effective sectors for max spread score
_TOP_WEIGHT_CAP: float = 0.50   # a single name at/above this weight => 0 sub-score

# Market-cap bucket thresholds, in the instrument's own currency.  yfinance
# reports marketCap in the ticker's native currency, so INR-listed names use
# SEBI-style rupee cutoffs while USD/EUR names use dollar-scale cutoffs.
_MCAP_THRESHOLDS: dict[str, tuple[float, float]] = {
    # currency: (large_min, mid_min)
    "INR": (200e9, 50e9),   # ~₹20,000 Cr large-cap, ~₹5,000 Cr mid-cap
}
_MCAP_DEFAULT: tuple[float, float] = (10e9, 2e9)  # USD/EUR-scale


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _market_value(holding: Holding) -> float:
    """Current market value of a holding (falls back to average price)."""
    price = (
        float(holding.current_price)
        if holding.current_price is not None
        else float(holding.average_price)
    )
    return float(holding.cumulative_quantity) * price


def _effective_count(weights: list[float]) -> float:
    """Effective number of buckets = 1 / sum(w_i^2) for fractional weights."""
    hhi = sum(w * w for w in weights)
    return (1.0 / hhi) if hhi > 0 else 0.0


def _grade(score: float) -> str:
    """Map a 0-100 score to an A-F letter grade."""
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def _market_cap_bucket(market_cap: float | None, currency: str | None) -> str:
    """Classify a market cap into Large/Mid/Small (or Unknown)."""
    if market_cap is None or market_cap <= 0:
        return _UNKNOWN
    large_min, mid_min = _MCAP_THRESHOLDS.get(
        (currency or "").upper(), _MCAP_DEFAULT
    )
    if market_cap >= large_min:
        return "Large"
    if market_cap >= mid_min:
        return "Mid"
    return "Small"


def _sync_fetch_info(ticker_str: str) -> dict:
    """Fetch yfinance ``.info`` synchronously (runs in a thread). Best-effort."""
    try:
        import yfinance as yf

        return yf.Ticker(ticker_str).info or {}
    except Exception:
        return {}


async def _fetch_info_map(
    tickers: list[tuple[str, str]],
    timeout: float = 6.0,
) -> dict[str, dict]:
    """Fetch ``.info`` for a set of (symbol, exchange) pairs, concurrently.

    Optional and non-blocking by design: every fetch is bounded by *timeout*
    and any failure yields an empty dict, so a slow or offline yfinance simply
    degrades sector/market-cap data to "Unknown" without stalling the request.
    Keyed by the resolved yfinance ticker string.
    """
    if not tickers:
        return {}

    async def _one(sym: str, exch: str) -> tuple[str, dict]:
        ticker_str = _ticker_symbol(sym, exch)
        try:
            info = await asyncio.wait_for(
                asyncio.to_thread(_sync_fetch_info, ticker_str), timeout=timeout
            )
        except Exception:  # best-effort: timeouts/network errors => Unknown
            info = {}
        return ticker_str, info

    results = await asyncio.gather(
        *(_one(s, e) for s, e in tickers), return_exceptions=True
    )
    info_map: dict[str, dict] = {}
    for r in results:
        if isinstance(r, tuple):
            info_map[r[0]] = r[1]
    return info_map


def _neutral_state(
    single_name_threshold: float,
    sector_threshold: float,
) -> dict:
    """Return a neutral zero-state for empty / zero-value portfolios."""
    return {
        "total_value": 0.0,
        "holdings_count": 0,
        "effective_holdings": 0.0,
        "herfindahl_index": 0.0,
        "overall_score": 0.0,
        "grade": "N/A",
        "single_name_threshold": single_name_threshold,
        "sector_threshold": sector_threshold,
        "top_holdings": [],
        "by_sector": [],
        "by_market_cap": [],
        "by_exchange": [],
        "warnings": [],
    }


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

async def analyze_concentration(
    portfolio_id: int,
    db: AsyncSession,
    *,
    single_name_threshold: float = DEFAULT_SINGLE_NAME_THRESHOLD,
    sector_threshold: float = DEFAULT_SECTOR_THRESHOLD,
    fetch_external: bool = True,
) -> dict:
    """Compute concentration & diversification metrics for a portfolio.

    Parameters
    ----------
    single_name_threshold, sector_threshold
        Percentage-point limits above which a holding / sector is flagged.
    fetch_external
        When True, missing sectors and market caps are backfilled from
        yfinance ``.info`` (best-effort, bounded by a per-call timeout).
    """
    result = await db.execute(
        select(Holding).where(Holding.portfolio_id == portfolio_id)
    )
    holdings = list(result.scalars().all())

    if not holdings:
        return _neutral_state(single_name_threshold, sector_threshold)

    values = [_market_value(h) for h in holdings]
    total_value = sum(values)
    if total_value <= 0:
        return _neutral_state(single_name_threshold, sector_threshold)

    # -- Optionally backfill sector / market-cap from yfinance .info --------
    info_map: dict[str, dict] = {}
    if fetch_external:
        # market-cap bucketing always needs .info, and it doubles as the sector
        # fallback, so fetch once per holding (best-effort, bounded timeout).
        tickers = [(h.stock_symbol, h.exchange) for h in holdings]
        try:
            info_map = await _fetch_info_map(tickers)
        except Exception:
            logger.debug("Concentration .info backfill failed", exc_info=True)
            info_map = {}

    # -- Per-holding weights & top holdings --------------------------------
    fractions = [v / total_value for v in values]
    hhi = sum(f * f for f in fractions)
    effective_holdings = (1.0 / hhi) if hhi > 0 else 0.0

    top_holdings: list[dict] = []
    sector_values: dict[str, float] = defaultdict(float)
    mcap_values: dict[str, float] = defaultdict(float)
    exchange_values: dict[str, float] = defaultdict(float)

    for h, mv, frac in zip(holdings, values, fractions):
        weight_pct = round(frac * 100, 2)
        info = info_map.get(_ticker_symbol(h.stock_symbol, h.exchange), {})

        # Sector: prefer the stored value, else yfinance .info, else Unknown.
        sector = h.sector or info.get("sector") or _UNKNOWN
        sector_values[sector] += mv

        # Market cap bucket (best-effort).
        market_cap = info.get("marketCap") if info else None
        bucket = _market_cap_bucket(market_cap, h.currency)
        mcap_values[bucket] += mv

        exchange_values[h.exchange or _UNKNOWN] += mv

        top_holdings.append(
            {
                "holding_id": h.id,
                "stock_symbol": h.stock_symbol,
                "stock_name": h.stock_name,
                "exchange": h.exchange,
                "sector": sector,
                "value": round(mv, 2),
                "weight_pct": weight_pct,
                "flagged": weight_pct > single_name_threshold,
            }
        )

    top_holdings.sort(key=lambda x: x["weight_pct"], reverse=True)

    # -- Group breakdowns ---------------------------------------------------
    def _breakdown(key_name: str, values_map: dict[str, float], threshold: float | None):
        rows = []
        for name, val in values_map.items():
            wpct = round((val / total_value) * 100, 2)
            row = {key_name: name, "value": round(val, 2), "weight_pct": wpct}
            if threshold is not None:
                row["flagged"] = wpct > threshold
            rows.append(row)
        rows.sort(key=lambda x: x["weight_pct"], reverse=True)
        return rows

    by_sector = _breakdown("sector", sector_values, sector_threshold)
    by_market_cap = _breakdown("bucket", mcap_values, None)
    by_exchange = _breakdown("exchange", exchange_values, None)

    # -- Scoring ------------------------------------------------------------
    sector_fractions = [v / total_value for v in sector_values.values()]
    sector_neff = _effective_count(sector_fractions)
    top_weight = max(fractions) if fractions else 0.0

    diversification = min(effective_holdings / _TARGET_HOLDINGS, 1.0) * 100
    sector_spread = min(sector_neff / _TARGET_SECTORS, 1.0) * 100
    top_holding_score = (1.0 - min(top_weight / _TOP_WEIGHT_CAP, 1.0)) * 100

    overall_score = (
        0.50 * diversification + 0.25 * sector_spread + 0.25 * top_holding_score
    )
    overall_score = round(max(0.0, min(100.0, overall_score)), 1)
    grade = _grade(overall_score)

    # -- Warnings -----------------------------------------------------------
    warnings: list[str] = []
    for row in top_holdings:
        if row["flagged"]:
            warnings.append(
                f"{row['stock_symbol']} is {row['weight_pct']:.1f}% of the portfolio "
                f"(over the {single_name_threshold:.0f}% single-name limit)."
            )
    for row in by_sector:
        if row.get("flagged"):
            warnings.append(
                f"{row['sector']} sector is {row['weight_pct']:.1f}% of the portfolio "
                f"(over the {sector_threshold:.0f}% limit)."
            )
    if effective_holdings and effective_holdings < 5:
        warnings.append(
            f"Portfolio is concentrated: only {effective_holdings:.1f} effective "
            f"holdings out of {len(holdings)}."
        )

    return {
        "total_value": round(total_value, 2),
        "holdings_count": len(holdings),
        "effective_holdings": round(effective_holdings, 2),
        "herfindahl_index": round(hhi, 4),
        "overall_score": overall_score,
        "grade": grade,
        "single_name_threshold": single_name_threshold,
        "sector_threshold": sector_threshold,
        "top_holdings": top_holdings,
        "by_sector": by_sector,
        "by_market_cap": by_market_cap,
        "by_exchange": by_exchange,
        "warnings": warnings,
    }
