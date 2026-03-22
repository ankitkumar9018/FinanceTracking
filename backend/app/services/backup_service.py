"""Backup service — JSON full export/import and SQLite database backup."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.asset import Asset
from app.models.dividend import Dividend
from app.models.fno_position import FnoPosition
from app.models.goal import Goal
from app.models.holding import Holding
from app.models.mutual_fund import MutualFund
from app.models.portfolio import Portfolio
from app.models.tax_record import TaxRecord
from app.models.transaction import Transaction
from app.services.portfolio_service import calculate_cumulative_holding

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _ser(val: object) -> object:
    """Serialize a value to JSON-safe type."""
    if val is None:
        return None
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    if isinstance(val, dict):
        return val
    return val


# ---------------------------------------------------------------------------
# JSON Export — Full portfolio backup
# ---------------------------------------------------------------------------

async def export_portfolio_json(
    portfolio_id: int,
    user_id: int,
    db: AsyncSession,
) -> dict:
    """Export a full portfolio backup as a JSON-serializable dict.

    Includes: portfolio info, holdings (with transactions + dividends),
    mutual funds, F&O positions, goals, assets, tax records.
    """
    # Load portfolio with holdings → transactions + dividends
    result = await db.execute(
        select(Portfolio)
        .options(
            selectinload(Portfolio.holdings)
            .selectinload(Holding.transactions),
            selectinload(Portfolio.holdings)
            .selectinload(Holding.dividends),
        )
        .where(Portfolio.id == portfolio_id)
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise ValueError(f"Portfolio {portfolio_id} not found")

    # Load related entities
    mf_result = await db.execute(
        select(MutualFund).where(MutualFund.portfolio_id == portfolio_id)
    )
    mutual_funds = mf_result.scalars().all()

    fno_result = await db.execute(
        select(FnoPosition).where(FnoPosition.portfolio_id == portfolio_id)
    )
    fno_positions = fno_result.scalars().all()

    goals_result = await db.execute(
        select(Goal).where(Goal.user_id == user_id)
    )
    goals = goals_result.scalars().all()

    assets_result = await db.execute(
        select(Asset).where(Asset.user_id == user_id)
    )
    assets = assets_result.scalars().all()

    tax_result = await db.execute(
        select(TaxRecord).where(TaxRecord.user_id == user_id)
    )
    tax_records = tax_result.scalars().all()

    # Build JSON structure
    return {
        "format": "financetracker_backup",
        "version": "1.0",
        "exported_at": datetime.now().isoformat(),
        "portfolio": {
            "name": portfolio.name,
            "currency": portfolio.currency,
            "description": portfolio.description,
            "holdings": [
                {
                    "stock_symbol": h.stock_symbol,
                    "stock_name": h.stock_name,
                    "exchange": h.exchange,
                    "currency": h.currency,
                    "sector": h.sector,
                    "notes": h.notes,
                    "lower_mid_range_1": _ser(h.lower_mid_range_1),
                    "lower_mid_range_2": _ser(h.lower_mid_range_2),
                    "upper_mid_range_1": _ser(h.upper_mid_range_1),
                    "upper_mid_range_2": _ser(h.upper_mid_range_2),
                    "base_level": _ser(h.base_level),
                    "top_level": _ser(h.top_level),
                    "transactions": [
                        {
                            "transaction_type": tx.transaction_type,
                            "date": _ser(tx.date),
                            "quantity": _ser(tx.quantity),
                            "price": _ser(tx.price),
                            "brokerage": _ser(tx.brokerage),
                            "notes": tx.notes,
                            "source": tx.source,
                        }
                        for tx in h.transactions
                    ],
                    "dividends": [
                        {
                            "ex_date": _ser(d.ex_date),
                            "payment_date": _ser(d.payment_date),
                            "amount_per_share": _ser(d.amount_per_share),
                            "total_amount": _ser(d.total_amount),
                            "is_reinvested": d.is_reinvested,
                            "reinvest_price": _ser(d.reinvest_price),
                            "reinvest_shares": _ser(d.reinvest_shares),
                        }
                        for d in h.dividends
                    ],
                }
                for h in portfolio.holdings
            ],
            "mutual_funds": [
                {
                    "scheme_code": mf.scheme_code,
                    "scheme_name": mf.scheme_name,
                    "folio_number": mf.folio_number,
                    "units": _ser(mf.units),
                    "nav": _ser(mf.nav),
                    "invested_amount": _ser(mf.invested_amount),
                }
                for mf in mutual_funds
            ],
            "fno_positions": [
                {
                    "symbol": fno.symbol,
                    "exchange": fno.exchange,
                    "instrument_type": fno.instrument_type,
                    "strike_price": _ser(fno.strike_price),
                    "expiry_date": _ser(fno.expiry_date),
                    "lot_size": fno.lot_size,
                    "quantity": fno.quantity,
                    "entry_price": _ser(fno.entry_price),
                    "exit_price": _ser(fno.exit_price),
                    "side": fno.side,
                    "status": fno.status,
                    "notes": fno.notes,
                }
                for fno in fno_positions
            ],
        },
        "goals": [
            {
                "name": g.name,
                "target_amount": _ser(g.target_amount),
                "current_amount": _ser(g.current_amount),
                "target_date": _ser(g.target_date),
                "category": g.category,
                "monthly_sip_needed": _ser(g.monthly_sip_needed),
                "is_achieved": g.is_achieved,
            }
            for g in goals
        ],
        "assets": [
            {
                "asset_type": a.asset_type,
                "name": a.name,
                "symbol": a.symbol,
                "quantity": _ser(a.quantity),
                "purchase_price": _ser(a.purchase_price),
                "current_value": _ser(a.current_value),
                "currency": a.currency,
                "interest_rate": a.interest_rate,
                "maturity_date": _ser(a.maturity_date),
                "notes": a.notes,
            }
            for a in assets
        ],
        "tax_records": [
            {
                "financial_year": tr.financial_year,
                "tax_jurisdiction": tr.tax_jurisdiction,
                "gain_type": tr.gain_type,
                "purchase_date": _ser(tr.purchase_date),
                "sale_date": _ser(tr.sale_date),
                "purchase_price": _ser(tr.purchase_price),
                "sale_price": _ser(tr.sale_price),
                "gain_amount": _ser(tr.gain_amount),
                "tax_amount": _ser(tr.tax_amount),
                "holding_period_days": tr.holding_period_days,
                "currency": tr.currency,
            }
            for tr in tax_records
        ],
    }


# ---------------------------------------------------------------------------
# JSON Import — Restore portfolio from backup
# ---------------------------------------------------------------------------

def _parse_date_str(s: str | None) -> date | None:
    """Parse ISO date string to date object."""
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


async def import_portfolio_json(
    data: dict,
    user_id: int,
    db: AsyncSession,
) -> dict:
    """Import a full portfolio from a JSON backup.

    Creates a new portfolio with " (Imported)" suffix.
    Returns a summary dict with counts.
    """
    if data.get("format") != "financetracker_backup":
        raise ValueError("Invalid backup format. Expected 'financetracker_backup'.")

    version = data.get("version", "1.0")
    if version not in ("1.0",):
        raise ValueError(f"Unsupported backup version: {version}")

    portfolio_data = data.get("portfolio", {})
    counts = {
        "holdings": 0, "transactions": 0, "dividends": 0,
        "mutual_funds": 0, "fno_positions": 0,
        "goals": 0, "assets": 0, "tax_records": 0,
    }

    # Create portfolio
    portfolio = Portfolio(
        user_id=user_id,
        name=f"{portfolio_data.get('name', 'Portfolio')} (Imported)",
        currency=portfolio_data.get("currency", "INR"),
        description=portfolio_data.get("description"),
    )
    db.add(portfolio)
    await db.flush()
    await db.refresh(portfolio)

    # Import holdings with transactions and dividends
    for h_data in portfolio_data.get("holdings", []):
        holding = Holding(
            portfolio_id=portfolio.id,
            stock_symbol=h_data["stock_symbol"],
            stock_name=h_data["stock_name"],
            exchange=h_data["exchange"],
            currency=h_data.get("currency", "INR"),
            cumulative_quantity=0.0,
            average_price=0.0,
            sector=h_data.get("sector"),
            notes=h_data.get("notes"),
            lower_mid_range_1=h_data.get("lower_mid_range_1"),
            lower_mid_range_2=h_data.get("lower_mid_range_2"),
            upper_mid_range_1=h_data.get("upper_mid_range_1"),
            upper_mid_range_2=h_data.get("upper_mid_range_2"),
            base_level=h_data.get("base_level"),
            top_level=h_data.get("top_level"),
        )
        db.add(holding)
        await db.flush()
        await db.refresh(holding)
        counts["holdings"] += 1

        # Transactions
        for tx_data in h_data.get("transactions", []):
            tx = Transaction(
                holding_id=holding.id,
                transaction_type=tx_data["transaction_type"],
                date=_parse_date_str(tx_data["date"]) or date.today(),
                quantity=float(tx_data["quantity"]),
                price=float(tx_data["price"]),
                brokerage=float(tx_data.get("brokerage", 0)),
                notes=tx_data.get("notes"),
                source="JSON_IMPORT",
            )
            db.add(tx)
            counts["transactions"] += 1

        # Dividends
        for d_data in h_data.get("dividends", []):
            div = Dividend(
                holding_id=holding.id,
                ex_date=_parse_date_str(d_data["ex_date"]) or date.today(),
                payment_date=_parse_date_str(d_data.get("payment_date")),
                amount_per_share=float(d_data["amount_per_share"]),
                total_amount=float(d_data["total_amount"]),
                is_reinvested=d_data.get("is_reinvested", False),
                reinvest_price=d_data.get("reinvest_price"),
                reinvest_shares=d_data.get("reinvest_shares"),
            )
            db.add(div)
            counts["dividends"] += 1

        await db.flush()
        # Recalculate cumulative holding
        await calculate_cumulative_holding(holding.id, db)

    # Mutual funds
    for mf_data in portfolio_data.get("mutual_funds", []):
        mf = MutualFund(
            portfolio_id=portfolio.id,
            scheme_code=mf_data["scheme_code"],
            scheme_name=mf_data["scheme_name"],
            folio_number=mf_data.get("folio_number"),
            units=float(mf_data["units"]),
            nav=float(mf_data["nav"]),
            invested_amount=float(mf_data["invested_amount"]),
        )
        db.add(mf)
        counts["mutual_funds"] += 1

    # F&O positions
    for fno_data in portfolio_data.get("fno_positions", []):
        fno = FnoPosition(
            portfolio_id=portfolio.id,
            symbol=fno_data["symbol"],
            exchange=fno_data.get("exchange", "NSE"),
            instrument_type=fno_data["instrument_type"],
            strike_price=fno_data.get("strike_price"),
            expiry_date=_parse_date_str(fno_data["expiry_date"]) or date.today(),
            lot_size=int(fno_data.get("lot_size", 1)),
            quantity=int(fno_data.get("quantity", 1)),
            entry_price=float(fno_data["entry_price"]),
            exit_price=fno_data.get("exit_price"),
            side=fno_data.get("side", "BUY"),
            status=fno_data.get("status", "OPEN"),
            notes=fno_data.get("notes"),
        )
        db.add(fno)
        counts["fno_positions"] += 1

    # Goals (user-level)
    for g_data in data.get("goals", []):
        goal = Goal(
            user_id=user_id,
            name=g_data["name"],
            target_amount=float(g_data["target_amount"]),
            current_amount=float(g_data.get("current_amount", 0)),
            target_date=_parse_date_str(g_data.get("target_date")),
            category=g_data.get("category", "CUSTOM"),
            linked_portfolio_id=portfolio.id,
            monthly_sip_needed=g_data.get("monthly_sip_needed"),
            is_achieved=g_data.get("is_achieved", False),
        )
        db.add(goal)
        counts["goals"] += 1

    # Assets (user-level)
    for a_data in data.get("assets", []):
        asset = Asset(
            user_id=user_id,
            asset_type=a_data["asset_type"],
            name=a_data["name"],
            symbol=a_data.get("symbol"),
            quantity=float(a_data.get("quantity", 0)),
            purchase_price=float(a_data.get("purchase_price", 0)),
            current_value=float(a_data.get("current_value", 0)),
            currency=a_data.get("currency", "INR"),
            interest_rate=a_data.get("interest_rate"),
            maturity_date=_parse_date_str(a_data.get("maturity_date")),
            notes=a_data.get("notes"),
        )
        db.add(asset)
        counts["assets"] += 1

    # Tax records (user-level)
    for tr_data in data.get("tax_records", []):
        tr = TaxRecord(
            user_id=user_id,
            financial_year=tr_data["financial_year"],
            tax_jurisdiction=tr_data["tax_jurisdiction"],
            gain_type=tr_data["gain_type"],
            purchase_date=_parse_date_str(tr_data["purchase_date"]) or date.today(),
            sale_date=_parse_date_str(tr_data.get("sale_date")),
            purchase_price=float(tr_data["purchase_price"]),
            sale_price=tr_data.get("sale_price"),
            gain_amount=tr_data.get("gain_amount"),
            tax_amount=tr_data.get("tax_amount"),
            holding_period_days=tr_data.get("holding_period_days"),
            currency=tr_data.get("currency", "INR"),
        )
        db.add(tr)
        counts["tax_records"] += 1

    await db.flush()

    return {
        "portfolio_id": portfolio.id,
        "portfolio_name": portfolio.name,
        **counts,
    }


# ---------------------------------------------------------------------------
# SQLite Database Backup
# ---------------------------------------------------------------------------

async def export_sqlite_backup() -> bytes | None:
    """Export the SQLite database file as raw bytes.

    Returns None if the app is not using SQLite.
    """
    from app.config import settings

    if not settings.is_sqlite:
        return None

    db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")

    # Checkpoint WAL to ensure consistency
    import sqlite3
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.close()
    except Exception:
        logger.debug("WAL checkpoint failed (may not be in WAL mode)", exc_info=True)

    try:
        with open(db_path, "rb") as f:
            return f.read()
    except FileNotFoundError:
        logger.warning("SQLite database file not found at %s", db_path)
        return None
