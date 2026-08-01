"""Regression tests for the verified review fixes.

Covers:
- Deleting a holding via the ORM must NOT destroy the user's alerts; the
  alert survives with ``holding_id`` set to NULL (cascade fix in
  ``models/holding.py``).
- Re-importing the same transaction set through ``import_to_portfolio`` does
  not double-count (application-level dedup in ``excel_service.py``).
- A legitimate zero-price row (e.g. bonus/IPO allotment) is parsed, not
  dropped as "missing" (truthiness fix in ``excel_service.parse_excel``).
- ``MutualFundUpdate`` rejects a negative NAV (schema bounds).
- The backtester counts round-trips, so an all-winning set yields a 100%
  win rate (``_compute_backtest_metrics``).
- ``compute_holding_risks`` returns a per-holding entry for every holding in a
  seeded 2-holding portfolio with price history (batched-query fix).

Run with:
    uv run pytest tests/test_review_fixes_models.py -q
"""

from __future__ import annotations

import io
from datetime import date, timedelta

import pytest
from openpyxl import Workbook
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.alert import Alert
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.transaction import Transaction
from app.models.user import User
from app.models.watchlist import WatchlistItem

# ---------------------------------------------------------------------------
# 1. Alert survives holding delete (cascade fix)
# ---------------------------------------------------------------------------

async def test_alert_survives_holding_delete(db: AsyncSession):
    """Deleting a holding must leave the user's alert intact with a NULL FK."""
    user = User(email="alert@example.com", password_hash="x", display_name="Alert")
    db.add(user)
    await db.flush()

    portfolio = Portfolio(user_id=user.id, name="P", currency="INR")
    db.add(portfolio)
    await db.flush()

    holding = Holding(
        portfolio_id=portfolio.id,
        stock_symbol="RELIANCE",
        stock_name="Reliance",
        exchange="NSE",
        currency="INR",
        cumulative_quantity=10.0,
        average_price=2500.0,
    )
    db.add(holding)
    await db.flush()

    alert = Alert(
        user_id=user.id,
        holding_id=holding.id,
        alert_type="PRICE_RANGE",
        condition={"min": 2000, "max": 3000},
    )
    db.add(alert)
    await db.flush()

    alert_id = alert.id
    holding_id = holding.id

    # Load the child collections eagerly so the ORM nullifies the alert FK
    # during flush (the test SQLite engine does not enable FK enforcement, so
    # the DB-level SET NULL never fires — the ORM path must govern).
    to_delete = (
        await db.execute(
            select(Holding)
            .options(
                selectinload(Holding.alerts),
                selectinload(Holding.transactions),
                selectinload(Holding.dividends),
            )
            .where(Holding.id == holding_id)
        )
    ).scalar_one()

    await db.delete(to_delete)
    await db.flush()

    # Holding is gone…
    assert (
        await db.execute(select(Holding).where(Holding.id == holding_id))
    ).scalar_one_or_none() is None

    # …but the alert survives with a NULL holding_id.
    surviving = (
        await db.execute(select(Alert).where(Alert.id == alert_id))
    ).scalar_one_or_none()
    assert surviving is not None
    assert surviving.holding_id is None


async def test_alert_survives_watchlist_item_delete(db: AsyncSession):
    """Deleting a watchlist item must leave the user's alert intact (NULL FK)."""
    user = User(email="wl-alert@example.com", password_hash="x", display_name="WL")
    db.add(user)
    await db.flush()

    item = WatchlistItem(
        user_id=user.id, stock_symbol="TCS", stock_name="TCS", exchange="NSE",
    )
    db.add(item)
    await db.flush()

    alert = Alert(
        user_id=user.id,
        watchlist_item_id=item.id,
        alert_type="PRICE_RANGE",
        condition={"min": 3000, "max": 4000},
    )
    db.add(alert)
    await db.flush()
    alert_id = alert.id
    item_id = item.id

    # Eager-load so the ORM nullifies the FK (test SQLite has FK enforcement off).
    to_delete = (
        await db.execute(
            select(WatchlistItem)
            .options(selectinload(WatchlistItem.alerts))
            .where(WatchlistItem.id == item_id)
        )
    ).scalar_one()
    await db.delete(to_delete)
    await db.flush()

    assert (
        await db.execute(select(WatchlistItem).where(WatchlistItem.id == item_id))
    ).scalar_one_or_none() is None

    surviving = (
        await db.execute(select(Alert).where(Alert.id == alert_id))
    ).scalar_one_or_none()
    assert surviving is not None
    assert surviving.watchlist_item_id is None


# ---------------------------------------------------------------------------
# 2. Re-import dedup
# ---------------------------------------------------------------------------

async def test_reimport_does_not_duplicate_transactions(db: AsyncSession):
    """Importing the same statement twice must not double-count transactions."""
    from app.services.excel_service import import_to_portfolio

    user = User(email="imp@example.com", password_hash="x", display_name="Imp")
    db.add(user)
    await db.flush()
    portfolio = Portfolio(user_id=user.id, name="Imp P", currency="INR")
    db.add(portfolio)
    await db.flush()

    rows = [
        {
            "stock_symbol": "RELIANCE",
            "stock_name": "Reliance",
            "exchange": "NSE",
            "transaction_type": "BUY",
            "date": date(2024, 1, 15),
            "quantity": 10.0,
            "price": 2500.0,
            "brokerage": 50.0,
        },
        {
            "stock_symbol": "RELIANCE",
            "stock_name": "Reliance",
            "exchange": "NSE",
            "transaction_type": "BUY",
            "date": date(2024, 2, 20),
            "quantity": 5.0,
            "price": 2600.0,
            "brokerage": 25.0,
        },
    ]

    first = await import_to_portfolio(rows, portfolio.id, db)
    assert first["transactions_created"] == 2

    # Second import of the exact same rows: everything is a duplicate.
    second = await import_to_portfolio(rows, portfolio.id, db)
    assert second["transactions_created"] == 0
    assert second["transactions_skipped"] == 2

    total_tx = (
        await db.execute(
            select(func.count())
            .select_from(Transaction)
            .join(Holding, Transaction.holding_id == Holding.id)
            .where(Holding.portfolio_id == portfolio.id)
        )
    ).scalar_one()
    assert total_tx == 2


# ---------------------------------------------------------------------------
# 3. Zero-price row is not dropped
# ---------------------------------------------------------------------------

def test_zero_price_row_is_parsed():
    """A price-0 allotment (bonus/IPO) is a valid row, not a "missing" one."""
    from app.services.excel_service import _TEMPLATE_COLUMNS, parse_excel

    wb = Workbook()
    ws = wb.active
    ws.append(_TEMPLATE_COLUMNS)
    row = [
        "INFY", "Infosys", "NSE", "BUY", "2024-02-01",
        100,   # quantity
        0,     # price == 0 (the previously-dropped case)
        0,     # brokerage
        None, None, None, None, None, None,  # range levels
        "IT", "bonus allotment",
    ]
    ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)

    parsed = parse_excel(buf.getvalue())
    assert len(parsed) == 1
    assert parsed[0]["price"] == 0.0
    assert parsed[0]["quantity"] == 100.0
    assert parsed[0]["stock_symbol"] == "INFY"


# ---------------------------------------------------------------------------
# 4. Schema bounds
# ---------------------------------------------------------------------------

def test_mutual_fund_update_rejects_negative_nav():
    from app.schemas.mutual_fund import MutualFundUpdate

    with pytest.raises(ValidationError):
        MutualFundUpdate(nav=-1)


# ---------------------------------------------------------------------------
# 5. Backtester round-trip win rate
# ---------------------------------------------------------------------------

def test_backtester_win_rate_all_winning_round_trips():
    from app.ml.backtester import _compute_backtest_metrics

    trades = [
        {"type": "buy", "price": 100.0, "shares": 10.0},
        {"type": "sell", "price": 110.0, "shares": 10.0, "pnl": 100.0},
        {"type": "buy", "price": 110.0, "shares": 9.0},
        {"type": "sell", "price": 120.0, "shares": 9.0, "pnl": 90.0},
    ]
    equity = [100_000.0, 100_100.0, 100_100.0, 100_190.0]

    result = _compute_backtest_metrics(trades, equity, days=252)

    # Two round-trips (two closing/sell legs), both profitable.
    assert result.total_trades == 2
    assert result.win_rate == 100.0


# ---------------------------------------------------------------------------
# 6. compute_holding_risks returns per-holding entries
# ---------------------------------------------------------------------------

async def test_compute_holding_risks_per_holding(db: AsyncSession):
    from app.ml.risk_calculator import compute_holding_risks
    from app.models.price_history import PriceHistory

    user = User(email="hrisk@example.com", password_hash="x", display_name="HR")
    db.add(user)
    await db.flush()
    portfolio = Portfolio(user_id=user.id, name="HR P", currency="INR")
    db.add(portfolio)
    await db.flush()
    db.add_all([
        Holding(portfolio_id=portfolio.id, stock_symbol="AAA", stock_name="AAA",
                exchange="NSE", currency="INR", cumulative_quantity=10.0,
                average_price=100.0, current_price=110.0),
        Holding(portfolio_id=portfolio.id, stock_symbol="BBB", stock_name="BBB",
                exchange="NSE", currency="INR", cumulative_quantity=5.0,
                average_price=200.0, current_price=190.0),
    ])
    await db.flush()

    base = date.today() - timedelta(days=60)
    for i in range(40):
        d = base + timedelta(days=i)
        ac = 100 + i * 0.5 + (i % 3)
        bc = 200 - i * 0.3 + (i % 2)
        db.add(PriceHistory(stock_symbol="AAA", exchange="NSE", date=d,
                            open=ac, high=ac + 1, low=ac - 1, close=ac, volume=1000))
        db.add(PriceHistory(stock_symbol="BBB", exchange="NSE", date=d,
                            open=bc, high=bc + 1, low=bc - 1, close=bc, volume=800))
    await db.flush()

    results = await compute_holding_risks(user.id, portfolio.id, db)

    assert len(results) == 2
    assert {r.symbol for r in results} == {"AAA", "BBB"}
    # Both holdings have stored price history, so volatility is computed.
    for r in results:
        assert r.volatility is not None
