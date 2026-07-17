"""Mutual fund service: NAV fetching, XIRR calculation, portfolio tracking."""

from __future__ import annotations

import asyncio
import logging
import math
from datetime import date

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mutual_fund import MutualFund
from app.models.portfolio import Portfolio
from app.schemas.mutual_fund import MutualFundCreate, MutualFundUpdate
from app.services.xirr_service import CashFlow, xirr

logger = logging.getLogger(__name__)

MFAPI_BASE = "https://api.mfapi.in/mf"
HTTP_TIMEOUT = 10.0

# yfinance is the best-effort source for fund constituents / expense ratios.
# It only resolves schemes whose ``scheme_code`` is an actual fund/ETF ticker
# (e.g. a US ETF symbol or a Yahoo fund id like ``0P0000XXXX``). Numeric AMFI
# scheme codes used by mfapi.in have no yfinance mapping, so those funds are
# reported as unavailable rather than fabricated.
_YF_FETCH_TIMEOUT = 12.0
# Above this expense ratio (as a decimal fraction) a fund is flagged high-fee.
_HIGH_FEE_THRESHOLD = 0.01  # 1.0% p.a.
# Assumed gross annual return used to project fee drag over time. Documented
# and returned to the caller so the projection is transparent, not implied fact.
_DEFAULT_ASSUMED_RETURN = 0.10


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_portfolio_for_user(
    portfolio_id: int,
    user_id: int,
    db: AsyncSession,
) -> Portfolio:
    """Fetch a portfolio ensuring it belongs to the user."""
    result = await db.execute(
        select(Portfolio).where(
            Portfolio.id == portfolio_id,
            Portfolio.user_id == user_id,
        )
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise ValueError("Portfolio not found or does not belong to the current user")
    return portfolio


async def _get_fund_for_user(
    fund_id: int,
    user_id: int,
    db: AsyncSession,
) -> MutualFund:
    """Fetch a mutual fund ensuring it belongs to a portfolio owned by the user."""
    result = await db.execute(
        select(MutualFund)
        .join(Portfolio, MutualFund.portfolio_id == Portfolio.id)
        .where(MutualFund.id == fund_id, Portfolio.user_id == user_id)
    )
    fund = result.scalar_one_or_none()
    if fund is None:
        raise ValueError("Mutual fund not found or does not belong to the current user")
    return fund


# ---------------------------------------------------------------------------
# NAV fetching from mfapi.in
# ---------------------------------------------------------------------------

async def fetch_nav(scheme_code: str) -> float | None:
    """Fetch the latest NAV for a mutual fund scheme from mfapi.in.

    Returns the NAV as a float, or None on failure.
    """
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(f"{MFAPI_BASE}/{scheme_code}/latest")
            resp.raise_for_status()
            data = resp.json()

            # mfapi.in returns {"meta": {...}, "data": [{"date": "...", "nav": "..."}]}
            nav_data = data.get("data")
            if nav_data and len(nav_data) > 0:
                nav_str = nav_data[0].get("nav")
                if nav_str is not None:
                    return float(nav_str)
    except Exception:
        logger.warning("Failed to fetch NAV for scheme %s", scheme_code, exc_info=True)

    return None


async def search_schemes(query: str) -> list[dict]:
    """Search mutual fund schemes by name on mfapi.in.

    Returns a list of {scheme_code, scheme_name} dicts.
    """
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.get(f"{MFAPI_BASE}/search", params={"q": query})
            resp.raise_for_status()
            data = resp.json()

            # mfapi.in returns a list of {"schemeCode": ..., "schemeName": ...}
            results: list[dict] = []
            if isinstance(data, list):
                for item in data:
                    results.append({
                        "scheme_code": str(item.get("schemeCode", "")),
                        "scheme_name": item.get("schemeName", ""),
                    })
            return results
    except Exception:
        logger.warning("Failed to search schemes for query %r", query, exc_info=True)

    return []


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------

async def create_mutual_fund(
    data: MutualFundCreate,
    user_id: int,
    db: AsyncSession,
) -> MutualFund:
    """Create a new mutual fund record in a user's portfolio.

    Attempts to fetch the current NAV and set current_value automatically.
    """
    await _get_portfolio_for_user(data.portfolio_id, user_id, db)

    fund = MutualFund(
        portfolio_id=data.portfolio_id,
        scheme_code=data.scheme_code,
        scheme_name=data.scheme_name,
        folio_number=data.folio_number,
        units=data.units,
        nav=data.nav,
        invested_amount=data.invested_amount,
    )

    # Try to fetch the current NAV and compute current value
    current_nav = await fetch_nav(data.scheme_code)
    if current_nav is not None:
        fund.nav = current_nav
        fund.current_value = round(data.units * current_nav, 4)
    else:
        # Fall back to user-provided NAV for current value
        fund.current_value = round(data.units * data.nav, 4)

    db.add(fund)
    await db.flush()
    await db.refresh(fund)
    return fund


async def list_mutual_funds(
    portfolio_id: int | None,
    user_id: int,
    db: AsyncSession,
) -> list[MutualFund]:
    """List mutual funds for a specific portfolio or all user's portfolios."""
    stmt = (
        select(MutualFund)
        .join(Portfolio, MutualFund.portfolio_id == Portfolio.id)
        .where(Portfolio.user_id == user_id)
    )

    if portfolio_id is not None:
        stmt = stmt.where(MutualFund.portfolio_id == portfolio_id)

    stmt = stmt.order_by(MutualFund.scheme_name.asc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def update_mutual_fund(
    fund_id: int,
    user_id: int,
    data: MutualFundUpdate,
    db: AsyncSession,
) -> MutualFund:
    """Update a mutual fund's fields."""
    fund = await _get_fund_for_user(fund_id, user_id, db)

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(fund, key, value)

    await db.flush()
    await db.refresh(fund)
    return fund


async def delete_mutual_fund(
    fund_id: int,
    user_id: int,
    db: AsyncSession,
) -> None:
    """Delete a mutual fund record after verifying ownership."""
    fund = await _get_fund_for_user(fund_id, user_id, db)
    await db.delete(fund)
    await db.flush()


# ---------------------------------------------------------------------------
# Refresh NAVs
# ---------------------------------------------------------------------------

async def refresh_all_navs(user_id: int, db: AsyncSession) -> dict:
    """Refresh current_value for all of a user's mutual funds by fetching
    the latest NAV from mfapi.in.

    Returns a dict with counts of updated and failed funds.
    """
    funds = await list_mutual_funds(portfolio_id=None, user_id=user_id, db=db)

    updated = 0
    failed = 0

    for fund in funds:
        nav = await fetch_nav(fund.scheme_code)
        if nav is not None:
            fund.nav = nav
            fund.current_value = round(float(fund.units) * nav, 4)
            updated += 1
        else:
            failed += 1

    if updated > 0:
        await db.flush()

    return {"updated": updated, "failed": failed, "total": len(funds)}


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

async def get_mf_summary(user_id: int, db: AsyncSession) -> dict:
    """Compute a mutual fund summary for the user.

    Returns:
        total_invested: sum of invested_amount
        total_current_value: sum of current_value (or invested_amount if null)
        total_gain: total_current_value - total_invested
        gain_percent: (total_gain / total_invested) * 100
        xirr: None (placeholder -- needs cash flow history)
        fund_count: number of MF records
    """
    funds = await list_mutual_funds(portfolio_id=None, user_id=user_id, db=db)

    total_invested = 0.0
    total_current_value = 0.0
    cash_flows: list[CashFlow] = []
    today = date.today()

    for fund in funds:
        invested = float(fund.invested_amount)
        current = float(fund.current_value) if fund.current_value is not None else invested
        total_invested += invested
        total_current_value += current

        # Outflow (buy) dated at the fund's investment date. The model has no
        # dedicated purchase/investment date, so fall back to created_at's date.
        buy_date = fund.created_at.date() if fund.created_at is not None else today
        cash_flows.append(CashFlow(date=buy_date, amount=-invested))

    # Single aggregate inflow of the current value, dated today.
    cash_flows.append(CashFlow(date=today, amount=total_current_value))

    total_gain = total_current_value - total_invested
    gain_percent: float | None = None
    if total_invested > 0:
        gain_percent = round((total_gain / total_invested) * 100, 2)

    # xirr() returns None when there are fewer than 2 distinct dates or it
    # fails to converge; surface it as a percentage otherwise.
    xirr_pct: float | None = None
    xirr_decimal = xirr(cash_flows)
    if xirr_decimal is not None:
        xirr_pct = round(xirr_decimal * 100, 2)

    return {
        "total_invested": round(total_invested, 2),
        "total_current_value": round(total_current_value, 2),
        "total_gain": round(total_gain, 2),
        "gain_percent": gain_percent,
        "xirr": xirr_pct,
        "fund_count": len(funds),
    }


# ---------------------------------------------------------------------------
# Best-effort yfinance helpers (constituents + expense ratio)
# ---------------------------------------------------------------------------

def _safe_float(val) -> float | None:
    """Convert a value to float, returning None for NaN/Inf/invalid values."""
    if val is None:
        return None
    try:
        f = float(val)
        return None if math.isnan(f) or math.isinf(f) else f
    except (ValueError, TypeError):
        return None


def _ticker_candidate(scheme_code: str, scheme_name: str) -> str | None:
    """Return a plausible yfinance ticker for a scheme, or None.

    mfapi.in uses purely-numeric AMFI scheme codes which have no yfinance
    mapping, so those return None. Alphanumeric codes (US ETF symbols, Yahoo
    fund ids like ``0P0000XXXX``) are passed through as best-effort candidates.
    """
    code = (scheme_code or "").strip()
    if not code or code.isdigit():
        return None
    return code


def _sync_fetch_constituents(ticker_str: str) -> list[dict] | None:
    """Best-effort fetch of a fund/ETF's top equity holdings via yfinance.

    Returns a list of ``{"symbol", "name", "weight"}`` (weight is a 0-1
    fraction) or None if constituents cannot be determined. Runs in a thread.
    """
    try:
        import yfinance as yf

        ticker = yf.Ticker(ticker_str)
        funds_data = getattr(ticker, "funds_data", None)
        if funds_data is None:
            return None

        try:
            top = funds_data.top_holdings
        except Exception:
            return None

        if top is None or getattr(top, "empty", True):
            return None

        cols = list(top.columns)
        pct_col = next(
            (c for c in cols if str(c).lower().replace(" ", "") in ("holdingpercent", "percent", "weight")),
            None,
        )
        name_col = next((c for c in cols if str(c).lower() == "name"), None)

        holdings: list[dict] = []
        for idx, row in top.iterrows():
            weight = _safe_float(row[pct_col]) if pct_col is not None else None
            if weight is None:
                continue
            # Some feeds express the weight as a percentage (0-100); normalise.
            if weight > 1.5:
                weight = weight / 100.0
            symbol = str(idx).strip().upper()
            name = str(row[name_col]).strip() if name_col is not None else symbol
            holdings.append({"symbol": symbol, "name": name or symbol, "weight": weight})

        return holdings or None
    except Exception:
        logger.warning("yfinance constituents fetch failed for %s", ticker_str, exc_info=True)
        return None


def _sync_fetch_expense_ratio(ticker_str: str) -> float | None:
    """Best-effort fetch of a fund/ETF expense ratio (0-1 fraction) via yfinance.

    Tries ``.info`` keys first, then ``funds_data.fund_operations``. Runs in a
    thread. Returns None when the ratio cannot be determined.
    """
    try:
        import yfinance as yf

        ticker = yf.Ticker(ticker_str)

        try:
            info = ticker.info or {}
        except Exception:
            info = {}

        for key in ("annualReportExpenseRatio", "netExpenseRatio", "expenseRatio"):
            er = _safe_float(info.get(key))
            if er is not None and er > 0:
                # yfinance reports these as fractions (0.0018) but guard against
                # feeds that return a percentage (0.18).
                return er / 100.0 if er > 1.5 else er

        # Fallback: fund_operations DataFrame carries an expense-ratio row.
        funds_data = getattr(ticker, "funds_data", None)
        if funds_data is not None:
            try:
                ops = funds_data.fund_operations
            except Exception:
                ops = None
            if ops is not None and not getattr(ops, "empty", True):
                for label in ops.index:
                    if "expense" in str(label).lower():
                        er = _safe_float(ops.loc[label].iloc[0])
                        if er is not None and er > 0:
                            return er / 100.0 if er > 1.5 else er
        return None
    except Exception:
        logger.warning("yfinance expense-ratio fetch failed for %s", ticker_str, exc_info=True)
        return None


async def _fetch_constituents(ticker_str: str) -> list[dict] | None:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_sync_fetch_constituents, ticker_str),
            timeout=_YF_FETCH_TIMEOUT,
        )
    except Exception:
        return None


async def _fetch_expense_ratio(ticker_str: str) -> float | None:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_sync_fetch_expense_ratio, ticker_str),
            timeout=_YF_FETCH_TIMEOUT,
        )
    except Exception:
        return None


def _fund_value(fund: MutualFund) -> float:
    """Current market value of a holding, falling back to invested amount."""
    if fund.current_value is not None:
        return float(fund.current_value)
    return float(fund.invested_amount)


# ---------------------------------------------------------------------------
# Overlap X-Ray
# ---------------------------------------------------------------------------

async def get_overlap_xray(user_id: int, db: AsyncSession) -> dict:
    """Portfolio overlap X-ray across a user's mutual fund holdings.

    For each held scheme, attempts a best-effort fetch of its underlying equity
    constituents (via yfinance when the scheme maps to a fund/ETF ticker). It
    then computes a pairwise overlap matrix (sum of ``min(weight_a, weight_b)``
    over common stocks) and a look-through single-stock concentration across
    funds. Funds without constituent data are flagged and excluded from the
    matrix; the response is always valid and never fabricates holdings.
    """
    funds = await list_mutual_funds(portfolio_id=None, user_id=user_id, db=db)

    total_value = sum(_fund_value(f) for f in funds) or 0.0

    # Fetch constituents concurrently (best-effort).
    candidates = [_ticker_candidate(f.scheme_code, f.scheme_name) for f in funds]
    fetched = await asyncio.gather(
        *[
            _fetch_constituents(c) if c is not None else _noop_none()
            for c in candidates
        ]
    )

    fund_infos: list[dict] = []
    for fund, holdings in zip(funds, fetched, strict=True):
        available = bool(holdings)
        fund_infos.append(
            {
                "scheme_code": fund.scheme_code,
                "scheme_name": fund.scheme_name,
                "constituents_available": available,
                "holdings_count": len(holdings) if holdings else 0,
                "value": _fund_value(fund),
                "_holdings": {h["symbol"]: h for h in holdings} if holdings else {},
            }
        )

    covered = [fi for fi in fund_infos if fi["constituents_available"]]

    # Pairwise overlap matrix (only between funds that both have constituents).
    overlap_matrix: list[dict] = []
    for i in range(len(covered)):
        for j in range(i + 1, len(covered)):
            a, b = covered[i], covered[j]
            common = set(a["_holdings"]) & set(b["_holdings"])
            overlap = sum(
                min(a["_holdings"][s]["weight"], b["_holdings"][s]["weight"])
                for s in common
            )
            overlap_matrix.append(
                {
                    "fund_a": a["scheme_name"],
                    "fund_b": b["scheme_name"],
                    "fund_a_code": a["scheme_code"],
                    "fund_b_code": b["scheme_code"],
                    "overlap_pct": round(overlap * 100, 2),
                    "common_holdings": len(common),
                }
            )

    # Look-through single-stock concentration across funds.
    look_through: dict[str, dict] = {}
    for fi in covered:
        weight_share = (fi["value"] / total_value) if total_value > 0 else 0.0
        for sym, h in fi["_holdings"].items():
            entry = look_through.setdefault(
                sym,
                {"symbol": sym, "name": h["name"], "funds_holding": 0, "look_through_pct": 0.0},
            )
            entry["funds_holding"] += 1
            entry["look_through_pct"] += h["weight"] * weight_share * 100.0

    top_common = sorted(
        (
            {
                "symbol": e["symbol"],
                "name": e["name"],
                "funds_holding": e["funds_holding"],
                "look_through_pct": round(e["look_through_pct"], 2),
            }
            for e in look_through.values()
        ),
        key=lambda e: (e["funds_holding"], e["look_through_pct"]),
        reverse=True,
    )[:15]

    coverage_note = _overlap_coverage_note(len(funds), len(covered))

    return {
        "funds": [
            {
                "scheme_code": fi["scheme_code"],
                "scheme_name": fi["scheme_name"],
                "constituents_available": fi["constituents_available"],
                "holdings_count": fi["holdings_count"],
            }
            for fi in fund_infos
        ],
        "overlap_matrix": overlap_matrix,
        "top_common_holdings": top_common,
        "funds_with_constituents": len(covered),
        "total_funds": len(funds),
        "coverage_note": coverage_note,
    }


async def _noop_none() -> None:
    """Awaitable that yields None (placeholder for un-mappable schemes)."""
    return None


def _overlap_coverage_note(total: int, covered: int) -> str:
    if total < 2:
        return (
            "Overlap analysis needs at least two mutual fund holdings. "
            "Add another fund to compare their underlying constituents."
        )
    if covered == 0:
        return (
            "No underlying constituent data could be retrieved for your funds. "
            "mfapi.in provides NAV only, and none of your scheme codes map to a "
            "fund/ETF holdings source (numeric AMFI codes have no such mapping). "
            "Overlap cannot be computed for these schemes."
        )
    if covered < total:
        return (
            f"Constituents available for {covered} of {total} funds. mfapi.in "
            "provides NAV only; holdings are sourced best-effort from yfinance "
            "for schemes that map to a fund/ETF ticker, and cover only each "
            "fund's top holdings. Overlap is computed among covered funds only."
        )
    return (
        f"Constituents available for all {total} funds (best-effort via "
        "yfinance top holdings). Overlap reflects each fund's top holdings, "
        "so figures are a lower bound on true overlap."
    )


# ---------------------------------------------------------------------------
# Expense-ratio / fee-drag analysis
# ---------------------------------------------------------------------------

async def get_expense_analysis(
    user_id: int,
    db: AsyncSession,
    assumed_return: float = _DEFAULT_ASSUMED_RETURN,
) -> dict:
    """Value-weighted expense ratio and multi-year fee-drag projection.

    Expense ratios are read best-effort from yfinance (``.info`` expense-ratio
    keys, then ``funds_data.fund_operations``) for schemes that map to a ticker.
    Unknown ratios are surfaced clearly and excluded from the weighted average
    and drag projection. Fee drag compares compounding at the assumed gross
    return versus at (gross - expense ratio) over 5/10/20 years.
    """
    funds = await list_mutual_funds(portfolio_id=None, user_id=user_id, db=db)

    candidates = [_ticker_candidate(f.scheme_code, f.scheme_name) for f in funds]
    ratios = await asyncio.gather(
        *[
            _fetch_expense_ratio(c) if c is not None else _noop_none()
            for c in candidates
        ]
    )

    by_fund: list[dict] = []
    weighted_sum = 0.0
    covered_value = 0.0
    horizons = (5, 10, 20)
    projected_drag = {f"{h}y": 0.0 for h in horizons}
    covered_count = 0

    for fund, er in zip(funds, ratios, strict=True):
        value = _fund_value(fund)
        available = er is not None
        annual_fee_cost = round(value * er, 2) if available else None
        is_high_fee = bool(available and er >= _HIGH_FEE_THRESHOLD)

        if available:
            covered_count += 1
            weighted_sum += er * value
            covered_value += value
            net = assumed_return - er
            for h in horizons:
                no_fee = value * (1 + assumed_return) ** h
                with_fee = value * (1 + net) ** h
                projected_drag[f"{h}y"] += no_fee - with_fee

        by_fund.append(
            {
                "scheme_code": fund.scheme_code,
                "scheme_name": fund.scheme_name,
                "current_value": round(value, 2),
                "expense_ratio": round(er, 6) if available else None,
                "expense_ratio_pct": round(er * 100, 3) if available else None,
                "expense_ratio_available": available,
                "annual_fee_cost": annual_fee_cost,
                "is_high_fee": is_high_fee,
            }
        )

    weighted_expense_ratio = (
        round(weighted_sum / covered_value, 6) if covered_value > 0 else None
    )
    projected_drag = {k: round(v, 2) for k, v in projected_drag.items()}

    return {
        "weighted_expense_ratio": weighted_expense_ratio,
        "weighted_expense_ratio_pct": (
            round(weighted_expense_ratio * 100, 3)
            if weighted_expense_ratio is not None
            else None
        ),
        "by_fund": by_fund,
        "projected_drag": projected_drag,
        "assumed_annual_return": assumed_return,
        "high_fee_threshold_pct": round(_HIGH_FEE_THRESHOLD * 100, 2),
        "funds_with_expense_data": covered_count,
        "total_funds": len(funds),
        "coverage_note": _expense_coverage_note(len(funds), covered_count),
    }


def _expense_coverage_note(total: int, covered: int) -> str:
    if total == 0:
        return "Add mutual funds to analyse their expense ratios and fee drag."
    if covered == 0:
        return (
            "No expense-ratio data could be retrieved for your funds. mfapi.in "
            "does not publish expense ratios, and none of your scheme codes map "
            "to a yfinance fund/ETF ticker (numeric AMFI codes have no mapping). "
            "Enter ratios from your fund fact sheet for an accurate estimate."
        )
    if covered < total:
        return (
            f"Expense ratios found for {covered} of {total} funds via yfinance. "
            "Funds without data are excluded from the weighted average and drag "
            "projection. Projections assume a constant gross annual return and "
            "are illustrative, not guaranteed."
        )
    return (
        f"Expense ratios found for all {total} funds via yfinance. Projections "
        "assume a constant gross annual return and are illustrative estimates, "
        "not guarantees."
    )
