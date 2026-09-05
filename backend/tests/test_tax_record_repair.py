"""Repairing tax records that were computed before the capital-gains fixes.

A ``TaxRecord`` is a SNAPSHOT of what the compute path believed when it ran,
and ``/tax/summary`` and the ITR-ready export read those STORED figures. The
compute path only re-derives a record when the LEDGER changes — so every
record written before the brokerage / loss-set-off / 2024-rate / split-lot
fixes still holds the old number, and nothing in the app corrects it.

These tests drive the repair path that does: ``recompute_stored_tax_records``
and ``POST /api/v1/tax/recompute``. Each one seeds a CORRECT record, rewrites
it to the figure the old code would have stored, and asserts the repair puts
the right number back and reports the correction.
"""

from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest
import sqlalchemy as sa
from httpx import AsyncClient
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Base
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.tax_record import TaxRecord
from app.models.transaction import Transaction
from app.models.user import User
from app.services.tax_service import (
    compute_tax_for_transaction,
    recompute_stored_tax_records,
)

BACKEND_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------

async def _user(db: AsyncSession, email: str = "repair@example.com") -> User:
    user = User(email=email, password_hash="x", display_name="Repair")
    db.add(user)
    await db.flush()
    return user


async def _holding(
    db: AsyncSession, user: User, symbol: str, exchange: str = "NSE"
) -> Holding:
    portfolio = Portfolio(user_id=user.id, name=f"P-{symbol}", currency="INR")
    db.add(portfolio)
    await db.flush()
    holding = Holding(
        portfolio_id=portfolio.id,
        stock_symbol=symbol,
        stock_name=symbol.title(),
        exchange=exchange,
        currency="INR",
        cumulative_quantity=0.0,
        average_price=0.0,
    )
    db.add(holding)
    await db.flush()
    return holding


async def _txn(
    db: AsyncSession,
    holding: Holding,
    kind: str,
    on: date,
    qty: float,
    price: float,
    brokerage: float = 0.0,
) -> Transaction:
    txn = Transaction(
        holding_id=holding.id,
        transaction_type=kind,
        date=on,
        quantity=qty,
        price=price,
        brokerage=brokerage,
    )
    db.add(txn)
    await db.flush()
    return txn


async def _records(
    db: AsyncSession, user: User, financial_year: str | None = None
) -> list[TaxRecord]:
    stmt = select(TaxRecord).where(TaxRecord.user_id == user.id)
    if financial_year is not None:
        stmt = stmt.where(TaxRecord.financial_year == financial_year)
    result = await db.execute(stmt.order_by(TaxRecord.sale_date, TaxRecord.id))
    return list(result.scalars().all())


def _year(report: dict, financial_year: str) -> dict:
    matches = [y for y in report["years"] if y["financial_year"] == financial_year]
    assert matches, f"FY {financial_year} missing from {report['years']}"
    return matches[0]


# ---------------------------------------------------------------------------
# 1. The stored figure is put back to what the fixed compute path says
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_repair_restores_the_pre_cutover_rate(db: AsyncSession):
    """A transfer made before 23-Jul-2024 is taxed at 10 %, not 12.5 %.

    The old code applied the Finance (No. 2) Act 2024 rate to every transfer,
    including ones made months before it took effect.
    """
    user = await _user(db)
    holding = await _holding(db, user, "RELIANCE")
    await _txn(db, holding, "BUY", date(2023, 1, 10), 100, 1000)
    sell = await _txn(db, holding, "SELL", date(2024, 6, 1), 100, 3000)

    await compute_tax_for_transaction(sell.id, user.id, db)
    record = (await _records(db, user))[0]
    # Gain 200,000 LTCG; Rs 1.25L exempt; 75,000 taxed at the OLD 10 %.
    assert float(record.gain_amount) == pytest.approx(200_000.0)
    assert float(record.tax_amount) == pytest.approx(7_500.0)

    # Rewrite it to what the pre-fix code stored: 12.5 % of the same base.
    record.tax_amount = 9_375.0
    await db.flush()

    report = await recompute_stored_tax_records(user.id, db)

    fresh = (await _records(db, user))[0]
    assert float(fresh.tax_amount) == pytest.approx(7_500.0)

    year = _year(report, "2024-25")
    assert year["jurisdiction"] == "IN"
    assert year["currency"] == "INR"
    assert year["total_tax_before"] == pytest.approx(9_375.0)
    assert year["total_tax_after"] == pytest.approx(7_500.0)
    assert year["total_tax_delta"] == pytest.approx(-1_875.0)
    assert year["changed"] is True
    assert year["records_recomputed"] == 1
    assert report["records_recomputed"] == 1
    assert report["years_changed"] == 1


@pytest.mark.asyncio
async def test_repair_restores_the_brokerage_aware_basis(db: AsyncSession):
    """Brokerage is part of the round trip on BOTH sides of the gain."""
    user = await _user(db)
    holding = await _holding(db, user, "INFY")
    await _txn(db, holding, "BUY", date(2025, 4, 10), 100, 1000, brokerage=500)
    sell = await _txn(db, holding, "SELL", date(2025, 9, 1), 100, 1500, brokerage=300)

    await compute_tax_for_transaction(sell.id, user.id, db)
    record = (await _records(db, user))[0]
    # (1500 - (1000 + 5 buy brokerage) - 3 sale brokerage) * 100
    assert float(record.gain_amount) == pytest.approx(49_200.0)
    assert float(record.tax_amount) == pytest.approx(9_840.0)  # 20 % STCG

    # The pre-fix figures: brokerage ignored on both sides.
    record.gain_amount = 50_000.0
    record.tax_amount = 10_000.0
    await db.flush()

    report = await recompute_stored_tax_records(user.id, db)

    fresh = (await _records(db, user))[0]
    assert float(fresh.gain_amount) == pytest.approx(49_200.0)
    assert float(fresh.tax_amount) == pytest.approx(9_840.0)
    year = _year(report, "2025-26")
    assert year["total_gain_before"] == pytest.approx(50_000.0)
    assert year["total_gain_after"] == pytest.approx(49_200.0)
    assert year["total_tax_delta"] == pytest.approx(-160.0)


@pytest.mark.asyncio
async def test_repair_applies_the_annual_loss_set_off(db: AsyncSession):
    """A loss elsewhere in the year relieves the gain — s.70(2)."""
    user = await _user(db)
    winner = await _holding(db, user, "TCS")
    await _txn(db, winner, "BUY", date(2025, 4, 10), 100, 1000)
    win_sell = await _txn(db, winner, "SELL", date(2025, 9, 1), 100, 1500)

    loser = await _holding(db, user, "WIPRO")
    await _txn(db, loser, "BUY", date(2025, 4, 10), 100, 1000)
    loss_sell = await _txn(db, loser, "SELL", date(2025, 9, 15), 100, 700)

    await compute_tax_for_transaction(win_sell.id, user.id, db)
    await compute_tax_for_transaction(loss_sell.id, user.id, db)

    records = {r.transaction_id: r for r in await _records(db, user)}
    # STCL 30,000 sets off STCG 50,000 -> 20,000 taxed at 20 %.
    assert float(records[win_sell.id].tax_amount) == pytest.approx(4_000.0)

    # Pre-fix: each sale taxed in isolation, so the whole 50,000 was charged.
    records[win_sell.id].tax_amount = 10_000.0
    await db.flush()

    report = await recompute_stored_tax_records(user.id, db)

    fresh = {r.transaction_id: r for r in await _records(db, user)}
    assert float(fresh[win_sell.id].tax_amount) == pytest.approx(4_000.0)
    assert float(fresh[loss_sell.id].tax_amount) == pytest.approx(0.0)
    year = _year(report, "2025-26")
    assert year["total_tax_before"] == pytest.approx(10_000.0)
    assert year["total_tax_after"] == pytest.approx(4_000.0)
    assert year["records_recomputed"] == 2


# ---------------------------------------------------------------------------
# 2. Orphans — records nothing can ever re-derive
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_orphan_is_dropped_and_frees_the_exemption(db: AsyncSession):
    """A record whose sale is gone keeps eating the Rs 1.25L exemption."""
    user = await _user(db)
    kept = await _holding(db, user, "HDFCBANK")
    await _txn(db, kept, "BUY", date(2024, 1, 10), 100, 1000)
    kept_sell = await _txn(db, kept, "SELL", date(2025, 9, 1), 100, 2000)

    ghost = await _holding(db, user, "ICICIBANK")
    await _txn(db, ghost, "BUY", date(2024, 1, 10), 100, 1000)
    ghost_sell = await _txn(db, ghost, "SELL", date(2025, 9, 5), 100, 2000)

    await compute_tax_for_transaction(kept_sell.id, user.id, db)
    await compute_tax_for_transaction(ghost_sell.id, user.id, db)
    ghost_sell_id = ghost_sell.id

    before = {r.transaction_id: float(r.tax_amount) for r in await _records(db, user)}
    # 1.25L exemption spent chronologically: the first sale is fully covered,
    # the second is taxed on 75,000 at 12.5 %.
    assert before[kept_sell.id] == pytest.approx(0.0)
    assert before[ghost_sell_id] == pytest.approx(9_375.0)

    # Delete the sale the way a database without FK enforcement leaves it:
    # the tax record survives, still naming a transaction that is gone.
    await db.execute(delete(Transaction).where(Transaction.id == ghost_sell_id))
    await db.flush()

    report = await recompute_stored_tax_records(user.id, db)

    remaining = await _records(db, user)
    assert [r.transaction_id for r in remaining] == [kept_sell.id]
    assert float(remaining[0].tax_amount) == pytest.approx(0.0)

    year = _year(report, "2025-26")
    assert year["orphans_dropped"] == 1
    assert year["orphans"][0]["transaction_id"] == ghost_sell_id
    assert "no longer exists" in year["orphans"][0]["reason"]
    assert year["total_tax_before"] == pytest.approx(9_375.0)
    assert year["total_tax_after"] == pytest.approx(0.0)
    assert report["orphans_dropped"] == 1


@pytest.mark.asyncio
async def test_record_whose_transaction_is_no_longer_a_sell_is_dropped(
    db: AsyncSession,
):
    """A sale corrected into a purchase cannot leave a capital gain behind."""
    user = await _user(db)
    holding = await _holding(db, user, "SBIN")
    await _txn(db, holding, "BUY", date(2025, 4, 10), 100, 1000)
    sell = await _txn(db, holding, "SELL", date(2025, 9, 1), 100, 1500)
    await compute_tax_for_transaction(sell.id, user.id, db)
    assert len(await _records(db, user)) == 1

    await db.execute(
        update(Transaction)
        .where(Transaction.id == sell.id)
        .values(transaction_type="BUY")
    )
    await db.flush()

    report = await recompute_stored_tax_records(user.id, db)

    assert await _records(db, user) == []
    year = _year(report, "2025-26")
    assert year["orphans_dropped"] == 1
    assert "not a SELL" in year["orphans"][0]["reason"]


@pytest.mark.asyncio
async def test_sale_with_no_purchase_left_is_reported_as_a_failure(db: AsyncSession):
    """A sale whose lots are gone yields a reported failure, not a silent zero."""
    user = await _user(db)
    holding = await _holding(db, user, "AXISBANK")
    buy = await _txn(db, holding, "BUY", date(2025, 4, 10), 100, 1000)
    sell = await _txn(db, holding, "SELL", date(2025, 9, 1), 100, 1500)
    await compute_tax_for_transaction(sell.id, user.id, db)

    await db.execute(delete(Transaction).where(Transaction.id == buy.id))
    await db.flush()

    report = await recompute_stored_tax_records(user.id, db)

    year = _year(report, "2025-26")
    assert year["failures"], "an unmatchable sale must be reported"
    failure = year["failures"][0]
    assert failure["transaction_id"] == sell.id
    assert failure["records_dropped"] == 1
    assert "purchase" in failure["reason"].lower()
    # The stale figure is not left standing as a number we can no longer justify.
    assert await _records(db, user) == []


# ---------------------------------------------------------------------------
# 3. What the repair must NOT touch
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_imported_records_are_counted_not_rewritten(db: AsyncSession):
    """A CSV-imported / restored record carries the user's filed figure.

    It has no transaction link — the same shape a ghost has — so the repair
    reports it and leaves it exactly as it is rather than destroying data it
    cannot re-derive.
    """
    user = await _user(db)
    db.add(
        TaxRecord(
            user_id=user.id,
            transaction_id=None,
            financial_year="2023-24",
            tax_jurisdiction="IN",
            gain_type="STCG",
            purchase_date=date(2023, 5, 1),
            sale_date=date(2023, 11, 1),
            purchase_price=100_000.0,
            sale_price=150_000.0,
            gain_amount=50_000.0,
            tax_amount=7_500.0,
            currency="INR",
        )
    )
    await db.flush()

    report = await recompute_stored_tax_records(user.id, db)

    survivors = await _records(db, user)
    assert len(survivors) == 1
    assert float(survivors[0].tax_amount) == pytest.approx(7_500.0)

    year = _year(report, "2023-24")
    assert year["unlinked_records"] == 1
    assert year["orphans_dropped"] == 0
    assert year["records_recomputed"] == 0
    assert year["changed"] is False
    assert report["unlinked_records"] == 1


@pytest.mark.asyncio
async def test_another_users_records_are_untouched(db: AsyncSession):
    """The repair is scoped to the caller."""
    mine = await _user(db, "mine@example.com")
    theirs = await _user(db, "theirs@example.com")
    for user in (mine, theirs):
        holding = await _holding(db, user, f"SYM{user.id}")
        await _txn(db, holding, "BUY", date(2025, 4, 10), 100, 1000)
        sell = await _txn(db, holding, "SELL", date(2025, 9, 1), 100, 1500)
        await compute_tax_for_transaction(sell.id, user.id, db)
        record = (await _records(db, user))[0]
        record.tax_amount = 99_999.0
    await db.flush()

    await recompute_stored_tax_records(mine.id, db)

    assert float((await _records(db, mine))[0].tax_amount) == pytest.approx(10_000.0)
    assert float((await _records(db, theirs))[0].tax_amount) == pytest.approx(99_999.0)


@pytest.mark.asyncio
async def test_financial_year_filter_limits_the_repair(db: AsyncSession):
    """Repairing one year must not silently rewrite the others."""
    user = await _user(db)
    holding = await _holding(db, user, "LT")
    await _txn(db, holding, "BUY", date(2024, 4, 10), 200, 1000)
    old_sell = await _txn(db, holding, "SELL", date(2024, 9, 1), 100, 1500)
    # LTCG on the 2025 sale (bought Apr-2024): gain 200,000, Rs 1.25L exempt,
    # 75,000 taxed at 12.5 %.
    new_sell = await _txn(db, holding, "SELL", date(2025, 9, 1), 100, 3000)
    await compute_tax_for_transaction(old_sell.id, user.id, db)
    await compute_tax_for_transaction(new_sell.id, user.id, db)

    for record in await _records(db, user):
        record.tax_amount = 42_000.0
    await db.flush()

    report = await recompute_stored_tax_records(user.id, db, financial_year="2025-26")

    assert report["years_scanned"] == 1
    assert report["financial_year"] == "2025-26"
    by_fy = {r.financial_year: float(r.tax_amount) for r in await _records(db, user)}
    assert by_fy["2025-26"] == pytest.approx(9_375.0)
    assert by_fy["2024-25"] == pytest.approx(42_000.0), "untargeted year was rewritten"


@pytest.mark.asyncio
async def test_repairing_correct_records_reports_no_change(db: AsyncSession):
    """Running the repair on healthy data must be a visible no-op."""
    user = await _user(db)
    holding = await _holding(db, user, "ITC")
    await _txn(db, holding, "BUY", date(2025, 4, 10), 100, 1000)
    sell = await _txn(db, holding, "SELL", date(2025, 9, 1), 100, 1500)
    await compute_tax_for_transaction(sell.id, user.id, db)

    report = await recompute_stored_tax_records(user.id, db)

    assert report["years_changed"] == 0
    year = _year(report, "2025-26")
    assert year["changed"] is False
    assert year["total_tax_delta"] == pytest.approx(0.0)
    assert year["orphans_dropped"] == 0
    assert year["failures"] == []


# ---------------------------------------------------------------------------
# 4. The endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_recompute_endpoint_reports_the_correction(
    client: AsyncClient, auth_headers: dict[str, str], db: AsyncSession
):
    user = (
        await db.execute(select(User).where(User.email == "testuser@example.com"))
    ).scalar_one()
    holding = await _holding(db, user, "BHARTIARTL")
    await _txn(db, holding, "BUY", date(2025, 4, 10), 100, 1000)
    sell = await _txn(db, holding, "SELL", date(2025, 9, 1), 100, 1500)
    await compute_tax_for_transaction(sell.id, user.id, db)
    (await _records(db, user))[0].tax_amount = 25_000.0
    await db.commit()

    resp = await client.post("/api/v1/tax/recompute", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["years_scanned"] == 1
    assert body["years_changed"] == 1
    assert body["records_recomputed"] == 1
    year = body["years"][0]
    assert year["financial_year"] == "2025-26"
    assert year["currency"] == "INR"
    assert year["total_tax_before"] == pytest.approx(25_000.0)
    assert year["total_tax_after"] == pytest.approx(10_000.0)

    # And the summary the user actually reads now agrees.
    summary = await client.get(
        "/api/v1/tax/summary",
        params={"financial_year": "2025-26", "jurisdiction": "IN"},
        headers=auth_headers,
    )
    assert summary.json()["total_tax"] == pytest.approx(10_000.0)


@pytest.mark.asyncio
async def test_recompute_endpoint_accepts_a_financial_year(
    client: AsyncClient, auth_headers: dict[str, str]
):
    resp = await client.post(
        "/api/v1/tax/recompute",
        params={"financial_year": "2024-25"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["financial_year"] == "2024-25"
    assert body["years_scanned"] == 0
    assert body["years"] == []


@pytest.mark.asyncio
async def test_recompute_endpoint_requires_authentication(client: AsyncClient):
    resp = await client.post("/api/v1/tax/recompute")
    assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# 5. The migration reports staleness — it never recomputes it
# ---------------------------------------------------------------------------

def _migration():
    path = (
        BACKEND_DIR
        / "alembic"
        / "versions"
        / "c1d2e3f4a5b6_report_stale_tax_records.py"
    )
    spec = importlib.util.spec_from_file_location("mig_c1d2e3f4a5b6", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _seed_sync_db():
    """A synchronous SQLite database holding one of each kind of record."""
    import app.models  # noqa: F401  — register every table on Base.metadata

    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    conn = engine.connect()

    conn.execute(
        sa.text(
            "INSERT INTO users (id, email, password_hash, preferred_currency, "
            "theme_preference, notification_preferences, is_active) VALUES "
            "(1, 'a@x.com', 'h', 'INR', 'dark', '{}', 1)"
        )
    )
    conn.execute(
        sa.text(
            "INSERT INTO portfolios (id, user_id, name, currency) "
            "VALUES (1, 1, 'P', 'INR')"
        )
    )
    conn.execute(
        sa.text(
            "INSERT INTO holdings (id, portfolio_id, stock_symbol, stock_name, "
            "exchange, currency, cumulative_quantity, average_price) "
            "VALUES (1, 1, 'RELIANCE', 'Reliance', 'NSE', 'INR', 0, 0)"
        )
    )
    # A live SELL whose ledger carries brokerage, and a BUY that supplies it.
    conn.execute(
        sa.text(
            "INSERT INTO transactions (id, holding_id, transaction_type, date, "
            "quantity, price, brokerage, source) VALUES "
            "(1, 1, 'BUY', '2023-01-10', 100, 1000, 500, 'MANUAL'), "
            "(2, 1, 'SELL', '2024-06-01', 100, 3000, 300, 'MANUAL')"
        )
    )
    # A second, brokerage-free holding for the loss / gain pair of FY 2025-26.
    conn.execute(
        sa.text(
            "INSERT INTO holdings (id, portfolio_id, stock_symbol, stock_name, "
            "exchange, currency, cumulative_quantity, average_price) "
            "VALUES (2, 1, 'INFY', 'Infosys', 'NSE', 'INR', 0, 0)"
        )
    )
    conn.execute(
        sa.text(
            "INSERT INTO transactions (id, holding_id, transaction_type, date, "
            "quantity, price, brokerage, source) VALUES "
            "(3, 2, 'BUY', '2024-01-10', 200, 1000, 0, 'MANUAL'), "
            "(4, 2, 'SELL', '2025-06-01', 100, 950, 0, 'MANUAL'), "
            "(5, 2, 'SELL', '2025-07-01', 100, 1090, 0, 'MANUAL')"
        )
    )

    def _record(rec_id, txn_id, fy, gain, tax, sale_date, gain_type="LTCG"):
        conn.execute(
            sa.text(
                "INSERT INTO tax_records (id, user_id, transaction_id, "
                "financial_year, tax_jurisdiction, gain_type, purchase_date, "
                "sale_date, purchase_price, sale_price, gain_amount, "
                "tax_amount, currency) VALUES (:id, 1, :txn, :fy, 'IN', :gt, "
                "'2023-01-10', :sd, 100000, 300000, :gain, :tax, 'INR')"
            ),
            {
                "id": rec_id,
                "txn": txn_id,
                "fy": fy,
                "gt": gain_type,
                "sd": sale_date,
                "gain": gain,
                "tax": tax,
            },
        )

    # 1: live, but taxed at 12.5 % on a pre-23-Jul-2024 transfer (ceiling 10 %).
    _record(1, 2, "2024-25", 200_000, 25_000, "2024-06-01")
    # 2: orphan — names a transaction that does not exist.
    _record(2, 999, "2024-25", 50_000, 6_250, "2024-06-01")
    # 3: imported — no transaction link at all.
    _record(3, None, "2023-24", 40_000, 4_000, "2023-11-01")
    # 4 & 5: a live loss next to a live taxed gain — the shape left behind
    # when the annual set-off never ran.
    _record(4, 4, "2025-26", -5_000, 0, "2025-06-01")
    _record(5, 5, "2025-26", 9_000, 1_125, "2025-07-01")
    # 6 & 7: the same shape made entirely of IMPORTED rows. The repair never
    # rewrites those, so the year must not be reported as stale.
    _record(6, None, "2022-23", -5_000, 0, "2022-06-01")
    _record(7, None, "2022-23", 9_000, 900, "2022-07-01")
    conn.commit()
    return conn


def test_migration_scan_groups_staleness_per_user_and_year():
    module = _migration()
    conn = _seed_sync_db()
    try:
        report = module.scan_stale_tax_records(conn)
    finally:
        conn.close()

    by_fy = {g["financial_year"]: g for g in report["groups"]}
    assert set(by_fy) == {"2022-23", "2023-24", "2024-25", "2025-26"}

    stale = by_fy["2024-25"]
    assert stale["user_id"] == 1
    assert stale["jurisdiction"] == "IN"
    assert stale["records"] == 2
    assert stale["orphans"] == 1
    assert stale["overtaxed"] == 1, "12.5 % on a pre-cutover transfer is provable"
    assert stale["brokerage_suspect"] == 1
    assert "pre-23-Jul-2024 rates" in stale["reasons"]

    imported = by_fy["2023-24"]
    assert imported["unlinked"] == 1
    assert imported["orphans"] == 0
    assert imported["stale_records"] == 0

    # A live loss beside a live taxed gain: the whole year's rewritable rows
    # are suspect, because the set-off is an annual exercise.
    unnetted = by_fy["2025-26"]
    assert unnetted["loss_suspect"] is True
    assert unnetted["stale_records"] == 2
    assert "loss not set off" in unnetted["reasons"]

    # The same shape in imported rows only: nothing the repair may rewrite,
    # so nothing to report.
    imported_loss = by_fy["2022-23"]
    assert imported_loss["unlinked"] == 2
    assert imported_loss["loss_suspect"] is False
    assert imported_loss["stale_records"] == 0

    assert report["orphan_record_ids"] == [2]
    assert report["totals"]["orphans"] == 1
    assert report["totals"]["unlinked"] == 3


def test_migration_scan_does_not_mutate_anything():
    """Log-only by default: the scan reads, it never writes."""
    module = _migration()
    conn = _seed_sync_db()
    try:
        before = conn.execute(
            sa.text("SELECT id, tax_amount FROM tax_records ORDER BY id")
        ).fetchall()
        module.scan_stale_tax_records(conn)
        after = conn.execute(
            sa.text("SELECT id, tax_amount FROM tax_records ORDER BY id")
        ).fetchall()
    finally:
        conn.close()

    assert before == after
    # And the destructive half only runs behind an explicit opt-in.
    assert module._opt_in() is False


def test_migration_opt_in_drops_only_provable_orphans():
    module = _migration()
    conn = _seed_sync_db()
    try:
        report = module.scan_stale_tax_records(conn)
        dropped = module.drop_orphaned_tax_records(
            conn, report["orphan_record_ids"]
        )
        surviving = [
            row[0]
            for row in conn.execute(
                sa.text("SELECT id FROM tax_records ORDER BY id")
            ).fetchall()
        ]
    finally:
        conn.close()

    assert dropped == 1
    # The stale-but-live records and the imported ones all stay: only a record
    # nothing can ever re-derive is deleted without asking.
    assert surviving == [1, 3, 4, 5, 6, 7]
