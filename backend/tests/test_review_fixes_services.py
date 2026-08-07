"""Service-layer correctness / data-integrity regression tests.

Covers the review fixes:

1. Broker sync re-injects the stored access token (``restore_session``) so the
   adapter is actually authenticated (``is_connected()`` becomes True).
2. Benchmark comparison degrades gracefully (``insufficient_history`` / null
   alpha) instead of fabricating an alpha, and computes a sane alpha when a
   real dated market-value series is supplied.
3. DRIP dividends are recorded as real BUY transactions and therefore survive a
   ``calculate_cumulative_holding`` recompute.
4. Reverse-split (ratio < 1) adjustments are written as a reconciling
   transaction and survive a recompute.
5. CSV import parses European number formats ("1234,56", "1.234,56") and
   decodes non-UTF-8 (cp1252) bytes without raising.

Run with:
    uv run pytest tests/test_review_fixes_services.py -q
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.brokers.base import (
    BrokerAdapter,
    BrokerHolding,
    BrokerOrder,
    BrokerPosition,
)
from app.models.corporate_action import CorporateAction
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.dividend import DividendCreate
from app.services import benchmark_service, broker_service, dividend_service
from app.services.corporate_actions_service import apply_corporate_action
from app.services.csv_import_service import _safe_float, parse_csv
from app.services.portfolio_service import calculate_cumulative_holding
from app.utils.security import encrypt_value

# ---------------------------------------------------------------------------
# Shared ORM helpers
# ---------------------------------------------------------------------------

async def _make_user(db: AsyncSession, email: str) -> User:
    user = User(email=email, password_hash="x", display_name="Reviewer")
    db.add(user)
    await db.flush()
    return user


async def _make_holding(
    db: AsyncSession,
    user: User,
    *,
    symbol: str = "RELIANCE",
    exchange: str = "NSE",
) -> Holding:
    portfolio = Portfolio(user_id=user.id, name="P", currency="INR")
    db.add(portfolio)
    await db.flush()
    holding = Holding(
        portfolio_id=portfolio.id,
        stock_symbol=symbol,
        stock_name=symbol,
        exchange=exchange,
        currency="INR",
        cumulative_quantity=0.0,
        average_price=0.0,
    )
    db.add(holding)
    await db.flush()
    return holding


async def _add_buy(
    db: AsyncSession,
    holding: Holding,
    *,
    qty: float,
    price: float,
    when: date,
) -> Transaction:
    tx = Transaction(
        holding_id=holding.id,
        transaction_type="BUY",
        date=when,
        quantity=qty,
        price=price,
        brokerage=0,
        source="MANUAL",
    )
    db.add(tx)
    await db.flush()
    return tx


# ===========================================================================
# Fix 3 — DRIP shares survive recompute
# ===========================================================================

class TestDripSurvivesRecompute:
    async def test_drip_creates_buy_txn_and_survives_recompute(self, db: AsyncSession):
        user = await _make_user(db, "drip@example.com")
        holding = await _make_holding(db, user)

        # Base position: 100 @ 10 -> cost basis 1000.
        await _add_buy(db, holding, qty=100, price=10.0, when=date(2024, 1, 1))
        await calculate_cumulative_holding(holding.id, db)
        assert float(holding.cumulative_quantity) == pytest.approx(100.0)
        assert float(holding.average_price) == pytest.approx(10.0)

        # DRIP: reinvest 10 shares @ 20.
        div = await dividend_service.create_dividend(
            DividendCreate(
                holding_id=holding.id,
                ex_date=date(2024, 6, 1),
                payment_date=date(2024, 6, 15),
                amount_per_share=2.0,
                total_amount=200.0,
                is_reinvested=True,
                reinvest_price=20.0,
                reinvest_shares=10.0,
            ),
            user_id=user.id,
            db=db,
        )

        # A real BUY transaction should have been created for the DRIP shares.
        tx_rows = (
            await db.execute(
                select(Transaction).where(Transaction.holding_id == holding.id)
            )
        ).scalars().all()
        drip_txs = [t for t in tx_rows if (t.notes or "").startswith("DRIP dividend")]
        assert len(drip_txs) == 1
        assert float(drip_txs[0].quantity) == pytest.approx(10.0)
        assert float(drip_txs[0].price) == pytest.approx(20.0)

        # Totals after DRIP: qty 110, cost 1200 -> avg 10.9091.
        expected_avg = 1200.0 / 110.0
        assert float(holding.cumulative_quantity) == pytest.approx(110.0)
        assert float(holding.average_price) == pytest.approx(expected_avg, abs=1e-4)

        # The key regression: a fresh recompute must NOT wipe the DRIP shares.
        await calculate_cumulative_holding(holding.id, db)
        assert float(holding.cumulative_quantity) == pytest.approx(110.0)
        assert float(holding.average_price) == pytest.approx(expected_avg, abs=1e-4)

        # Deleting the DRIP dividend removes the txn and restores the base.
        await dividend_service.delete_dividend(div.id, user.id, db)
        await calculate_cumulative_holding(holding.id, db)
        assert float(holding.cumulative_quantity) == pytest.approx(100.0)
        assert float(holding.average_price) == pytest.approx(10.0)

        remaining = (
            await db.execute(
                select(Transaction).where(
                    Transaction.holding_id == holding.id,
                    Transaction.notes.like("DRIP dividend%"),
                )
            )
        ).scalars().all()
        assert remaining == []


# ===========================================================================
# Fix 4 — reverse split survives recompute
# ===========================================================================

class TestReverseSplitSurvivesRecompute:
    @pytest.mark.parametrize("ratio", [0.5, 0.1])
    async def test_reverse_split_preserved(self, db: AsyncSession, ratio: float):
        user = await _make_user(db, f"revsplit{int(ratio * 100)}@example.com")
        holding = await _make_holding(db, user)

        await _add_buy(db, holding, qty=100, price=10.0, when=date(2024, 1, 1))
        await calculate_cumulative_holding(holding.id, db)

        action = CorporateAction(
            holding_id=holding.id,
            action_type="SPLIT",
            ex_date=date(2024, 3, 1),
            ratio=ratio,
            status="DETECTED",
        )
        db.add(action)
        await db.flush()

        await apply_corporate_action(action.id, user.id, db)

        expected_qty = 100.0 * ratio
        expected_avg = 10.0 / ratio
        assert float(holding.cumulative_quantity) == pytest.approx(expected_qty)
        assert float(holding.average_price) == pytest.approx(expected_avg, abs=1e-4)

        # Cost basis unchanged.
        assert float(holding.cumulative_quantity) * float(
            holding.average_price
        ) == pytest.approx(1000.0, abs=1e-2)

        # The regression: recompute from transactions must keep the split.
        await calculate_cumulative_holding(holding.id, db)
        assert float(holding.cumulative_quantity) == pytest.approx(expected_qty)
        assert float(holding.average_price) == pytest.approx(expected_avg, abs=1e-4)


# ===========================================================================
# Fix 5 — CSV European numbers + non-UTF-8 decoding
# ===========================================================================

class TestCsvLocaleAndEncoding:
    def test_european_decimal_comma(self):
        assert _safe_float("1234,56") == pytest.approx(1234.56)

    def test_european_thousands_and_decimal(self):
        assert _safe_float("2.500,00") == pytest.approx(2500.00)
        assert _safe_float("1.234.567,89") == pytest.approx(1234567.89)

    def test_us_format_still_works(self):
        assert _safe_float("2500.00") == pytest.approx(2500.00)
        assert _safe_float("1,234.56") == pytest.approx(1234.56)
        assert _safe_float("1,234") == pytest.approx(1234.0)

    def test_currency_symbols_stripped(self):
        assert _safe_float("₹1,234.56") == pytest.approx(1234.56)
        assert _safe_float("€1.234,56") == pytest.approx(1234.56)

    def test_cp1252_bytes_do_not_raise_and_parse_german_price(self):
        # Umlaut + quoted German-formatted price. Encoded as cp1252, the umlaut
        # byte (0xFC) is invalid UTF-8, so a naive utf-8 decode would 500.
        content = (
            "stock_symbol,stock_name,exchange,transaction_type,date,quantity,price\n"
            'SAP,SAP SE Müller,XETRA,BUY,2024-01-15,10,"1.234,56"\n'
        )
        raw = content.encode("cp1252")
        # utf-8 would blow up on these bytes — prove the premise.
        with pytest.raises(UnicodeDecodeError):
            raw.decode("utf-8")

        rows = parse_csv(raw)  # must not raise
        assert len(rows) == 1
        assert rows[0]["price"] == pytest.approx(1234.56)
        assert rows[0]["quantity"] == pytest.approx(10.0)
        assert "Müller" in rows[0]["stock_name"]


# ===========================================================================
# Fix 2 — benchmark alpha honesty / graceful degradation
# ===========================================================================

def _fake_benchmark_ticker(dates: list[date], closes: list[float]):
    df = pd.DataFrame(
        {"Close": closes},
        index=pd.to_datetime([d.isoformat() for d in dates]),
    )

    class _FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        def history(self, start=None, end=None):
            return df

    return _FakeTicker


class TestBenchmarkGracefulDegradation:
    async def test_sane_alpha_with_real_series(self, monkeypatch):
        today = date.today()
        dates = [today - timedelta(days=i) for i in range(20, 0, -1)]
        closes = [100.0 + i for i in range(len(dates))]  # benchmark rising
        monkeypatch.setattr(
            benchmark_service.yf, "Ticker", _fake_benchmark_ticker(dates, closes)
        )

        # Portfolio series covering the same window, rising faster than the
        # benchmark (~+19%) so alpha is clearly positive.
        pf_values = [
            {"date": d.isoformat(), "value": 1000.0 + i * 25}
            for i, d in enumerate(dates)
        ]
        result = await benchmark_service.compare_with_benchmark(
            pf_values, benchmark_name="NIFTY50", days=30
        )
        assert result is not None
        assert result.insufficient_history is False
        assert result.portfolio_return_pct is not None
        assert result.alpha is not None
        # Alpha is exactly the difference of the two windowed returns.
        assert result.alpha == pytest.approx(
            result.portfolio_return_pct - result.benchmark_return_pct, abs=0.01
        )
        # Portfolio outran the benchmark -> positive alpha.
        assert result.alpha > 0

    async def test_insufficient_history_null_alpha(self, monkeypatch):
        today = date.today()
        dates = [today - timedelta(days=i) for i in range(20, 0, -1)]
        closes = [100.0 + i for i in range(len(dates))]
        monkeypatch.setattr(
            benchmark_service.yf, "Ticker", _fake_benchmark_ticker(dates, closes)
        )

        # No portfolio history at all (mirrors "no PriceHistory rows").
        result = await benchmark_service.compare_with_benchmark(
            [], benchmark_name="NIFTY50", days=30
        )
        assert result is not None
        assert result.insufficient_history is True
        assert result.alpha is None
        assert result.portfolio_return_pct is None
        # Benchmark return is still computed honestly.
        assert result.benchmark_return_pct is not None


# ===========================================================================
# Fix 1 — broker token restore re-authenticates the adapter
# ===========================================================================

class _FakeAdapter(BrokerAdapter):
    """Minimal adapter that only becomes connected via restore_session."""

    BROKER_NAME = "fake"

    def __init__(self) -> None:
        self._connected = False
        self.restored_with: str | None = None
        self.connect_called = False

    async def connect(self, api_key: str, api_secret: str, **kwargs) -> dict:
        # Plain connect (no request_token) does NOT authenticate — mirrors the
        # real OAuth brokers whose connect() only returns a login URL.
        self.connect_called = True
        return {"access_token": None, "login_url": "https://login"}

    async def restore_session(
        self, api_key: str, api_secret: str, access_token: str
    ) -> bool:
        self.restored_with = access_token
        self._connected = True
        return True

    async def disconnect(self) -> None:
        self._connected = False

    async def get_holdings(self) -> list[BrokerHolding]:
        return []

    async def get_positions(self) -> list[BrokerPosition]:
        return []

    async def get_orders(self, from_date=None, to_date=None) -> list[BrokerOrder]:
        return []

    async def get_historical_data(
        self, symbol, exchange, from_date, to_date, interval="day"
    ) -> list[dict]:
        return []

    def is_connected(self) -> bool:
        return self._connected


class TestBrokerTokenRestore:
    async def test_stored_token_restores_is_connected(
        self, db: AsyncSession, monkeypatch
    ):
        from app.models.broker_connection import BrokerConnection

        user = await _make_user(db, "broker@example.com")
        conn = BrokerConnection(
            user_id=user.id,
            broker_name="zerodha",
            encrypted_api_key=encrypt_value("api_key"),
            encrypted_api_secret=encrypt_value("api_secret"),
            access_token_encrypted=encrypt_value("stored-token"),
            is_active=True,
        )
        db.add(conn)
        await db.flush()

        fake = _FakeAdapter()
        monkeypatch.setattr(broker_service, "get_broker", lambda name: fake)

        status = await broker_service.get_connection_status(conn.id, user.id, db)

        assert status["is_connected"] is True
        # The service must have passed the *decrypted* stored token to the
        # adapter's restore_session (not left it unauthenticated).
        assert fake.restored_with == "stored-token"
        assert fake.connect_called is False

    async def test_zerodha_adapter_restore_validates_token(self, monkeypatch):
        """Zerodha restore_session validates the stored token with a cheap
        authenticated call (``kite.profile()``): a valid token restores the
        session, a rejected (expired) token returns False instead of silently
        arming a dead client."""
        from app.brokers import zerodha
        from app.brokers.zerodha import ZerodhaBroker

        class _FakeKite:
            profile_ok = True

            def __init__(self, api_key: str) -> None:
                self.api_key = api_key
                self.token: str | None = None

            def set_access_token(self, token: str) -> None:
                self.token = token

            def profile(self) -> dict:
                if not _FakeKite.profile_ok:
                    raise Exception("TokenException: token expired")
                return {"user_id": "AB1234"}

        monkeypatch.setattr(zerodha, "_KITE_AVAILABLE", True)
        monkeypatch.setattr(zerodha, "KiteConnect", _FakeKite)

        # Valid token → restored, connected.
        _FakeKite.profile_ok = True
        broker = ZerodhaBroker()
        assert broker.is_connected() is False
        restored = await broker.restore_session("api_key", "api_secret", "tok-123")
        assert restored is True
        assert broker.is_connected() is True
        assert broker._access_token == "tok-123"

        # Dead token → validation fails → False, still disconnected.
        _FakeKite.profile_ok = False
        broker2 = ZerodhaBroker()
        restored2 = await broker2.restore_session("api_key", "api_secret", "tok-dead")
        assert restored2 is False
        assert broker2.is_connected() is False
