"""A stock split re-bases the existing lots; it is not an acquisition.

``apply_corporate_action`` used to record a split by appending a zero-price BUY
dated at the ex-date. That gives the split shares a NIL cost basis and the
ex-date as their acquisition date, so the next sale reports a fabricated loss
on the original lot and a fabricated short-term gain on the phantom one. The
headline case — 100 @ Rs 1000, 2:1 split, two sales of 100 @ Rs 600 — billed
Rs 12,000 of STCG against a true liability of Rs 0.

The law both regimes apply is a re-basing:

- India s.55(2)(b)(v) with s.2(42A) Expl. 1(i)(d)/(e) — the original cost is
  spread over the enlarged share count, the holding period is inherited.
- Germany s.20 EStG — a Split is steuerneutral; Anschaffungskosten je Stueck
  are divided by the ratio, the Anschaffungszeitpunkt is unchanged.

A genuine Indian BONUS issue is the exception (s.55(2)(aa)(iiia): nil cost,
allotment-date holding period) and keeps the zero-cost lot.

Also covers the opt-in repair in alembic revision b7c8d9e0f1a2, which restates
splits already applied in the old shape.

Run with:
    uv run pytest tests/test_split_rebase.py -q
"""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.corporate_action import CorporateAction
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.tax_record import TaxRecord
from app.models.transaction import Transaction
from app.models.user import User
from app.services.corporate_actions_service import apply_corporate_action
from app.services.portfolio_service import calculate_cumulative_holding
from app.services.tax_service import build_open_lots, compute_tax_for_transaction

BACKEND_DIR = Path(__file__).resolve().parent.parent
MIGRATION_PATH = (
    BACKEND_DIR / "alembic" / "versions" / "b7c8d9e0f1a2_repair_split_zero_cost_lots.py"
)


def _load_migration():
    """Import the repair revision by path (alembic/versions is not a package)."""
    spec = importlib.util.spec_from_file_location("_split_repair", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _make_holding(
    db: AsyncSession,
    email: str,
    *,
    exchange: str = "NSE",
    symbol: str = "TESTCO",
) -> tuple[User, Holding]:
    user = User(email=email, password_hash="x", display_name="Split Tester")
    db.add(user)
    await db.flush()

    portfolio = Portfolio(user_id=user.id, name="Split Portfolio")
    db.add(portfolio)
    await db.flush()

    holding = Holding(
        portfolio_id=portfolio.id,
        stock_symbol=symbol,
        stock_name=symbol,
        exchange=exchange,
        cumulative_quantity=0.0,
        average_price=0.0,
    )
    db.add(holding)
    await db.flush()
    return user, holding


async def _tx(
    db: AsyncSession,
    holding: Holding,
    ttype: str,
    when: date,
    qty: float,
    price: float,
    *,
    notes: str | None = None,
) -> Transaction:
    txn = Transaction(
        holding_id=holding.id,
        transaction_type=ttype,
        date=when,
        quantity=qty,
        price=price,
        brokerage=0,
        notes=notes,
        source="MANUAL",
    )
    db.add(txn)
    await db.flush()
    await db.refresh(txn)
    return txn


async def _action(
    db: AsyncSession,
    holding: Holding,
    ex_date: date,
    ratio: float,
    *,
    action_type: str = "SPLIT",
    status: str = "DETECTED",
    details: dict | None = None,
) -> CorporateAction:
    action = CorporateAction(
        holding_id=holding.id,
        action_type=action_type,
        ex_date=ex_date,
        ratio=ratio,
        status=status,
        details=details if details is not None else {},
    )
    db.add(action)
    await db.flush()
    await db.refresh(action)
    return action


async def _ledger(db: AsyncSession, holding_id: int) -> list[Transaction]:
    rows = await db.execute(
        select(Transaction)
        .where(Transaction.holding_id == holding_id)
        .order_by(Transaction.date, Transaction.id)
    )
    return list(rows.scalars().all())


async def _records(db: AsyncSession, user: User) -> list[TaxRecord]:
    rows = await db.execute(
        select(TaxRecord)
        .where(TaxRecord.user_id == user.id)
        .order_by(TaxRecord.sale_date, TaxRecord.transaction_id, TaxRecord.id)
    )
    return list(rows.scalars().all())


async def _records_for(db: AsyncSession, txn_id: int) -> list[TaxRecord]:
    rows = await db.execute(
        select(TaxRecord)
        .where(TaxRecord.transaction_id == txn_id)
        .order_by(TaxRecord.id)
    )
    return list(rows.scalars().all())


# ===========================================================================
# 1. A split re-bases the lot — no zero-cost acquisition
# ===========================================================================

class TestSplitRebasesLots:
    async def test_split_rebases_lots_not_new_acquisition(self, db: AsyncSession):
        user, holding = await _make_holding(db, "split-rebase@example.com")
        await _tx(db, holding, "BUY", date(2022, 1, 10), 100, 1000.0)
        await calculate_cumulative_holding(holding.id, db)

        action = await _action(db, holding, date(2025, 6, 3), 2.0)
        result = await apply_corporate_action(action.id, user.id, db)

        # ONE lot, re-based, with the ORIGINAL acquisition date.
        lots = build_open_lots(await _ledger(db, holding.id))
        assert len(lots) == 1
        assert lots[0]["qty"] == pytest.approx(200.0)
        assert lots[0]["price"] == pytest.approx(500.0)
        assert lots[0]["date"] == date(2022, 1, 10)

        # No zero-cost row was fabricated.
        assert all(float(t.price) != 0 for t in await _ledger(db, holding.id))
        assert result["details"]["applied"]["adjustment_transaction"] is False
        assert result["details"]["applied"]["treatment"] == "REBASE"

        # Holding still derives from the ledger.
        assert float(holding.cumulative_quantity) == pytest.approx(200.0)
        assert float(holding.average_price) == pytest.approx(500.0)

        sell1 = await _tx(db, holding, "SELL", date(2025, 8, 1), 100, 600.0)
        await compute_tax_for_transaction(sell1.id, user.id, db)
        recs1 = await _records_for(db, sell1.id)
        assert len(recs1) == 1
        assert recs1[0].gain_type == "LTCG"
        assert recs1[0].purchase_date == date(2022, 1, 10)
        assert float(recs1[0].gain_amount) == pytest.approx(10000.0)
        assert float(recs1[0].tax_amount) == pytest.approx(0.0)

        sell2 = await _tx(db, holding, "SELL", date(2025, 9, 1), 100, 600.0)
        await compute_tax_for_transaction(sell2.id, user.id, db)
        recs2 = await _records_for(db, sell2.id)
        assert len(recs2) == 1
        assert recs2[0].gain_type == "LTCG"
        assert float(recs2[0].gain_amount) == pytest.approx(10000.0)
        assert float(recs2[0].tax_amount) == pytest.approx(0.0)

        # Regression guard: the zero-cost lot billed Rs 12,000 here.
        total_tax = sum(float(r.tax_amount or 0) for r in await _records(db, user))
        assert total_tax == pytest.approx(0.0)

        # Position fully sold: nothing left open.
        assert build_open_lots(await _ledger(db, holding.id)) == []


    async def test_rebase_leaves_notes_alone(self, db: AsyncSession):
        """``dividend_service`` deletes a reinvestment BUY by an exact
        ``notes ==`` match, so the restatement must not touch ``notes``."""
        user, holding = await _make_holding(db, "split-drip@example.com")
        await _tx(db, holding, "BUY", date(2022, 1, 10), 100, 1000.0, notes=None)
        await _tx(
            db, holding, "BUY", date(2023, 4, 1), 5, 1200.0,
            notes="DRIP dividend #7",
        )
        await calculate_cumulative_holding(holding.id, db)

        action = await _action(db, holding, date(2025, 6, 3), 2.0)
        await apply_corporate_action(action.id, user.id, db)

        rows = await _ledger(db, holding.id)
        assert [r.notes for r in rows] == [None, "DRIP dividend #7"]
        assert [float(r.quantity) for r in rows] == [200.0, 10.0]
        assert [float(r.price) for r in rows] == [500.0, 600.0]


# ===========================================================================
# 2. Already-realized gains survive the restatement
# ===========================================================================

class TestSplitPreservesRealizedGains:
    async def test_split_preserves_already_realized_gains(self, db: AsyncSession):
        user, holding = await _make_holding(db, "split-realized@example.com")
        await _tx(db, holding, "BUY", date(2022, 1, 10), 100, 1000.0)
        sell_old = await _tx(db, holding, "SELL", date(2023, 5, 1), 40, 1500.0)
        await calculate_cumulative_holding(holding.id, db)
        await compute_tax_for_transaction(sell_old.id, user.id, db)

        before = await _records_for(db, sell_old.id)
        assert len(before) == 1
        assert float(before[0].gain_amount) == pytest.approx(20000.0)
        assert before[0].gain_type == "LTCG"

        action = await _action(db, holding, date(2025, 6, 3), 2.0)
        await apply_corporate_action(action.id, user.id, db)

        # The realized gain is unchanged — same consideration, re-based unit.
        after = await _records_for(db, sell_old.id)
        assert len(after) == 1
        assert float(after[0].gain_amount) == pytest.approx(20000.0)
        assert after[0].gain_type == "LTCG"
        assert after[0].purchase_date == date(2022, 1, 10)

        rows = await _ledger(db, holding.id)
        buy, sell = rows[0], rows[1]
        assert (float(buy.quantity), float(buy.price)) == (200.0, 500.0)
        assert (float(sell.quantity), float(sell.price)) == (80.0, 750.0)
        # Restating the SELL keeps the residual right: 120, not 160.
        assert float(holding.cumulative_quantity) == pytest.approx(120.0)

        sell1 = await _tx(db, holding, "SELL", date(2025, 8, 1), 60, 600.0)
        await compute_tax_for_transaction(sell1.id, user.id, db)
        rec1 = (await _records_for(db, sell1.id))[0]
        assert rec1.gain_type == "LTCG"
        assert float(rec1.gain_amount) == pytest.approx(6000.0)
        assert float(rec1.tax_amount) == pytest.approx(0.0)

        sell2 = await _tx(db, holding, "SELL", date(2025, 9, 1), 60, 600.0)
        await compute_tax_for_transaction(sell2.id, user.id, db)
        rec2 = (await _records_for(db, sell2.id))[0]
        assert rec2.gain_type == "LTCG"
        assert float(rec2.gain_amount) == pytest.approx(6000.0)
        assert float(rec2.tax_amount) == pytest.approx(0.0)

        # Buggy: -24,000 LTCG then +36,000 STCG -> Rs 7,200 of tax.
        fy_2025 = [r for r in await _records(db, user) if r.financial_year == "2025-26"]
        assert sum(float(r.tax_amount or 0) for r in fy_2025) == pytest.approx(0.0)


# ===========================================================================
# 3. Reverse split leaves no phantom lots
# ===========================================================================

class TestReverseSplitRebase:
    async def test_reverse_split_leaves_no_phantom_lots(self, db: AsyncSession):
        user, holding = await _make_holding(db, "split-reverse@example.com")
        await _tx(db, holding, "BUY", date(2022, 1, 10), 100, 100.0)
        await calculate_cumulative_holding(holding.id, db)

        action = await _action(db, holding, date(2025, 6, 3), 0.1)
        await apply_corporate_action(action.id, user.id, db)

        lots = build_open_lots(await _ledger(db, holding.id))
        assert len(lots) == 1
        assert lots[0]["qty"] == pytest.approx(10.0)
        assert lots[0]["price"] == pytest.approx(1000.0)
        assert lots[0]["date"] == date(2022, 1, 10)
        assert sum(lot["qty"] for lot in lots) == pytest.approx(
            float(holding.cumulative_quantity)
        ) == pytest.approx(10.0)

        sell = await _tx(db, holding, "SELL", date(2025, 8, 1), 10, 1200.0)
        await compute_tax_for_transaction(sell.id, user.id, db)
        rec = (await _records_for(db, sell.id))[0]
        # Buggy: 11,000 (a zero-cost negative row left 90 phantom shares).
        assert float(rec.gain_amount) == pytest.approx(2000.0)
        assert rec.gain_type == "LTCG"

        assert build_open_lots(await _ledger(db, holding.id)) == []


# ===========================================================================
# 4. Germany — the split must not burn the Sparer-Pauschbetrag
# ===========================================================================

class TestGermanSplitRebase:
    async def test_split_german_freibetrag_allocation(self, db: AsyncSession):
        user, holding = await _make_holding(
            db, "split-de@example.com", exchange="XETRA", symbol="SAP"
        )
        await _tx(db, holding, "BUY", date(2022, 1, 10), 100, 50.0)
        await calculate_cumulative_holding(holding.id, db)

        action = await _action(db, holding, date(2025, 6, 3), 2.0)
        await apply_corporate_action(action.id, user.id, db)
        assert float(holding.cumulative_quantity) == pytest.approx(200.0)
        assert float(holding.average_price) == pytest.approx(25.0)

        sell1 = await _tx(db, holding, "SELL", date(2025, 8, 1), 100, 30.0)
        await compute_tax_for_transaction(sell1.id, user.id, db)
        sell2 = await _tx(db, holding, "SELL", date(2026, 2, 1), 100, 30.0)
        await compute_tax_for_transaction(sell2.id, user.id, db)

        records = await _records(db, user)
        assert [
            (r.financial_year, round(float(r.gain_amount), 2), float(r.tax_amount))
            for r in records
        ] == [("2025", 500.0, 0.0), ("2026", 500.0, 0.0)]
        # Buggy: -2,000 then +3,000 -> EUR 527.50 of Abgeltungsteuer.
        assert sum(float(r.tax_amount or 0) for r in records) == pytest.approx(0.0)


# ===========================================================================
# 5. Grandfathering (31-Jan-2018) compares like with like after the re-basing
# ===========================================================================

class TestSplitGrandfathering:
    async def test_split_grandfathering_uses_rebased_cost(
        self, db: AsyncSession, monkeypatch
    ):
        # yfinance's 31-Jan-2018 close is already adjusted for every later
        # split, so a PRE-split lot cost could never be compared against it.
        async def _fake_fmv(symbol: str, exchange: str) -> float:
            return 600.0

        monkeypatch.setattr("app.services.tax_service.get_fmv_31jan2018", _fake_fmv)

        user, holding = await _make_holding(db, "split-fmv@example.com")
        await _tx(db, holding, "BUY", date(2017, 6, 1), 1000, 1000.0)
        await calculate_cumulative_holding(holding.id, db)

        action = await _action(db, holding, date(2020, 6, 3), 2.0)
        await apply_corporate_action(action.id, user.id, db)

        sell = await _tx(db, holding, "SELL", date(2025, 8, 1), 2000, 700.0)
        await compute_tax_for_transaction(sell.id, user.id, db)
        rec = (await _records_for(db, sell.id))[0]

        assert rec.gain_type == "LTCG"
        # s.55(2)(ac): basis = max(500, min(600, 700)) = 600 -> 1,200,000.
        assert float(rec.purchase_price) == pytest.approx(1200000.0)
        assert float(rec.gain_amount) == pytest.approx(200000.0)
        # Buggy: grandfathering never fired -> 400,000 gain, Rs 34,375 of tax.
        assert float(rec.tax_amount) == pytest.approx(9375.0)


# ===========================================================================
# 6. An Indian BONUS issue really IS a nil-cost acquisition
# ===========================================================================

class TestIndianBonusIsAnAcquisition:
    async def test_bonus_keeps_nil_cost_allotment_lot(self, db: AsyncSession):
        user, holding = await _make_holding(db, "bonus-in@example.com")
        await _tx(db, holding, "BUY", date(2022, 1, 10), 100, 1000.0)
        await calculate_cumulative_holding(holding.id, db)

        action = await _action(
            db, holding, date(2025, 6, 3), 2.0, action_type="BONUS"
        )
        result = await apply_corporate_action(action.id, user.id, db)

        # s.55(2)(aa)(iiia): nil cost; s.2(42A) Expl. 1(i)(f): the holding
        # period runs from the allotment date. The zero-cost lot is correct.
        assert result["details"]["applied"]["treatment"] == "NIL_COST_ALLOTMENT"
        assert result["details"]["applied"]["adjustment_transaction"] is True

        lots = build_open_lots(await _ledger(db, holding.id))
        assert len(lots) == 2
        assert (lots[0]["qty"], lots[0]["price"], lots[0]["date"]) == (
            100.0, 1000.0, date(2022, 1, 10)
        )
        assert (lots[1]["qty"], lots[1]["price"], lots[1]["date"]) == (
            100.0, 0.0, date(2025, 6, 3)
        )

        # The original lot is untouched: still LTCG from 2022.
        sell1 = await _tx(db, holding, "SELL", date(2025, 8, 1), 100, 600.0)
        await compute_tax_for_transaction(sell1.id, user.id, db)
        rec1 = (await _records_for(db, sell1.id))[0]
        assert rec1.gain_type == "LTCG"
        assert rec1.purchase_date == date(2022, 1, 10)
        assert float(rec1.gain_amount) == pytest.approx(-40000.0)

        # The bonus shares are a fresh, nil-cost, short-term holding.
        sell2 = await _tx(db, holding, "SELL", date(2025, 9, 1), 100, 600.0)
        await compute_tax_for_transaction(sell2.id, user.id, db)
        rec2 = (await _records_for(db, sell2.id))[0]
        assert rec2.gain_type == "STCG"
        assert rec2.purchase_date == date(2025, 6, 3)
        assert float(rec2.gain_amount) == pytest.approx(60000.0)


# ===========================================================================
# 7. Applying a split recomputes the tax records it invalidated
# ===========================================================================

class TestSplitRecomputesTax:
    async def test_stale_post_ex_records_are_recomputed_in_order(
        self, db: AsyncSession
    ):
        user, holding = await _make_holding(db, "split-recompute@example.com")
        await _tx(db, holding, "BUY", date(2022, 1, 10), 200, 500.0)
        await calculate_cumulative_holding(holding.id, db)

        # Sales computed BEFORE the (late-detected) split is applied.
        sell1 = await _tx(db, holding, "SELL", date(2025, 8, 1), 100, 300.0)
        await compute_tax_for_transaction(sell1.id, user.id, db)
        sell2 = await _tx(db, holding, "SELL", date(2025, 9, 1), 100, 300.0)
        await compute_tax_for_transaction(sell2.id, user.id, db)
        assert float((await _records_for(db, sell1.id))[0].gain_amount) == pytest.approx(
            -20000.0
        )

        # The split's ex-date precedes both sales, so both were computed
        # against a pre-split cost basis.
        action = await _action(db, holding, date(2025, 6, 3), 2.0)
        result = await apply_corporate_action(action.id, user.id, db)

        recompute = result["details"]["applied"]["tax_recompute"]
        assert recompute["recomputed"] == [sell1.id, sell2.id]
        assert recompute["failed"] == []
        assert recompute["records_removed"] == []

        # 400 shares @ 250; each sale of 100 @ 300 gains 5,000.
        assert float((await _records_for(db, sell1.id))[0].gain_amount) == pytest.approx(
            5000.0
        )
        assert float((await _records_for(db, sell2.id))[0].gain_amount) == pytest.approx(
            5000.0
        )


# ===========================================================================
# 8. The opt-in repair of splits already applied in the old shape
# ===========================================================================

class TestMigrationRepair:
    """The opt-in repair in alembic revision b7c8d9e0f1a2.

    The raw-SQL repair runs outside the ORM, so every test captures plain ids
    BEFORE running it and re-reads through awaited queries afterwards.
    """

    async def _seed_old_shape(
        self,
        db: AsyncSession,
        email: str,
        *,
        ratio: float,
        action_type: str = "SPLIT",
    ) -> dict:
        """The exact rows the pre-fix ``apply_corporate_action`` wrote."""
        user, holding = await _make_holding(db, email)
        buy = await _tx(db, holding, "BUY", date(2022, 1, 10), 100, 1000.0)
        marker = await _tx(
            db,
            holding,
            "BUY",
            date(2025, 6, 3),
            100 * (ratio - 1),
            0.0,
            notes=f"{action_type} adjustment (ratio {ratio}) — auto",
        )
        action = await _action(
            db,
            holding,
            date(2025, 6, 3),
            ratio,
            action_type=action_type,
            status="APPLIED",
            details={"applied": {"adjustment_transaction": True, "ratio": ratio}},
        )
        holding = await calculate_cumulative_holding(holding.id, db)
        return {
            "user_id": user.id,
            "holding_id": holding.id,
            "action_id": action.id,
            "buy_id": buy.id,
            "marker_id": marker.id,
            "quantity": float(holding.cumulative_quantity),
            "average_price": float(holding.average_price),
        }

    async def _run_repair(self, db: AsyncSession, *, dry_run: bool) -> dict:
        module = _load_migration()
        await db.flush()
        conn = await db.connection()
        report = await conn.run_sync(
            lambda sync_conn: module.repair_applied_split_actions(
                sync_conn, dry_run=dry_run
            )
        )
        # The repair wrote through raw SQL; drop the ORM's stale copies.
        db.expire_all()
        return report

    @pytest.mark.parametrize("ratio", [2.0, 1.5, 0.1])
    async def test_migration_rebases_already_applied_split(
        self, db: AsyncSession, ratio: float
    ):
        seed = await self._seed_old_shape(
            db, f"repair{int(ratio * 100)}@example.com", ratio=ratio
        )
        assert seed["quantity"] == pytest.approx(100 * ratio)

        report = await self._run_repair(db, dry_run=False)
        assert report["scanned_actions"] == 1
        assert report["repaired_actions"] == [seed["action_id"]]
        assert report["quarantined"] == []

        rows = await _ledger(db, seed["holding_id"])
        # The zero-price adjustment row is gone.
        assert [r.id for r in rows] == [seed["buy_id"]]
        buy = rows[0]
        assert float(buy.quantity) == pytest.approx(100 * ratio)
        assert float(buy.price) == pytest.approx(1000.0 / ratio, abs=1e-4)
        assert buy.date == date(2022, 1, 10)

        # The holding is unchanged by the repair — both schemes preserve the
        # cost basis; only the lot's acquisition date and unit change.
        holding = await calculate_cumulative_holding(seed["holding_id"], db)
        assert float(holding.cumulative_quantity) == pytest.approx(seed["quantity"])
        assert float(holding.average_price) == pytest.approx(
            seed["average_price"], abs=1e-4
        )
        assert float(holding.cumulative_quantity) * float(
            holding.average_price
        ) == pytest.approx(100000.0, abs=0.05)

        action = await db.get(CorporateAction, seed["action_id"])
        assert action is not None
        assert action.details["applied"]["adjustment_transaction"] is False
        repaired = action.details["repaired"]
        assert repaired["removed_transaction_id"] == seed["marker_id"]
        # The pre-restatement values are stashed, so the repair is reversible.
        assert repaired["rebased"] == [
            {"transaction_id": seed["buy_id"], "quantity": 100.0, "price": 1000.0}
        ]

        # And the lot the tax engine now sees is the re-based original.
        lots = build_open_lots(rows)
        assert len(lots) == 1
        assert lots[0]["date"] == date(2022, 1, 10)
        assert lots[0]["qty"] * lots[0]["price"] == pytest.approx(100000.0, abs=0.05)

    async def test_repair_leaves_notes_alone(self, db: AsyncSession):
        """``dividend_service`` finds a DRIP BUY by an exact ``notes ==``
        match; restating a row must not break that lookup."""
        seed = await self._seed_old_shape(db, "repair-notes@example.com", ratio=2.0)
        await self._run_repair(db, dry_run=False)

        rows = await _ledger(db, seed["holding_id"])
        assert [r.notes for r in rows] == [None]

    async def test_dry_run_reports_without_writing(self, db: AsyncSession):
        seed = await self._seed_old_shape(db, "repair-dry@example.com", ratio=2.0)
        report = await self._run_repair(db, dry_run=True)

        assert report["dry_run"] is True
        assert report["scanned_actions"] == 1
        assert report["repaired_actions"] == [seed["action_id"]]

        rows = await _ledger(db, seed["holding_id"])
        assert [float(r.price) for r in rows] == [1000.0, 0.0]  # untouched
        action = await db.get(CorporateAction, seed["action_id"])
        assert action is not None
        assert action.details["applied"]["adjustment_transaction"] is True

    async def test_bonus_action_is_not_migrated(self, db: AsyncSession):
        seed = await self._seed_old_shape(
            db, "repair-bonus@example.com", ratio=2.0, action_type="BONUS"
        )
        report = await self._run_repair(db, dry_run=False)

        # A nil-cost allotment lot is CORRECT for an Indian bonus issue.
        assert report["scanned_actions"] == 0
        rows = await _ledger(db, seed["holding_id"])
        assert [float(r.price) for r in rows] == [1000.0, 0.0]

    async def test_user_entered_zero_price_buy_is_not_touched(
        self, db: AsyncSession
    ):
        _user, holding = await _make_holding(db, "repair-manual@example.com")
        await _tx(db, holding, "BUY", date(2022, 1, 10), 100, 1000.0)
        # A user's own zero-price row on the ex-date, without the auto note.
        await _tx(db, holding, "BUY", date(2025, 6, 3), 10, 0.0, notes="gift")
        await _action(db, holding, date(2025, 6, 3), 2.0, status="APPLIED")
        holding_id = holding.id

        report = await self._run_repair(db, dry_run=False)
        assert report["scanned_actions"] == 0
        assert [float(r.quantity) for r in await _ledger(db, holding_id)] == [
            100.0, 10.0
        ]

    async def test_point_in_time_oversell_is_quarantined_not_rewritten(
        self, db: AsyncSession
    ):
        """A backdated SELL can leave nothing held on the ex-date.

        ``create_transaction`` validates a sale against the CURRENT quantity,
        not the quantity held on the sale date, so this shape is reachable.
        The two schemes disagree on the resulting quantity, so the repair must
        leave the holding alone and say so rather than rewrite it.
        """
        _user, holding = await _make_holding(db, "repair-oversell@example.com")
        await _tx(db, holding, "BUY", date(2022, 1, 10), 100, 1000.0)
        await _tx(db, holding, "SELL", date(2023, 1, 10), 100, 1200.0)
        await _tx(db, holding, "BUY", date(2025, 7, 1), 50, 600.0)
        marker = await _tx(
            db, holding, "BUY", date(2025, 6, 3), 25, 0.0,
            notes="SPLIT adjustment (ratio 2.0) — auto",
        )
        action = await _action(db, holding, date(2025, 6, 3), 2.0, status="APPLIED")
        holding_id, marker_id, action_id = holding.id, marker.id, action.id

        report = await self._run_repair(db, dry_run=False)
        assert report["repaired_actions"] == []
        assert len(report["quarantined"]) == 1
        assert report["quarantined"][0]["holding_id"] == holding_id
        assert "ex-date" in report["quarantined"][0]["reason"]

        # Nothing was written.
        rows = await _ledger(db, holding_id)
        assert marker_id in [r.id for r in rows]
        assert [float(r.quantity) for r in rows] == [100.0, 100.0, 25.0, 50.0]
        action = await db.get(CorporateAction, action_id)
        assert action is not None
        assert action.details.get("repaired") is None

    async def test_repair_reports_sells_needing_tax_recompute(
        self, db: AsyncSession
    ):
        seed = await self._seed_old_shape(db, "repair-tax@example.com", ratio=2.0)
        holding = await db.get(Holding, seed["holding_id"])
        assert holding is not None
        sell = await _tx(db, holding, "SELL", date(2025, 8, 1), 100, 600.0)
        sell_id = sell.id
        await compute_tax_for_transaction(sell_id, seed["user_id"], db)
        stale_gain = float((await _records_for(db, sell_id))[0].gain_amount)

        report = await self._run_repair(db, dry_run=False)
        pending = report["tax_records_to_recompute"]
        assert [row["transaction_id"] for row in pending] == [sell_id]
        assert pending[0]["user_id"] == seed["user_id"]

        # The repair does not recompute (it cannot: the FMV lookup needs the
        # network and the FY driver must run oldest-FY-first). The service-side
        # helper does, in (sale_date, transaction_id) order.
        from app.services.corporate_actions_service import (
            recompute_tax_after_ledger_change,
        )

        tax_report = await recompute_tax_after_ledger_change(
            seed["holding_id"], seed["user_id"], db
        )
        assert tax_report["recomputed"] == [sell_id]
        fixed_gain = float((await _records_for(db, sell_id))[0].gain_amount)
        assert stale_gain == pytest.approx(-40000.0)   # computed off the bad lots
        assert fixed_gain == pytest.approx(10000.0)    # 100 @ 600 vs 100 @ 500
