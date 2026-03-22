"""Google Sheets Export Service — generate a downloadable CSV.

Produces a well-formatted CSV that can be directly imported into Google Sheets.
Includes proper headers, date formatting (ISO 8601), and numeric precision
appropriate for financial data.
"""

from __future__ import annotations

import csv
import io
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.dividend import Dividend
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.transaction import Transaction
from app.services.export_service import _sanitize_csv_cell

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CSV generation
# ---------------------------------------------------------------------------

async def generate_portfolio_csv(
    portfolio_id: int,
    db: AsyncSession,
) -> str:
    """Generate a CSV string for a portfolio, ready for Google Sheets import.

    The CSV contains two sections separated by a blank row:
    1. **Holdings summary** — one row per holding with current valuation
    2. **Transaction history** — all BUY/SELL records

    Returns the full CSV as a string.
    """
    # Fetch portfolio with holdings eagerly loaded
    result = await db.execute(
        select(Portfolio)
        .options(selectinload(Portfolio.holdings))
        .where(Portfolio.id == portfolio_id)
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise ValueError("Portfolio not found")

    holdings = list(portfolio.holdings)

    # Fetch all transactions for these holdings
    holding_ids = [h.id for h in holdings]
    if holding_ids:
        tx_result = await db.execute(
            select(Transaction)
            .where(Transaction.holding_id.in_(holding_ids))
            .order_by(Transaction.date.asc())
        )
        transactions = list(tx_result.scalars().all())
    else:
        transactions = []

    # Fetch dividends too
    if holding_ids:
        div_result = await db.execute(
            select(Dividend)
            .where(Dividend.holding_id.in_(holding_ids))
            .order_by(Dividend.ex_date.asc())
        )
        dividends = list(div_result.scalars().all())
    else:
        dividends = []

    # Build holding lookup
    holding_map = {h.id: h for h in holdings}

    output = io.StringIO()
    writer = csv.writer(output)

    # ── Section 1: Portfolio Summary ──────────────────────────────────
    writer.writerow([f"Portfolio: {portfolio.name}"])
    writer.writerow([f"Currency: {portfolio.currency}"])
    writer.writerow([f"Exported: {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}"])
    writer.writerow([])  # blank line

    writer.writerow(
        [
            "Symbol",
            "Name",
            "Exchange",
            "Sector",
            "Quantity",
            "Avg Price",
            "Current Price",
            "Market Value",
            "Unrealised P&L",
            "P&L %",
            "RSI (14)",
            "Last Updated",
        ]
    )

    total_invested = 0.0
    total_market_value = 0.0

    for h in sorted(holdings, key=lambda x: x.stock_symbol):
        qty = float(h.cumulative_quantity)
        avg = float(h.average_price)
        cur = float(h.current_price) if h.current_price is not None else avg
        mv = qty * cur
        invested = qty * avg
        pnl = mv - invested
        pnl_pct = round((pnl / invested) * 100, 2) if invested > 0 else 0.0

        total_invested += invested
        total_market_value += mv

        last_updated_str = ""
        if h.last_price_update is not None:
            last_updated_str = h.last_price_update.strftime("%Y-%m-%d %H:%M")

        writer.writerow(
            [
                _sanitize_csv_cell(h.stock_symbol),
                _sanitize_csv_cell(h.stock_name),
                _sanitize_csv_cell(h.exchange),
                _sanitize_csv_cell(h.sector or ""),
                round(qty, 4),
                round(avg, 4),
                round(cur, 4),
                round(mv, 2),
                round(pnl, 2),
                pnl_pct,
                round(float(h.current_rsi), 2) if h.current_rsi is not None else "",
                last_updated_str,
            ]
        )

    # Totals row
    total_pnl = total_market_value - total_invested
    total_pnl_pct = (
        round((total_pnl / total_invested) * 100, 2) if total_invested > 0 else 0.0
    )
    writer.writerow([])
    writer.writerow(
        [
            "TOTAL",
            "",
            "",
            "",
            "",
            "",
            "",
            round(total_market_value, 2),
            round(total_pnl, 2),
            total_pnl_pct,
            "",
            "",
        ]
    )

    # ── Section 2: Transaction History ────────────────────────────────
    writer.writerow([])
    writer.writerow([])
    writer.writerow(["TRANSACTION HISTORY"])
    writer.writerow(
        [
            "Date",
            "Symbol",
            "Name",
            "Type",
            "Quantity",
            "Price",
            "Total Value",
            "Brokerage",
            "Source",
            "Notes",
        ]
    )

    for tx in transactions:
        holding = holding_map.get(tx.holding_id)
        total_val = float(tx.quantity) * float(tx.price)
        writer.writerow(
            [
                tx.date.isoformat(),
                _sanitize_csv_cell(holding.stock_symbol if holding else ""),
                _sanitize_csv_cell(holding.stock_name if holding else ""),
                _sanitize_csv_cell(tx.transaction_type),
                round(float(tx.quantity), 4),
                round(float(tx.price), 4),
                round(total_val, 2),
                round(float(tx.brokerage), 2),
                _sanitize_csv_cell(tx.source or ""),
                _sanitize_csv_cell(tx.notes or ""),
            ]
        )

    # ── Section 3: Dividends ─────────────────────────────────────────
    if dividends:
        writer.writerow([])
        writer.writerow([])
        writer.writerow(["DIVIDEND HISTORY"])
        writer.writerow(
            [
                "Ex-Date",
                "Payment Date",
                "Symbol",
                "Name",
                "Amount/Share",
                "Total Amount",
                "Reinvested",
            ]
        )

        for div in dividends:
            holding = holding_map.get(div.holding_id)
            writer.writerow(
                [
                    div.ex_date.isoformat(),
                    div.payment_date.isoformat() if div.payment_date else "",
                    _sanitize_csv_cell(holding.stock_symbol if holding else ""),
                    _sanitize_csv_cell(holding.stock_name if holding else ""),
                    round(float(div.amount_per_share), 4),
                    round(float(div.total_amount), 2),
                    "Yes" if div.is_reinvested else "No",
                ]
            )

    return output.getvalue()
