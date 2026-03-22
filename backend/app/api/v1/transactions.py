"""Transaction management endpoints."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.transaction import TransactionCreate, TransactionPatch, TransactionResponse
from app.services.portfolio_service import calculate_cumulative_holding

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _verify_holding_ownership(
    holding_id: int,
    user: User,
    db: AsyncSession,
) -> Holding:
    """Ensure the holding exists and belongs to one of the user's portfolios."""
    result = await db.execute(
        select(Holding)
        .join(Portfolio, Holding.portfolio_id == Portfolio.id)
        .where(Holding.id == holding_id, Portfolio.user_id == user.id)
    )
    holding = result.scalar_one_or_none()
    if holding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Holding not found or does not belong to the current user",
        )
    return holding


async def _get_user_transaction(
    transaction_id: int,
    user: User,
    db: AsyncSession,
) -> Transaction:
    """Fetch a transaction and verify it belongs to the user (via holding -> portfolio)."""
    result = await db.execute(
        select(Transaction)
        .join(Holding, Transaction.holding_id == Holding.id)
        .join(Portfolio, Holding.portfolio_id == Portfolio.id)
        .where(Transaction.id == transaction_id, Portfolio.user_id == user.id)
    )
    tx = result.scalar_one_or_none()
    if tx is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transaction not found",
        )
    return tx


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[TransactionResponse])
async def list_transactions(
    holding_id: int | None = Query(default=None, description="Filter by holding"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(200, ge=1, le=1000, description="Max records to return"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[Transaction]:
    """List transactions, optionally filtered by holding_id."""

    # Auto-backfill: if a specific holding has qty but no transactions, seed one
    if holding_id is not None:
        holding = await _verify_holding_ownership(holding_id, user, db)
        count_result = await db.execute(
            select(func.count()).select_from(Transaction).where(Transaction.holding_id == holding_id)
        )
        tx_count = count_result.scalar() or 0
        if tx_count == 0 and float(holding.cumulative_quantity) > 0:
            seed_tx = Transaction(
                holding_id=holding_id,
                transaction_type="BUY",
                date=holding.created_at.date() if holding.created_at else date.today(),
                quantity=float(holding.cumulative_quantity),
                price=float(holding.average_price),
                brokerage=0,
                source="MANUAL",
                notes="Auto-created from existing holding",
            )
            db.add(seed_tx)
            await db.flush()

    stmt = (
        select(Transaction)
        .join(Holding, Transaction.holding_id == Holding.id)
        .join(Portfolio, Holding.portfolio_id == Portfolio.id)
        .where(Portfolio.user_id == user.id)
    )
    if holding_id is not None:
        stmt = stmt.where(Transaction.holding_id == holding_id)

    stmt = stmt.order_by(Transaction.date.desc(), Transaction.id.desc()).offset(skip).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("/", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    body: TransactionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Transaction:
    """Add a buy or sell transaction.

    Automatically recalculates the holding's cumulative_quantity and
    average_price after the transaction is recorded.
    """
    holding = await _verify_holding_ownership(body.holding_id, user, db)

    # For SELL, validate that the user isn't selling more than they hold
    if body.transaction_type == "SELL":
        if body.quantity > float(holding.cumulative_quantity):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Cannot sell {body.quantity} units; "
                    f"only {float(holding.cumulative_quantity)} held"
                ),
            )

    tx = Transaction(
        holding_id=body.holding_id,
        transaction_type=body.transaction_type,
        date=body.date,
        quantity=body.quantity,
        price=body.price,
        brokerage=body.brokerage,
        notes=body.notes,
        source=body.source,
    )
    db.add(tx)
    await db.flush()
    await db.refresh(tx)

    # Recalculate holding cumulative values
    await calculate_cumulative_holding(body.holding_id, db)

    return tx


@router.get("/{transaction_id}", response_model=TransactionResponse)
async def get_transaction(
    transaction_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Transaction:
    """Get a single transaction by ID."""
    return await _get_user_transaction(transaction_id, user, db)


@router.patch("/{transaction_id}", response_model=TransactionResponse)
async def update_transaction(
    transaction_id: int,
    body: TransactionPatch,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Transaction:
    """Update a transaction and recalculate the holding's cumulative values."""
    tx = await _get_user_transaction(transaction_id, user, db)

    patch_data = body.model_dump(exclude_unset=True)
    for field, value in patch_data.items():
        setattr(tx, field, value)

    await db.flush()
    await db.refresh(tx)

    # Recalculate holding after modification
    await calculate_cumulative_holding(tx.holding_id, db)

    return tx


@router.delete("/{transaction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_transaction(
    transaction_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a transaction and recalculate the holding's cumulative values."""
    tx = await _get_user_transaction(transaction_id, user, db)
    holding_id = tx.holding_id

    await db.delete(tx)
    await db.flush()

    # Recalculate holding after removing the transaction
    await calculate_cumulative_holding(holding_id, db)
