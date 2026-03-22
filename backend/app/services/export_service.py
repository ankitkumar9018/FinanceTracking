"""Export services: CSV and PDF report generation."""

from __future__ import annotations

import csv
import html as html_mod
import io
import logging
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.transaction import Transaction
from app.models.tax_record import TaxRecord

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sanitize_csv_cell(value: object) -> object:
    """Prevent CSV formula injection by prefixing dangerous characters.

    Spreadsheet applications (Excel, Google Sheets) interpret cells starting
    with ``=``, ``+``, ``-``, ``@``, ``\\t``, or ``\\r`` as formulas or
    field separators.  Prefixing with a single quote neutralises this.
    """
    if isinstance(value, str) and value and value[0] in "=+-@\t\r":
        return f"'{value}"
    return value


# ---------------------------------------------------------------------------
# CSV Export
# ---------------------------------------------------------------------------


async def export_holdings_csv(portfolio_id: int, db: AsyncSession) -> str:
    """Export portfolio holdings as CSV string."""
    result = await db.execute(
        select(Portfolio)
        .options(selectinload(Portfolio.holdings))
        .where(Portfolio.id == portfolio_id)
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise ValueError(f"Portfolio {portfolio_id} not found")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Stock Symbol", "Stock Name", "Exchange", "Quantity", "Avg Price",
        "Current Price", "P&L %", "Action Needed", "RSI", "Sector",
    ])

    for h in portfolio.holdings:
        qty = float(h.cumulative_quantity)
        avg = float(h.average_price)
        current = float(h.current_price) if h.current_price else None
        pnl = None
        if current and avg > 0:
            pnl = round(((current - avg) / avg) * 100, 2)
        writer.writerow([
            _sanitize_csv_cell(h.stock_symbol),
            _sanitize_csv_cell(h.stock_name),
            _sanitize_csv_cell(h.exchange),
            qty, avg, current, pnl,
            _sanitize_csv_cell(h.action_needed),
            h.current_rsi,
            _sanitize_csv_cell(h.sector),
        ])

    return output.getvalue()


async def export_transactions_csv(portfolio_id: int, db: AsyncSession) -> str:
    """Export all transactions for a portfolio as CSV."""
    result = await db.execute(
        select(Portfolio)
        .options(selectinload(Portfolio.holdings).selectinload(Holding.transactions))
        .where(Portfolio.id == portfolio_id)
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise ValueError(f"Portfolio {portfolio_id} not found")

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Stock Symbol", "Exchange", "Type", "Date", "Quantity",
        "Price", "Brokerage", "Source", "Notes",
    ])

    for h in portfolio.holdings:
        for tx in h.transactions:
            writer.writerow([
                _sanitize_csv_cell(h.stock_symbol),
                _sanitize_csv_cell(h.exchange),
                _sanitize_csv_cell(tx.transaction_type),
                tx.date.isoformat(),
                float(tx.quantity), float(tx.price), float(tx.brokerage),
                _sanitize_csv_cell(tx.source),
                _sanitize_csv_cell(tx.notes),
            ])

    return output.getvalue()


# ---------------------------------------------------------------------------
# PDF Report (simple HTML-based)
# ---------------------------------------------------------------------------


async def generate_portfolio_report_html(
    portfolio_id: int,
    user_name: str,
    db: AsyncSession,
) -> str:
    """Generate a portfolio summary report as styled HTML (can be printed to PDF)."""
    result = await db.execute(
        select(Portfolio)
        .options(selectinload(Portfolio.holdings))
        .where(Portfolio.id == portfolio_id)
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise ValueError(f"Portfolio {portfolio_id} not found")

    total_invested = 0.0
    total_current = 0.0
    holdings_data = []

    for h in portfolio.holdings:
        qty = float(h.cumulative_quantity)
        avg = float(h.average_price)
        invested = qty * avg
        current_price = float(h.current_price) if h.current_price else 0
        current_value = qty * current_price
        pnl = current_value - invested
        pnl_pct = (pnl / invested * 100) if invested > 0 else 0

        total_invested += invested
        total_current += current_value

        holdings_data.append({
            "symbol": h.stock_symbol,
            "name": h.stock_name,
            "exchange": h.exchange,
            "qty": qty,
            "avg": avg,
            "current": current_price,
            "invested": invested,
            "value": current_value,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "action": h.action_needed,
            "rsi": h.current_rsi,
        })

    total_pnl = total_current - total_invested
    total_pnl_pct = (total_pnl / total_invested * 100) if total_invested > 0 else 0

    now = datetime.now().strftime("%B %d, %Y")

    # Build HTML report (escape user-controlled strings to prevent XSS)
    _esc = html_mod.escape
    rows_html = ""
    for h in holdings_data:
        pnl_color = "#16a34a" if h["pnl"] >= 0 else "#dc2626"
        rows_html += f"""
        <tr>
            <td>{_esc(str(h['symbol']))}</td>
            <td>{_esc(str(h['name']))}</td>
            <td style="text-align:right">{h['qty']:.2f}</td>
            <td style="text-align:right">{h['avg']:.2f}</td>
            <td style="text-align:right">{h['current']:.2f}</td>
            <td style="text-align:right">{h['invested']:,.2f}</td>
            <td style="text-align:right">{h['value']:,.2f}</td>
            <td style="text-align:right;color:{pnl_color}">{h['pnl']:+,.2f} ({h['pnl_pct']:+.1f}%)</td>
            <td style="text-align:center">{_esc(str(h['action']))}</td>
            <td style="text-align:right">{h['rsi']:.1f if h['rsi'] else '--'}</td>
        </tr>"""

    total_pnl_color = "#16a34a" if total_pnl >= 0 else "#dc2626"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Portfolio Report - {_esc(portfolio.name)}</title>
<style>
    body {{ font-family: -apple-system, 'Segoe UI', sans-serif; margin: 40px; color: #1a1a1a; }}
    h1 {{ color: #1e3a5f; margin-bottom: 4px; }}
    .subtitle {{ color: #666; margin-bottom: 24px; }}
    .summary {{ display: flex; gap: 24px; margin-bottom: 32px; }}
    .summary-card {{ background: #f8f9fa; border-radius: 8px; padding: 16px 24px; flex: 1; }}
    .summary-card .label {{ font-size: 12px; color: #666; text-transform: uppercase; }}
    .summary-card .value {{ font-size: 24px; font-weight: 700; margin-top: 4px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th {{ background: #1e3a5f; color: white; padding: 10px 8px; text-align: left; }}
    td {{ padding: 8px; border-bottom: 1px solid #e5e7eb; }}
    tr:hover {{ background: #f8f9fa; }}
    .footer {{ margin-top: 32px; font-size: 11px; color: #999; text-align: center; }}
</style></head><body>
<h1>{_esc(portfolio.name)} — Portfolio Report</h1>
<p class="subtitle">Generated on {now} for {_esc(user_name)} | Currency: {_esc(portfolio.currency)}</p>
<div class="summary">
    <div class="summary-card">
        <div class="label">Total Invested</div>
        <div class="value">{total_invested:,.2f}</div>
    </div>
    <div class="summary-card">
        <div class="label">Current Value</div>
        <div class="value">{total_current:,.2f}</div>
    </div>
    <div class="summary-card">
        <div class="label">Total P&L</div>
        <div class="value" style="color:{total_pnl_color}">{total_pnl:+,.2f} ({total_pnl_pct:+.1f}%)</div>
    </div>
    <div class="summary-card">
        <div class="label">Holdings</div>
        <div class="value">{len(holdings_data)}</div>
    </div>
</div>
<table>
<thead><tr>
    <th>Symbol</th><th>Name</th><th style="text-align:right">Qty</th>
    <th style="text-align:right">Avg Price</th><th style="text-align:right">Current</th>
    <th style="text-align:right">Invested</th><th style="text-align:right">Value</th>
    <th style="text-align:right">P&L</th><th style="text-align:center">Action</th>
    <th style="text-align:right">RSI</th>
</tr></thead>
<tbody>{rows_html}</tbody>
</table>
<div class="footer">FinanceTracker — Personal Investment Portfolio Tracking | Generated automatically</div>
</body></html>"""

    return html


# ---------------------------------------------------------------------------
# PDF Export (requires xhtml2pdf)
# ---------------------------------------------------------------------------


async def generate_portfolio_pdf(
    portfolio_id: int, user_name: str, db: AsyncSession
) -> bytes:
    """Generate a PDF report from the HTML portfolio report.

    Requires the ``xhtml2pdf`` package. Raises ImportError if not installed.
    """
    from xhtml2pdf import pisa  # noqa: F811

    html_content = await generate_portfolio_report_html(portfolio_id, user_name, db)
    output = io.BytesIO()
    pisa.CreatePDF(html_content, dest=output)
    return output.getvalue()
