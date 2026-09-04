"""Tests for tax-record CSV import deduplication.

``import_tax_records`` used to insert unconditionally, so re-uploading the same
broker statement doubled every disposal.  That is not cosmetic: the Rs 1,25,000
s.112A LTCG exemption and the EUR 1,000 Sparer-Pauschbetrag are both
per-assessee-per-year, so a phantom row consumes an allowance a *real* later
sale then has to pay tax on — and the Schedule-CG / ITR export emits each
disposal twice, which is an incorrect return.

These tests pin the fixed point (re-upload is a no-op) and, just as importantly,
the cases dedup must NOT swallow: legitimate identical disposals inside one
file, rows that differ, and records the FIFO engine computed itself.

Run with:
    cd backend && uv run pytest tests/test_import_dedup.py -q
"""

from __future__ import annotations

from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.tax_record import TaxRecord
from app.models.transaction import Transaction
from app.models.user import User
from app.services.csv_import_service import import_tax_records, parse_csv_tax_records
from app.services.export_service import export_tax_report_csv
from app.services.tax_service import (
    compute_german_allowance,
    compute_tax_for_transaction,
    generate_tax_summary,
)
from tests.conftest import TestSessionFactory

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

HEADER = (
    "financial_year,tax_jurisdiction,gain_type,purchase_date,sale_date,"
    "purchase_price,sale_price,gain_amount,tax_amount,currency"
)

# The two rows the repro used.  A: LTCG 10,000 (tax 1,250); B: STCG 8,000
# (tax 1,600).  Totals for the FY: LTCG 10,000 / STCG 8,000 / tax 2,850.
ROW_A = "2024-25,IN,LTCG,2023-01-15,2024-08-20,25000.00,35000.00,10000.00,1250.00,INR"
ROW_B = "2024-25,IN,STCG,2024-02-01,2024-09-10,50000.00,58000.00,8000.00,1600.00,INR"
# C differs from A only in proceeds/gain -> a genuinely different disposal.
ROW_C = "2024-25,IN,LTCG,2023-01-15,2024-08-20,25000.00,36000.00,11000.00,1375.00,INR"


def csv_bytes(*rows: str) -> bytes:
    """Build a tax-record CSV from the shared header plus the given rows."""
    return ("\n".join([HEADER, *rows]) + "\n").encode()


TAX_CSV = csv_bytes(ROW_A, ROW_B)


async def _make_user(db: AsyncSession, email: str = "dedup@example.com") -> User:
    user = User(email=email, password_hash="x", display_name="Dedup Tester")
    db.add(user)
    await db.flush()
    return user


async def _make_holding(db: AsyncSession, user: User) -> Holding:
    portfolio = Portfolio(user_id=user.id, name="Dedup Portfolio", currency="INR")
    db.add(portfolio)
    await db.flush()

    holding = Holding(
        portfolio_id=portfolio.id,
        stock_symbol="INFY",
        stock_name="Infosys",
        exchange="NSE",
        currency="INR",
        cumulative_quantity=100.0,
        average_price=1000.0,
    )
    db.add(holding)
    await db.flush()
    return holding


async def _add_txn(
    db: AsyncSession,
    holding: Holding,
    *,
    txn_type: str,
    txn_date: date,
    quantity: float,
    price: float,
) -> Transaction:
    txn = Transaction(
        holding_id=holding.id,
        transaction_type=txn_type,
        date=txn_date,
        quantity=quantity,
        price=price,
    )
    db.add(txn)
    await db.flush()
    return txn


async def _import(db: AsyncSession, user: User, data: bytes, **kwargs) -> dict:
    return await import_tax_records(parse_csv_tax_records(data), user.id, db, **kwargs)


async def _summary(db: AsyncSession, user: User, fy: str = "2024-25", jur: str = "IN"):
    return await generate_tax_summary(user.id, fy, jur, db)


# ---------------------------------------------------------------------------
# Idempotence — the core invariant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tax_record_import_is_idempotent(db: AsyncSession):
    """Re-uploading the same file creates nothing and leaves the FY untouched."""
    user = await _make_user(db)

    first = await _import(db, user, TAX_CSV)
    assert first["tax_records_created"] == 2
    assert first["tax_records_skipped"] == 0

    second = await _import(db, user, TAX_CSV)
    assert second["tax_records_created"] == 0
    assert second["tax_records_skipped"] == 2
    assert second["tax_records_updated"] == 0

    # A third upload is still a no-op.
    third = await _import(db, user, TAX_CSV)
    assert third["tax_records_created"] == 0
    assert third["tax_records_skipped"] == 2

    summary = await _summary(db, user)
    assert summary["records_count"] == 2
    assert summary["total_stcg"] == 8000.0
    assert summary["total_ltcg"] == 10000.0
    assert summary["total_tax"] == 2850.0


@pytest.mark.asyncio
async def test_skipped_rows_are_reported_not_silent(db: AsyncSession):
    """The response names what was dropped, so a repeat import is visible."""
    user = await _make_user(db)
    await _import(db, user, TAX_CSV)

    result = await _import(db, user, TAX_CSV)
    detail = result["tax_records_skipped_detail"]

    assert len(detail) == 2
    assert any("LTCG" in line and "2024-08-20" in line for line in detail)
    assert any("STCG" in line and "2024-09-10" in line for line in detail)
    assert all("already imported" in line for line in detail)


@pytest.mark.asyncio
async def test_tax_record_reimport_does_not_duplicate_itr_export(db: AsyncSession):
    """The ITR artefact must list each disposal exactly once after a re-upload."""
    user = await _make_user(db)
    await _import(db, user, TAX_CSV)
    await _import(db, user, TAX_CSV)

    csv_out = await export_tax_report_csv(user.id, "2024-25", "IN", db)

    assert csv_out.count("LTCG,2023-01-15,2024-08-20") == 1
    assert csv_out.count("STCG,2024-02-01,2024-09-10") == 1
    assert "Total Tax,2850.0" in csv_out
    assert "Records Count,2" in csv_out


@pytest.mark.asyncio
async def test_tax_record_upload_endpoint_idempotent(
    client: AsyncClient, auth_headers: dict[str, str]
):
    """Same thing through the HTTP upload the web/desktop app actually calls."""
    url = "/api/v1/import-export/csv/tax-records"
    files = {"file": ("tax.csv", TAX_CSV, "text/csv")}

    first = await client.post(url, files=files, headers=auth_headers)
    assert first.status_code == 200
    assert first.json()["tax_records_created"] == 2

    second = await client.post(
        url, files={"file": ("tax.csv", TAX_CSV, "text/csv")}, headers=auth_headers
    )
    assert second.status_code == 200
    body = second.json()
    assert body["tax_records_created"] == 0
    assert body["tax_records_skipped"] == 2
    assert len(body["tax_records_skipped_detail"]) == 2

    records = await client.get("/api/v1/tax/", headers=auth_headers)
    assert len(records.json()) == 2

    summary = await client.get(
        "/api/v1/tax/summary?financial_year=2024-25&jurisdiction=IN",
        headers=auth_headers,
    )
    assert summary.json()["total_tax"] == 2850.0
    assert summary.json()["records_count"] == 2


# ---------------------------------------------------------------------------
# What dedup must NOT swallow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_genuinely_duplicate_rows_are_both_kept(db: AsyncSession):
    """Two identical disposals in ONE file are two real sales, not a duplicate.

    Guards against the set-based form ``import_dividends`` uses, which collapses
    within-file duplicates: matching has to drain a multiset, not test set
    membership.
    """
    user = await _make_user(db)
    doubled = csv_bytes(ROW_A, ROW_A)

    first = await _import(db, user, doubled)
    assert first["tax_records_created"] == 2
    assert first["tax_records_skipped"] == 0

    summary = await _summary(db, user)
    assert summary["total_ltcg"] == 20000.0  # NOT 10000.0
    assert summary["total_tax"] == 2500.0
    assert summary["records_count"] == 2

    # Re-uploading that same file is still a no-op — both rows are accounted for.
    second = await _import(db, user, doubled)
    assert second["tax_records_created"] == 0
    assert second["tax_records_skipped"] == 2
    assert (await _summary(db, user))["total_ltcg"] == 20000.0


@pytest.mark.asyncio
async def test_changed_row_is_not_falsely_skipped(db: AsyncSession):
    """A row differing in proceeds/gain is a different disposal and must land."""
    user = await _make_user(db)
    await _import(db, user, csv_bytes(ROW_A, ROW_B))

    second = await _import(db, user, csv_bytes(ROW_A, ROW_B, ROW_C))
    assert second["tax_records_created"] == 1
    assert second["tax_records_skipped"] == 2

    summary = await _summary(db, user)
    assert summary["records_count"] == 3
    assert summary["total_ltcg"] == 21000.0
    assert summary["total_stcg"] == 8000.0
    assert summary["total_tax"] == 4225.0


@pytest.mark.asyncio
async def test_incremental_broker_export_superset(db: AsyncSession):
    """A month-2 statement that repeats month-1's rows imports only the new one."""
    user = await _make_user(db)

    first = await _import(db, user, csv_bytes(ROW_A))
    assert first["tax_records_created"] == 1

    second = await _import(db, user, csv_bytes(ROW_A, ROW_B))
    assert second["tax_records_created"] == 1
    assert second["tax_records_skipped"] == 1

    summary = await _summary(db, user)
    assert summary["records_count"] == 2
    assert summary["total_ltcg"] == 10000.0
    assert summary["total_stcg"] == 8000.0
    assert summary["total_tax"] == 2850.0


@pytest.mark.asyncio
async def test_allow_duplicates_bypasses_matching(db: AsyncSession):
    """The escape hatch for two brokers whose numbers genuinely coincide.

    The schema carries no symbol or quantity, so identical disposals from
    different statements are indistinguishable; without an override they would
    be a permanent data-entry dead end.
    """
    user = await _make_user(db)
    await _import(db, user, csv_bytes(ROW_A))

    forced = await _import(db, user, csv_bytes(ROW_A), allow_duplicates=True)
    assert forced["tax_records_created"] == 1
    assert forced["tax_records_skipped"] == 0

    summary = await _summary(db, user)
    assert summary["records_count"] == 2
    assert summary["total_ltcg"] == 20000.0


# ---------------------------------------------------------------------------
# Interaction with the FIFO engine's own records
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_imported_row_not_absorbed_by_engine_record(db: AsyncSession):
    """Matching is scoped to imported rows (``transaction_id IS NULL``).

    A CSV disposal whose economics happen to equal an engine-computed record
    must still be inserted.  Letting the engine record absorb it would drop a
    real disposal silently — and the engine deletes and rewrites its records on
    every recompute, so the imported one would vanish for good.
    """
    user = await _make_user(db)
    holding = await _make_holding(db, user)
    await _add_txn(
        db, holding, txn_type="BUY", txn_date=date(2022, 5, 1), quantity=100, price=1000
    )
    sell = await _add_txn(
        db,
        holding,
        txn_type="SELL",
        txn_date=date(2024, 11, 20),
        quantity=100,
        price=3000,
    )
    engine_records = await compute_tax_for_transaction(sell.id, user.id, db)
    assert len(engine_records) == 1
    assert float(engine_records[0].purchase_price) == 100000.0
    assert float(engine_records[0].sale_price) == 300000.0
    assert float(engine_records[0].gain_amount) == 200000.0

    # Another broker's statement, same numbers, arriving as CSV.
    other_broker = csv_bytes(
        "2024-25,IN,LTCG,2022-05-01,2024-11-20,100000.00,300000.00,200000.00,9375.00,INR"
    )
    result = await _import(db, user, other_broker)
    assert result["tax_records_created"] == 1
    assert result["tax_records_skipped"] == 0

    summary = await _summary(db, user)
    assert summary["records_count"] == 2
    assert summary["total_ltcg"] == 400000.0

    # Re-uploading that broker file is still idempotent.
    again = await _import(db, user, other_broker)
    assert again["tax_records_created"] == 0
    assert again["tax_records_skipped"] == 1
    assert (await _summary(db, user))["records_count"] == 2


@pytest.mark.asyncio
async def test_engine_recompute_does_not_drop_imported_row(db: AsyncSession):
    """Recomputing the in-app sale leaves the imported disposal in place."""
    user = await _make_user(db)
    holding = await _make_holding(db, user)
    await _add_txn(
        db, holding, txn_type="BUY", txn_date=date(2022, 5, 1), quantity=100, price=1000
    )
    sell = await _add_txn(
        db,
        holding,
        txn_type="SELL",
        txn_date=date(2024, 11, 20),
        quantity=100,
        price=3000,
    )
    await compute_tax_for_transaction(sell.id, user.id, db)
    await _import(
        db,
        user,
        csv_bytes(
            "2024-25,IN,LTCG,2022-05-01,2024-11-20,100000.00,300000.00,200000.00,9375.00,INR"
        ),
    )
    assert (await _summary(db, user))["records_count"] == 2

    # The user corrects a typo in the sale price and the engine recomputes.
    sell.price = 3100
    await db.flush()
    await compute_tax_for_transaction(sell.id, user.id, db)

    summary = await _summary(db, user)
    assert summary["records_count"] == 2
    assert summary["total_ltcg"] == 410000.0  # 210,000 engine + 200,000 imported

    imported = (
        await db.execute(
            select(TaxRecord).where(
                TaxRecord.user_id == user.id, TaxRecord.transaction_id.is_(None)
            )
        )
    ).scalars().all()
    assert len(imported) == 1
    assert float(imported[0].gain_amount) == 200000.0


# ---------------------------------------------------------------------------
# The money tests — allowances a phantom row would eat
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_import_does_not_eat_the_fy_ltcg_exemption(db: AsyncSession):
    """A double-imported row used to inflate a REAL sale's tax by Rs 3,125.

    s.112A gives Rs 1,25,000 of LTCG exemption per assessee per FY.  With the
    imported disposal counted once, Rs 1,00,000 of it is consumed, leaving
    Rs 25,000 against the engine-computed Rs 1,00,000 gain -> Rs 75,000 taxed at
    12.5% = Rs 9,375.  Counted twice, the exemption is exhausted and the same
    sale is taxed Rs 12,500.
    """
    user = await _make_user(db)
    imported = csv_bytes(
        "2024-25,IN,LTCG,2022-01-10,2024-06-10,400000.00,500000.00,100000.00,0.00,INR"
    )
    await _import(db, user, imported)
    second = await _import(db, user, imported)
    assert second["tax_records_created"] == 0
    assert second["tax_records_skipped"] == 1

    holding = await _make_holding(db, user)
    await _add_txn(
        db, holding, txn_type="BUY", txn_date=date(2022, 5, 1), quantity=100, price=1000
    )
    sell = await _add_txn(
        db,
        holding,
        txn_type="SELL",
        txn_date=date(2024, 11, 20),
        quantity=100,
        price=2000,
    )
    records = await compute_tax_for_transaction(sell.id, user.id, db)

    assert len(records) == 1
    assert float(records[0].gain_amount) == 100000.0
    assert float(records[0].tax_amount) == 9375.0  # not 12500.0

    assert (await _summary(db, user))["records_count"] == 2


@pytest.mark.asyncio
async def test_duplicate_de_import_does_not_consume_sparer_pauschbetrag(
    db: AsyncSession,
):
    """The EUR 1,000 saver's allowance is per year — a phantom row exhausts it."""
    user = await _make_user(db)
    german = csv_bytes(
        "2024,DE,ABGELTUNGSSTEUER,2023-03-01,2024-05-10,4000.00,4600.00,600.00,0.00,EUR"
    )
    await _import(db, user, german)
    second = await _import(db, user, german)
    assert second["tax_records_created"] == 0
    assert second["tax_records_skipped"] == 1

    allowance = await compute_german_allowance(user.id, "2024", db)
    assert allowance == {
        "total_allowance": 1000.0,
        "used": 600.0,
        "remaining": 400.0,
        "filing": "single",
    }


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_import_is_a_noop(db: AsyncSession):
    """No rows must not blow up on an empty ``IN ()`` preload."""
    user = await _make_user(db)
    result = await import_tax_records([], user.id, db)
    assert result["tax_records_created"] == 0
    assert result["tax_records_skipped"] == 0
    assert result["tax_records_updated"] == 0
    assert result["tax_records_skipped_detail"] == []


@pytest.mark.asyncio
async def test_open_position_row_without_sale_date_is_idempotent(db: AsyncSession):
    """A row with no sale (blank sale_date/price/gain) dedups on NULLs too."""
    user = await _make_user(db)
    open_row = csv_bytes("2024-25,IN,LTCG,2023-01-15,,25000.00,,,,INR")

    first = await _import(db, user, open_row)
    assert first["tax_records_created"] == 1

    second = await _import(db, user, open_row)
    assert second["tax_records_created"] == 0
    assert second["tax_records_skipped"] == 1

    stored = (
        await db.execute(select(TaxRecord).where(TaxRecord.user_id == user.id))
    ).scalars().all()
    assert len(stored) == 1
    assert stored[0].sale_date is None


@pytest.mark.asyncio
async def test_decimal_vs_float_fingerprint_matches_across_sessions():
    """Records read back as ``Decimal`` must fingerprint like the CSV's floats.

    The second import runs in a FRESH session, so the existing rows come back
    from the ``Numeric(18, 4)`` columns as ``Decimal('25000.1234')`` rather than
    the float the parser produced — including a 5-decimal value the column has
    to round.
    """
    precise = csv_bytes(
        "2024-25,IN,LTCG,2023-01-15,2024-08-20,25000.12345,35000.00,10000.12345,1250.00,INR",
        ROW_B,
    )

    async with TestSessionFactory() as session:
        user = await _make_user(session, email="decimal@example.com")
        user_id = user.id
        result = await import_tax_records(
            parse_csv_tax_records(precise), user_id, session
        )
        assert result["tax_records_created"] == 2
        await session.commit()

    async with TestSessionFactory() as session:
        result = await import_tax_records(
            parse_csv_tax_records(precise), user_id, session
        )
        assert result["tax_records_created"] == 0
        assert result["tax_records_skipped"] == 2
        await session.commit()

    async with TestSessionFactory() as session:
        rows = (
            await session.execute(
                select(TaxRecord).where(TaxRecord.user_id == user_id)
            )
        ).scalars().all()
        assert len(rows) == 2


@pytest.mark.asyncio
async def test_corrected_tax_figure_updates_without_duplicating_the_gain(
    db: AsyncSession,
):
    """``tax_amount`` is out of the key, so a reissued statement updates it.

    Including it would insert a second copy of the same gain; ignoring the
    correction outright would leave a wrong number in the ITR export, since
    ``generate_tax_summary`` totals the stored column straight up.
    """
    user = await _make_user(db)
    wrong = csv_bytes(
        "2024-25,IN,LTCG,2023-01-15,2024-08-20,25000.00,35000.00,10000.00,20000.00,INR"
    )
    corrected = csv_bytes(ROW_A)  # same gain, tax 1250.00

    await _import(db, user, wrong)
    assert (await _summary(db, user))["total_tax"] == 20000.0

    result = await _import(db, user, corrected)
    assert result["tax_records_created"] == 0
    assert result["tax_records_skipped"] == 1
    assert result["tax_records_updated"] == 1

    summary = await _summary(db, user)
    assert summary["records_count"] == 1
    assert summary["total_ltcg"] == 10000.0
    assert summary["total_tax"] == 1250.0


@pytest.mark.asyncio
async def test_blank_tax_column_does_not_wipe_a_stored_figure(db: AsyncSession):
    """A statement with no tax column must not null out what is already there."""
    user = await _make_user(db)
    await _import(db, user, csv_bytes(ROW_A))

    blank_tax = csv_bytes(
        "2024-25,IN,LTCG,2023-01-15,2024-08-20,25000.00,35000.00,10000.00,,INR"
    )
    result = await _import(db, user, blank_tax)
    assert result["tax_records_skipped"] == 1
    assert result["tax_records_updated"] == 0
    assert (await _summary(db, user))["total_tax"] == 1250.0


@pytest.mark.asyncio
async def test_fix_does_not_silently_repair_pre_existing_duplicates(db: AsyncSession):
    """Dedup prevents new damage; it does not clean up an already-doubled FY.

    Pinned deliberately: a user whose FY was doubled before this shipped sees
    "created 0, skipped 2" on their next upload while their totals stay wrong.
    Repair needs the rows deleted, not another import.
    """
    user = await _make_user(db)
    await _import(db, user, TAX_CSV)
    await _import(db, user, TAX_CSV, allow_duplicates=True)  # simulate the old bug

    damaged = await _summary(db, user)
    assert damaged["records_count"] == 4
    assert damaged["total_stcg"] == 16000.0
    assert damaged["total_ltcg"] == 20000.0
    assert damaged["total_tax"] == 5700.0

    result = await _import(db, user, TAX_CSV)
    assert result["tax_records_created"] == 0
    assert result["tax_records_skipped"] == 2

    still_damaged = await _summary(db, user)
    assert still_damaged["records_count"] == 4
    assert still_damaged["total_tax"] == 5700.0


@pytest.mark.asyncio
async def test_skipped_detail_is_capped_on_a_large_reupload(db: AsyncSession):
    """A 40-row re-upload reports a bounded list plus an "...and N more" line."""
    user = await _make_user(db)
    rows = [
        f"2024-25,IN,LTCG,2023-01-15,2024-08-20,{1000 + i}.00,{2000 + i}.00,1000.00,125.00,INR"
        for i in range(40)
    ]
    big = csv_bytes(*rows)

    assert (await _import(db, user, big))["tax_records_created"] == 40

    result = await _import(db, user, big)
    assert result["tax_records_created"] == 0
    assert result["tax_records_skipped"] == 40
    detail = result["tax_records_skipped_detail"]
    assert len(detail) == 26  # 25 rows + the "and N more" summary line
    assert detail[-1] == "...and 15 more skipped row(s)"
