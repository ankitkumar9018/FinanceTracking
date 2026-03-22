"""Dividend management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.dividend import DividendCreate, DividendResponse, DividendSummary
from app.services.dividend_service import (
    create_dividend,
    delete_dividend,
    get_dividend_summary,
    list_dividends,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[DividendResponse])
async def list_dividends_endpoint(
    holding_id: int | None = Query(default=None, description="Filter by holding"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list:
    """List dividends for the current user, optionally filtered by holding_id."""
    return await list_dividends(holding_id=holding_id, user_id=user.id, db=db)


@router.post("/", response_model=DividendResponse, status_code=status.HTTP_201_CREATED)
async def create_dividend_endpoint(
    body: DividendCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> object:
    """Record a new dividend payment.

    If ``is_reinvested`` is True and ``reinvest_shares`` is provided,
    the holding's cumulative_quantity and average_price will be updated
    to reflect the DRIP shares.
    """
    try:
        return await create_dividend(data=body, user_id=user.id, db=db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )


@router.get("/summary", response_model=DividendSummary)
async def dividend_summary_endpoint(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a dividend summary for the current user including yield and calendar."""
    return await get_dividend_summary(user_id=user.id, db=db)


@router.delete("/{dividend_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dividend_endpoint(
    dividend_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a dividend record.

    If the dividend was reinvested, the DRIP shares adjustment is reversed.
    """
    try:
        await delete_dividend(dividend_id=dividend_id, user_id=user.id, db=db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
