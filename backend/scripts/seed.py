"""Seed script — populate database with sample data for development.

Usage:
    cd backend && uv run python scripts/seed.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Ensure app is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Monkey-patch for passlib + bcrypt 5.0 compatibility
import bcrypt
if not hasattr(bcrypt, "__about__"):
    class _About:
        __version__ = getattr(bcrypt, "__version__", "5.0.0")
    bcrypt.__about__ = _About()

from sqlalchemy import select
from app.database import engine, async_session_factory
from app.models import (
    User, Portfolio, Holding, Transaction, WatchlistItem, Goal, Alert,
    Asset, FnoPosition, Dividend, MutualFund, TaxRecord, BrokerConnection,
    ChatSession,
)
from app.utils.security import hash_password
from datetime import datetime, date, timezone


SAMPLE_HOLDINGS = [
    {"stock_symbol": "RELIANCE", "stock_name": "Reliance Industries Ltd", "exchange": "NSE", "sector": "Energy",
     "cumulative_quantity": 50, "average_price": 2450.00, "current_price": 2680.50, "current_rsi": 55.3,
     "lower_mid_range_1": 2400, "lower_mid_range_2": 2200, "upper_mid_range_1": 2800, "upper_mid_range_2": 3000,
     "base_level": 2000, "top_level": 3200},
    {"stock_symbol": "TCS", "stock_name": "Tata Consultancy Services", "exchange": "NSE", "sector": "IT",
     "cumulative_quantity": 30, "average_price": 3600.00, "current_price": 3850.75, "current_rsi": 62.1,
     "lower_mid_range_1": 3500, "lower_mid_range_2": 3200, "upper_mid_range_1": 4000, "upper_mid_range_2": 4200,
     "base_level": 3000, "top_level": 4500},
    {"stock_symbol": "INFY", "stock_name": "Infosys Ltd", "exchange": "NSE", "sector": "IT",
     "cumulative_quantity": 100, "average_price": 1480.00, "current_price": 1520.30, "current_rsi": 48.7,
     "lower_mid_range_1": 1400, "lower_mid_range_2": 1300, "upper_mid_range_1": 1600, "upper_mid_range_2": 1700,
     "base_level": 1200, "top_level": 1800},
    {"stock_symbol": "HDFCBANK", "stock_name": "HDFC Bank Ltd", "exchange": "NSE", "sector": "Banking",
     "cumulative_quantity": 75, "average_price": 1620.00, "current_price": 1690.25, "current_rsi": 58.4,
     "lower_mid_range_1": 1550, "lower_mid_range_2": 1450, "upper_mid_range_1": 1750, "upper_mid_range_2": 1850,
     "base_level": 1350, "top_level": 1950},
    {"stock_symbol": "SAP.DE", "stock_name": "SAP SE", "exchange": "XETRA", "sector": "IT", "currency": "EUR",
     "cumulative_quantity": 20, "average_price": 175.00, "current_price": 192.40, "current_rsi": 67.2,
     "lower_mid_range_1": 170, "lower_mid_range_2": 155, "upper_mid_range_1": 200, "upper_mid_range_2": 215,
     "base_level": 140, "top_level": 230},
    {"stock_symbol": "SIE.DE", "stock_name": "Siemens AG", "exchange": "XETRA", "sector": "Industrial", "currency": "EUR",
     "cumulative_quantity": 15, "average_price": 165.00, "current_price": 178.90, "current_rsi": 52.8,
     "lower_mid_range_1": 160, "lower_mid_range_2": 145, "upper_mid_range_1": 185, "upper_mid_range_2": 200,
     "base_level": 130, "top_level": 215},
    {"stock_symbol": "ICICIBANK", "stock_name": "ICICI Bank Ltd", "exchange": "NSE", "sector": "Banking",
     "cumulative_quantity": 120, "average_price": 980.00, "current_price": 1050.60, "current_rsi": 44.1,
     "lower_mid_range_1": 950, "lower_mid_range_2": 880, "upper_mid_range_1": 1100, "upper_mid_range_2": 1180,
     "base_level": 800, "top_level": 1250},
    {"stock_symbol": "WIPRO", "stock_name": "Wipro Ltd", "exchange": "NSE", "sector": "IT",
     "cumulative_quantity": 200, "average_price": 420.00, "current_price": 445.80, "current_rsi": 39.5,
     "lower_mid_range_1": 400, "lower_mid_range_2": 370, "upper_mid_range_1": 470, "upper_mid_range_2": 500,
     "base_level": 340, "top_level": 530},
]


async def seed():
    """Create sample user, portfolio, holdings, transactions, and all related data."""
    async with async_session_factory() as db:
        # Check if already seeded
        result = await db.execute(select(User).where(User.email == "demo@financetracker.dev"))
        if result.scalar_one_or_none():
            print("Database already seeded (demo user exists). Skipping.")
            return

        # ── User ──
        user = User(
            email="demo@financetracker.dev",
            password_hash=hash_password("demo1234"),
            display_name="Demo User",
            preferred_currency="INR",
            theme_preference="dark",
            is_active=True,
        )
        db.add(user)
        await db.flush()

        # ── Portfolio ──
        portfolio = Portfolio(
            user_id=user.id,
            name="My Portfolio",
            description="Demo investment portfolio with Indian & German stocks",
            currency="INR",
            is_default=True,
        )
        db.add(portfolio)
        await db.flush()

        # ── Holdings + Transactions ──
        holding_ids: dict[str, int] = {}
        for h_data in SAMPLE_HOLDINGS:
            currency = h_data.pop("currency", "INR")
            holding = Holding(
                portfolio_id=portfolio.id,
                currency=currency,
                action_needed="N",
                **h_data,
            )
            db.add(holding)
            await db.flush()
            holding_ids[holding.stock_symbol] = holding.id

            # Buy transaction
            txn = Transaction(
                holding_id=holding.id,
                transaction_type="BUY",
                date=date(2024, 6, 15),
                quantity=holding.cumulative_quantity,
                price=holding.average_price,
                brokerage=0,
                notes="Initial purchase",
                source="MANUAL",
            )
            db.add(txn)

        # Additional SELL transaction for one holding (for tax record testing)
        sell_txn = Transaction(
            holding_id=holding_ids["WIPRO"],
            transaction_type="SELL",
            date=date(2025, 1, 10),
            quantity=50,
            price=460.0,
            brokerage=20.0,
            notes="Partial profit booking",
            source="MANUAL",
        )
        db.add(sell_txn)

        # SIP-like recurring buys for INFY (for recurring detection testing)
        for month in range(1, 7):
            sip_txn = Transaction(
                holding_id=holding_ids["INFY"],
                transaction_type="BUY",
                date=date(2025, month, 5),
                quantity=5,
                price=1480.0 + month * 10,
                brokerage=0,
                notes="Monthly SIP",
                source="MANUAL",
            )
            db.add(sip_txn)

        # ── Watchlist ──
        watchlist = WatchlistItem(
            user_id=user.id,
            stock_symbol="TATAMOTORS",
            stock_name="Tata Motors Ltd",
            exchange="NSE",
            target_buy_price=750.0,
            notes="Wait for RSI below 30",
        )
        db.add(watchlist)

        watchlist2 = WatchlistItem(
            user_id=user.id,
            stock_symbol="BAJFINANCE",
            stock_name="Bajaj Finance Ltd",
            exchange="NSE",
            target_buy_price=6500.0,
            notes="Accumulate on dips",
        )
        db.add(watchlist2)

        # ── Goals ──
        goal = Goal(
            user_id=user.id,
            name="Retirement Fund",
            target_amount=10000000,
            current_amount=2500000,
            target_date=date(2045, 1, 1),
            category="RETIREMENT",
            linked_portfolio_id=portfolio.id,
            monthly_sip_needed=25000,
        )
        db.add(goal)

        goal2 = Goal(
            user_id=user.id,
            name="House Down Payment",
            target_amount=3000000,
            current_amount=1200000,
            target_date=date(2028, 6, 1),
            category="HOUSE",
            monthly_sip_needed=45000,
        )
        db.add(goal2)

        # ── Assets (Net Worth) ──
        assets_data = [
            Asset(user_id=user.id, asset_type="CRYPTO", name="Bitcoin", symbol="BTC-USD",
                  quantity=0.5, purchase_price=45000.0, current_value=52000.0, currency="USD"),
            Asset(user_id=user.id, asset_type="GOLD", name="Sovereign Gold Bond 2024",
                  quantity=10, purchase_price=5800.0, current_value=6200.0, currency="INR"),
            Asset(user_id=user.id, asset_type="FIXED_DEPOSIT", name="SBI FD 7.1%",
                  quantity=1, purchase_price=500000.0, current_value=535500.0, currency="INR",
                  interest_rate=7.1, maturity_date=date(2027, 3, 15)),
        ]
        for a in assets_data:
            db.add(a)

        # ── F&O Position ──
        fno = FnoPosition(
            portfolio_id=portfolio.id, symbol="NIFTY", exchange="NSE",
            instrument_type="CE", strike_price=22000.0,
            expiry_date=date(2026, 3, 27), lot_size=50, quantity=2,
            entry_price=350.0, current_price=420.0, side="BUY", status="OPEN",
            notes="Monthly expiry call option",
        )
        db.add(fno)

        # ── Alerts ──
        alert_price = Alert(
            user_id=user.id,
            holding_id=holding_ids["RELIANCE"],
            alert_type="PRICE_RANGE",
            condition={"operator": "below", "value": 2300, "field": "current_price"},
            channels=["in_app", "email"],
        )
        db.add(alert_price)

        alert_rsi = Alert(
            user_id=user.id,
            holding_id=holding_ids["TCS"],
            alert_type="RSI",
            condition={"operator": "above", "value": 70, "field": "rsi"},
            channels=["in_app"],
        )
        db.add(alert_rsi)

        alert_watchlist = Alert(
            user_id=user.id,
            watchlist_item_id=watchlist.id,
            alert_type="PRICE_RANGE",
            condition={"operator": "below", "value": 750, "field": "current_price"},
            channels=["in_app", "telegram"],
        )
        db.add(alert_watchlist)

        # ── Dividends ──
        div_reliance = Dividend(
            holding_id=holding_ids["RELIANCE"],
            ex_date=date(2025, 8, 15),
            amount_per_share=10.0,
            total_amount=500.0,
            payment_date=date(2025, 9, 1),
        )
        db.add(div_reliance)

        div_tcs = Dividend(
            holding_id=holding_ids["TCS"],
            ex_date=date(2025, 7, 1),
            amount_per_share=28.0,
            total_amount=840.0,
            payment_date=date(2025, 7, 20),
        )
        db.add(div_tcs)

        div_infy = Dividend(
            holding_id=holding_ids["INFY"],
            ex_date=date(2025, 6, 1),
            amount_per_share=18.5,
            total_amount=1850.0,
            payment_date=date(2025, 6, 15),
            is_reinvested=True,
            reinvest_price=1520.0,
            reinvest_shares=1.2,
        )
        db.add(div_infy)

        # ── Mutual Funds ──
        mf1 = MutualFund(
            portfolio_id=portfolio.id,
            scheme_code="119551",
            scheme_name="Axis Bluechip Fund - Direct Growth",
            units=250.5,
            nav=52.30,
            invested_amount=100000.0,
            current_value=131011.5,
            folio_number="1234567890",
        )
        db.add(mf1)

        mf2 = MutualFund(
            portfolio_id=portfolio.id,
            scheme_code="120503",
            scheme_name="Mirae Asset Large Cap Fund - Direct Growth",
            units=180.0,
            nav=98.75,
            invested_amount=150000.0,
            current_value=177750.0,
        )
        db.add(mf2)

        # ── Tax Records ──
        tax_stcg = TaxRecord(
            user_id=user.id,
            financial_year="2024-25",
            tax_jurisdiction="IN",
            gain_type="STCG",
            purchase_date=date(2024, 6, 15),
            purchase_price=420.0,
            sale_date=date(2025, 1, 10),
            sale_price=460.0,
            gain_amount=2000.0,
            tax_amount=400.0,
            holding_period_days=209,
            currency="INR",
        )
        db.add(tax_stcg)

        tax_ltcg = TaxRecord(
            user_id=user.id,
            financial_year="2025-26",
            tax_jurisdiction="IN",
            gain_type="LTCG",
            purchase_date=date(2023, 1, 10),
            purchase_price=2100.0,
            sale_date=date(2025, 3, 15),
            sale_price=2680.0,
            gain_amount=29000.0,
            tax_amount=3625.0,
            holding_period_days=795,
            currency="INR",
        )
        db.add(tax_ltcg)

        tax_de = TaxRecord(
            user_id=user.id,
            financial_year="2025",
            tax_jurisdiction="DE",
            gain_type="ABGELTUNGSSTEUER",
            purchase_date=date(2024, 3, 1),
            purchase_price=175.0,
            sale_date=date(2025, 2, 28),
            sale_price=192.0,
            gain_amount=340.0,
            tax_amount=89.58,
            holding_period_days=365,
            currency="EUR",
        )
        db.add(tax_de)

        # ── Broker Connection (demo — encrypted values are placeholders) ──
        broker = BrokerConnection(
            user_id=user.id,
            broker_name="zerodha",
            encrypted_api_key="demo_encrypted_key_placeholder",
            encrypted_api_secret="demo_encrypted_secret_placeholder",
            is_active=False,
        )
        db.add(broker)

        # ── Chat Session ──
        chat = ChatSession(
            user_id=user.id,
            messages=[
                {"role": "user", "content": "What is the best time to buy Reliance?"},
                {"role": "assistant", "content": "Based on the current RSI of 55.3, Reliance is in a neutral zone. Consider buying near the lower mid range of ₹2,200-2,400 for better risk-reward."},
                {"role": "user", "content": "What about TCS?"},
                {"role": "assistant", "content": "TCS has an RSI of 62.1 which is approaching overbought territory. You might want to wait for a pullback to the ₹3,500 level before adding more."},
            ],
            context={"portfolio_id": 1, "topic": "investment_advice"},
        )
        db.add(chat)

        await db.commit()

        print("Seeded database with demo user (demo@financetracker.dev / demo1234)")
        print(f"  - 1 portfolio with {len(SAMPLE_HOLDINGS)} holdings")
        print(f"  - {len(SAMPLE_HOLDINGS) + 7} transactions (buys + 1 sell + 6 SIP)")
        print(f"  - 2 watchlist items, 2 goals, 3 assets, 1 F&O position")
        print(f"  - 3 alerts (price, RSI, watchlist)")
        print(f"  - 3 dividends (incl. 1 DRIP)")
        print(f"  - 2 mutual funds")
        print(f"  - 3 tax records (STCG, LTCG, German)")
        print(f"  - 1 broker connection (inactive demo)")
        print(f"  - 1 chat session with sample conversation")
        print("Done!")


if __name__ == "__main__":
    asyncio.run(seed())
