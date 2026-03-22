"""Mutual fund management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.mutual_fund import (
    MutualFundCreate,
    MutualFundResponse,
    MutualFundSummary,
    MutualFundUpdate,
)
from app.services.mutual_fund_service import (
    create_mutual_fund,
    delete_mutual_fund,
    get_mf_summary,
    list_mutual_funds,
    refresh_all_navs,
    search_schemes,
    update_mutual_fund,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/", response_model=list[MutualFundResponse])
async def list_mutual_funds_endpoint(
    portfolio_id: int | None = Query(default=None, description="Filter by portfolio"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list:
    """List mutual funds for the current user, optionally filtered by portfolio_id."""
    return await list_mutual_funds(portfolio_id=portfolio_id, user_id=user.id, db=db)


@router.post("/", response_model=MutualFundResponse, status_code=status.HTTP_201_CREATED)
async def create_mutual_fund_endpoint(
    body: MutualFundCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> object:
    """Add a new mutual fund to a portfolio.

    Automatically fetches the latest NAV from mfapi.in and computes
    the current_value if available.
    """
    try:
        return await create_mutual_fund(data=body, user_id=user.id, db=db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )


@router.put("/{fund_id}", response_model=MutualFundResponse)
async def update_mutual_fund_endpoint(
    fund_id: int,
    body: MutualFundUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> object:
    """Update a mutual fund's details."""
    try:
        return await update_mutual_fund(
            fund_id=fund_id, user_id=user.id, data=body, db=db
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )


@router.delete("/{fund_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_mutual_fund_endpoint(
    fund_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a mutual fund record."""
    try:
        await delete_mutual_fund(fund_id=fund_id, user_id=user.id, db=db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )


@router.get("/summary", response_model=MutualFundSummary)
async def mf_summary_endpoint(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a mutual fund summary for the current user."""
    return await get_mf_summary(user_id=user.id, db=db)


@router.post("/refresh")
async def refresh_navs_endpoint(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Refresh NAVs for all of the current user's mutual funds from mfapi.in."""
    return await refresh_all_navs(user_id=user.id, db=db)


@router.get("/search")
async def search_schemes_endpoint(
    q: str = Query(min_length=2, description="Search query for scheme names"),
    user: User = Depends(get_current_user),
) -> list[dict]:
    """Search mutual fund schemes by name on mfapi.in."""
    return await search_schemes(query=q)
