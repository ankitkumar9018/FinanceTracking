"""Currency correctness: holdings must be denominated, weighted and valued right.

Two defects this pins:

1. ``Holding.currency`` defaulted to "INR" at every creation path with nothing
   deriving it from the exchange, so XETRA/NASDAQ positions were stored — and
   then summed, FX-converted and taxed — as rupees.
2. ``analyze_concentration`` summed raw market values across currencies. For a
   mixed India/Germany portfolio (this app's stated purpose) the rupee figures
   dwarfed the euro ones numerically, collapsing diversification to
   "1.0 effective holdings, grade F" regardless of how well spread it was.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.markets import currency_for
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.user import User


def test_currency_is_derived_from_exchange():
    assert currency_for("NSE") == "INR"
    assert currency_for("BSE") == "INR"
    assert currency_for("XETRA") == "EUR"
    assert currency_for("FRA") == "EUR"
    assert currency_for("NASDAQ") == "USD"
    assert currency_for("NYSE") == "USD"
    # case/whitespace tolerant
    assert currency_for(" xetra ") == "EUR"
    # unknown or missing exchange keeps the historical default
    assert currency_for("MADEUP") == "INR"
    assert currency_for(None) == "INR"
    # an EXPLICIT value always wins (cross-listed instruments, restores)
    assert currency_for("XETRA", "USD") == "USD"
    assert currency_for("NSE", "EUR") == "EUR"


async def _seed(db: AsyncSession) -> Portfolio:
    user = User(
        email="ccy@example.com", password_hash="x", preferred_currency="INR",
        theme_preference="dark", notification_preferences={}, is_active=True,
    )
    db.add(user)
    await db.flush()
    portfolio = Portfolio(user_id=user.id, name="Mixed", currency="INR")
    db.add(portfolio)
    await db.flush()
    # Roughly equal REAL money: 100k INR, and EUR 1,000 (~90k INR at 90/EUR).
    db.add(Holding(
        portfolio_id=portfolio.id, stock_symbol="RELIANCE", stock_name="Reliance",
        exchange="NSE", currency="INR", cumulative_quantity=100.0,
        average_price=1000.0, current_price=1000.0,
    ))
    db.add(Holding(
        portfolio_id=portfolio.id, stock_symbol="SAP", stock_name="SAP SE",
        exchange="XETRA", currency="EUR", cumulative_quantity=10.0,
        average_price=100.0, current_price=100.0,
    ))
    await db.flush()
    return portfolio


@pytest.mark.asyncio
async def test_concentration_weights_are_currency_normalised(db: AsyncSession, monkeypatch):
    """Two roughly equal positions in different currencies must weigh equally."""
    from app.services import concentration_service as cs

    async def fake_rate(frm: str, to: str, on, session):
        assert (frm, to) == ("EUR", "INR")
        return 90.0

    monkeypatch.setattr(cs, "get_exchange_rate", fake_rate, raising=False)
    monkeypatch.setattr(
        "app.services.forex_service.get_exchange_rate", fake_rate, raising=False
    )

    portfolio = await _seed(db)
    res = await cs.analyze_concentration(portfolio.id, db, fetch_external=False)

    assert res["currency"] == "INR"
    assert res["unconverted_symbols"] == []
    # INR 100,000 vs EUR 1,000 -> INR 90,000. Neither may dominate.
    weights = {h["stock_symbol"]: h["weight_pct"] for h in res["top_holdings"]}
    assert 45 < weights["RELIANCE"] < 60, weights
    assert 40 < weights["SAP"] < 55, weights
    # Pre-fix this was ~1.0 ("only 1 effective holding") because EUR 1,000 was
    # summed as 1,000 against RELIANCE's 100,000.
    assert res["effective_holdings"] > 1.9, res["effective_holdings"]


@pytest.mark.asyncio
async def test_unconvertible_holding_is_reported_not_silently_mixed(
    db: AsyncSession, monkeypatch
):
    """With no FX rate the holding is excluded AND named — never counted raw."""
    from app.services import concentration_service as cs

    async def no_rate(frm: str, to: str, on, session):
        raise RuntimeError("no rate")

    monkeypatch.setattr(cs, "get_exchange_rate", no_rate, raising=False)
    monkeypatch.setattr(
        "app.services.forex_service.get_exchange_rate", no_rate, raising=False
    )

    portfolio = await _seed(db)
    res = await cs.analyze_concentration(portfolio.id, db, fetch_external=False)

    assert res["unconverted_symbols"] == ["SAP"]
    # The INR holding still carries the whole (declared) total.
    assert res["total_value"] == pytest.approx(100_000.0)


@pytest.mark.asyncio
async def test_display_currency_fields_survive_the_response_model(
    db: AsyncSession, monkeypatch
):
    """?display_currency= must actually reach the client.

    The service computed per-row `invested_display` / `current_value_display`
    and portfolio-level `display_currency` / `total_*_display`, but NONE were
    declared on the response models, so FastAPI stripped every one of them.
    The dashboard's "Total Value (EUR)" card read undefined, and anything
    aggregating across holdings (heatmap tiles, weights) had only native
    values and silently summed INR with EUR.
    """
    from app.services import portfolio_service as ps

    async def fake_rate(frm: str, to: str, on, session):
        return {("EUR", "INR"): 90.0, ("INR", "EUR"): 1 / 90.0}.get((frm, to), 1.0)

    monkeypatch.setattr(
        "app.services.forex_service.get_exchange_rate", fake_rate, raising=False
    )

    portfolio = await _seed(db)
    summary = await ps.get_portfolio_summary(portfolio.id, db)
    # NOTE: even a base==target request converts here, because the portfolio
    # holds EUR as well as INR — the no-op path applies only when EVERY source
    # currency already equals the target.
    converted = await ps._add_display_currency(summary, "INR", "INR", db)
    assert converted["display_currency"] == "INR"
    assert converted["total_current_value_display"] > 0

    summary2 = await ps.get_portfolio_summary(portfolio.id, db)
    converted2 = await ps._add_display_currency(summary2, "INR", "EUR", db)
    assert converted2["display_currency"] == "EUR"

    # The response model must not strip any of it.
    from app.schemas.portfolio import PortfolioSummaryResponse

    validated = PortfolioSummaryResponse.model_validate(converted2)
    assert validated.display_currency == "EUR"
    assert validated.total_current_value_display is not None
    assert any(r.current_value_display is not None for r in validated.holdings)
