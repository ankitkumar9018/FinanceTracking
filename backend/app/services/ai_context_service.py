"""Assemble a compact, grounded portfolio context for the LLM assistant.

Feeds the app's ALREADY-COMPUTED numbers — holdings, P&L, diversification,
allocation drift, and risk metrics — to the model so its analysis is specific
to the user's real portfolio instead of generic filler.

Every section is best-effort: if a service errors or returns nothing, that
section is silently skipped so the chat never breaks. Nothing here hits the
network in the hot path (``analyze_concentration`` is called with
``fetch_external=False``; risk metrics come from stored price history).
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.portfolio import Portfolio

logger = logging.getLogger(__name__)

# Bounds so the prompt can't grow without limit for power users. Per-portfolio
# holdings are capped, plus a global budget across all portfolios, plus a cap on
# how many portfolios are detailed at all. Totals/diversification lines still
# summarise everything even when individual holdings are truncated.
_MAX_HOLDINGS = 30
_MAX_TOTAL_HOLDINGS = 60
_MAX_PORTFOLIOS = 10
_MAX_SECTORS = 6


def _fmt(value: object) -> str:
    """Render a number compactly, or 'n/a' for None."""
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    return str(value)


async def build_portfolio_context(user_id: int, db: AsyncSession) -> str:
    """Return a plain-text summary of the user's portfolios for the LLM.

    Returns an empty string when the user has no holdings, so the caller can
    skip context injection entirely (and the model answers generally).
    """
    from app.services.portfolio_service import get_portfolio_summary

    result = await db.execute(select(Portfolio).where(Portfolio.user_id == user_id))
    portfolios = list(result.scalars().all())
    if not portfolios:
        return ""

    lines: list[str] = []
    any_holdings = False
    listed_holdings = 0  # global budget across all portfolios
    processed = 0

    for p in portfolios:
        if processed >= _MAX_PORTFOLIOS:
            lines.append(
                f"(+{len(portfolios) - processed} more portfolios not detailed)"
            )
            break
        try:
            summary = await get_portfolio_summary(p.id, db)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("ai-context: summary failed for portfolio %s: %s", p.id, exc)
            continue

        holdings = summary.get("holdings") or []
        if not holdings:
            continue
        any_holdings = True
        processed += 1
        cur = p.currency or "INR"

        lines.append(f"## Portfolio: {p.name} ({cur})")
        lines.append(
            f"Invested {cur} {_fmt(summary.get('total_invested'))}; "
            f"current value {cur} {_fmt(summary.get('total_current_value'))}; "
            f"total P&L {_fmt(summary.get('total_pnl_percent'))}%."
        )
        # Per-portfolio cap AND a global budget so many portfolios can't add up
        # to an unbounded prompt.
        budget = max(0, min(_MAX_HOLDINGS, _MAX_TOTAL_HOLDINGS - listed_holdings))
        lines.append(f"Holdings ({len(holdings)}):")
        for h in holdings[:budget]:
            lines.append(
                f"- {h.get('stock_symbol')} "
                f"({h.get('exchange', '')}, {h.get('sector') or 'sector n/a'}): "
                f"qty {_fmt(h.get('quantity'))}, avg {_fmt(h.get('avg_price'))}, "
                f"current {_fmt(h.get('current_price'))}, "
                f"P&L {_fmt(h.get('pnl_percent'))}%, "
                f"zone {h.get('action_needed') or 'n/a'}, "
                f"RSI {_fmt(h.get('rsi'))}"
            )
        listed = min(budget, len(holdings))
        listed_holdings += listed
        if len(holdings) > listed:
            lines.append(
                f"  (+{len(holdings) - listed} more holdings not listed; "
                "totals and diversification below still cover all of them)"
            )

        await _append_diversification(lines, p.id, db)
        await _append_drift(lines, p.id, db)
        await _append_risk(lines, user_id, p.id, db)
        lines.append("")  # blank separator between portfolios

    if not any_holdings:
        return ""
    return "\n".join(lines).strip()


async def _append_diversification(lines: list[str], portfolio_id: int, db: AsyncSession) -> None:
    try:
        from app.services.concentration_service import analyze_concentration

        conc = await analyze_concentration(portfolio_id, db, fetch_external=False)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("ai-context: concentration failed: %s", exc)
        return

    lines.append(
        f"Diversification: grade {conc.get('grade')}, "
        f"effective holdings {_fmt(conc.get('effective_holdings'))} "
        f"of {conc.get('holdings_count')}, "
        f"Herfindahl index {_fmt(conc.get('herfindahl_index'))}."
    )
    sectors = conc.get("by_sector") or []
    if sectors:
        sec_txt = ", ".join(
            f"{s.get('sector', '?')} {_fmt(s.get('weight_pct'))}%"
            for s in sectors[:_MAX_SECTORS]
        )
        lines.append(f"Sector allocation: {sec_txt}.")
    warnings = conc.get("warnings") or []
    if warnings:
        lines.append("Concentration flags: " + " ".join(str(w) for w in warnings[:4]))


async def _append_drift(lines: list[str], portfolio_id: int, db: AsyncSession) -> None:
    try:
        from app.services.drift_service import check_drift

        drift = await check_drift(portfolio_id, db)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("ai-context: drift failed: %s", exc)
        return

    over = [d for d in (drift or []) if d.get("over_threshold")]
    if not over:
        return
    dtxt = ", ".join(
        f"{d.get('stock_symbol')} at {_fmt(d.get('actual_pct'))}% "
        f"vs target {_fmt(d.get('target_pct'))}% ({_fmt(d.get('drift_pct'))}pp off)"
        for d in over[:6]
    )
    lines.append(f"Allocation drift beyond threshold: {dtxt}.")


async def _append_risk(lines: list[str], user_id: int, portfolio_id: int, db: AsyncSession) -> None:
    try:
        from app.ml.risk_calculator import compute_portfolio_risk

        rm = await compute_portfolio_risk(user_id, portfolio_id, db)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("ai-context: risk failed: %s", exc)
        return

    parts: list[str] = []
    if rm.sharpe_ratio is not None:
        parts.append(f"Sharpe {_fmt(rm.sharpe_ratio)}")
    if rm.sortino_ratio is not None:
        parts.append(f"Sortino {_fmt(rm.sortino_ratio)}")
    if rm.volatility_annual is not None:
        parts.append(f"annualised volatility {_fmt(rm.volatility_annual)}")
    if rm.max_drawdown is not None:
        parts.append(f"max drawdown {_fmt(rm.max_drawdown)}")
    if rm.value_at_risk_95 is not None:
        parts.append(f"1-day VaR(95%) {_fmt(rm.value_at_risk_95)}")
    if rm.beta is not None:
        parts.append(f"beta {_fmt(rm.beta)}")
    if parts:
        lines.append("Risk metrics: " + ", ".join(parts) + ".")
