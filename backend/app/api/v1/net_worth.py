"""Net worth API — aggregate net worth across all asset types."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.asset import Asset
from app.models.user import User
from app.schemas.net_worth import AssetCreate, AssetResponse, NetWorthResponse
from app.services.net_worth_service import get_net_worth

router = APIRouter()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/", response_model=NetWorthResponse)
async def total_net_worth(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get total net worth breakdown by asset type.

    Includes stocks (from portfolio holdings), crypto, gold, fixed deposits,
    bonds, and real estate.
    """
    return await get_net_worth(user.id, db)


@router.post("/assets", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
async def add_asset(
    body: AssetCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Asset:
    """Add a non-stock asset (crypto, gold, FD, bond, real estate).

    Stocks are automatically pulled from portfolio holdings — use this endpoint
    for other asset types.
    """
    if body.asset_type == "STOCK":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Stock assets are tracked via portfolio holdings. Use /holdings to add stocks.",
        )

    asset = Asset(
        user_id=user.id,
        asset_type=body.asset_type.value,
        name=body.name.strip(),
        symbol=body.symbol.strip().upper() if body.symbol else None,
        quantity=body.quantity,
        purchase_price=body.purchase_price,
        current_value=body.current_value,
        currency=body.currency,
        interest_rate=body.interest_rate,
        maturity_date=body.maturity_date,
        notes=body.notes,
    )

    db.add(asset)
    await db.flush()
    await db.refresh(asset)
    return asset


@router.delete("/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_asset(
    asset_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a non-stock asset by ID."""
    from sqlalchemy import select

    result = await db.execute(
        select(Asset).where(Asset.id == asset_id, Asset.user_id == user.id)
    )
    asset = result.scalar_one_or_none()
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Asset not found or does not belong to the current user",
        )

    await db.delete(asset)
    await db.flush()
