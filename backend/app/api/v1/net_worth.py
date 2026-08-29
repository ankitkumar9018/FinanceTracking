"""Net worth API — aggregate net worth across all asset types."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.asset import Asset
from app.models.user import User
from app.schemas.net_worth import AssetCreate, AssetResponse, NetWorthResponse
from app.services.net_worth_service import get_net_worth

router = APIRouter()


class AssetUpdate(BaseModel):
    """Partial update for a non-stock asset. Only the fields sent are changed.

    ``asset_type`` is deliberately NOT editable — it drives the net-worth
    grouping and the emergency-fund liquidity classification, so changing it
    would silently reclassify history.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    symbol: str | None = None
    quantity: float | None = Field(default=None, ge=0)
    purchase_price: float | None = Field(default=None, ge=0)
    current_value: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, max_length=10)
    interest_rate: float | None = None
    maturity_date: date | None = None
    notes: str | None = None


# ---------------------------------------------------------------------------
# Emergency-fund liquidity classification
# ---------------------------------------------------------------------------
# How readily each asset class can be turned into cash in an emergency:
#   * FIXED_DEPOSIT — redeemable/breakable for cash within days (premature-
#     withdrawal penalties aside), so treated as liquid.
#   * CRYPTO / GOLD  — traded on deep markets and convertible to cash quickly,
#     hence liquid / semi-liquid.
#   * STOCK          — sellable within the normal settlement window but exposed
#     to market-timing risk, so it is reported SEPARATELY (the "*_incl_stocks"
#     figures) rather than counted in the core liquid pool.
#   * BOND / REAL_ESTATE — illiquid (lock-ins, long settlement, months-long
#     sale timelines); excluded from emergency coverage entirely.
_LIQUID_ASSET_TYPES = frozenset({"FIXED_DEPOSIT", "CRYPTO", "GOLD"})
_SEMI_LIQUID_ASSET_TYPES = frozenset({"STOCK"})

# Asset columns that cannot be NULL — an explicit null in a PATCH body is
# dropped rather than written (which would fail the NOT NULL constraint).
_NON_NULLABLE_ASSET_FIELDS = frozenset(
    {"name", "quantity", "purchase_price", "current_value", "currency"}
)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/", response_model=NetWorthResponse)
async def total_net_worth(
    display_currency: str | None = Query(
        None,
        description=(
            "Optional currency override (e.g. INR/EUR/USD). When set, totals are "
            "converted into this currency for this response only; the user's "
            "stored preferred_currency is left unchanged. Defaults to the stored "
            "preference."
        ),
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get total net worth breakdown by asset type.

    Includes stocks (from portfolio holdings), crypto, gold, fixed deposits,
    bonds, and real estate.

    Valuation honesty: only STOCK (from live holdings) and CRYPTO / GOLD with a
    ticker symbol are marked to market. FIXED_DEPOSIT, BOND and REAL_ESTATE
    report the ``current_value`` the USER last entered — no interest is
    accrued and ``interest_rate`` / ``maturity_date`` are stored for reference
    only, never used in a calculation. Keep those values current with
    ``PATCH /net-worth/assets/{asset_id}``.
    """
    return await get_net_worth(user.id, db, display_currency=display_currency)


@router.get("/emergency-fund")
async def emergency_fund(
    monthly_expenses: float = Query(
        ...,
        description=(
            "Your estimated monthly living expenses, in the net-worth base "
            "currency. Used to compute how many months your liquid assets would "
            "cover. A value <= 0 returns a neutral state prompting for input."
        ),
    ),
    display_currency: str | None = Query(
        None,
        description=(
            "Optional currency override (same semantics as GET /net-worth): "
            "figures are converted into this currency for this response only, "
            "leaving the stored preference unchanged. Defaults to the "
            "preferred currency."
        ),
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Emergency-fund indicator — do liquid assets cover N months of expenses?

    Liquidity classification (see module-level notes for rationale):
      - Liquid: FIXED_DEPOSIT, CRYPTO, GOLD
      - Semi-liquid: STOCK (reported separately via the ``*_incl_stocks`` fields)
      - Illiquid: BOND, REAL_ESTATE (excluded)

    ``status`` is derived from the core liquid coverage (excluding stocks):
    ``critical`` < 3 months, ``adequate`` 3-6 months, ``strong`` > 6 months.
    When ``monthly_expenses`` <= 0 a neutral ``status`` of ``"unknown"`` is
    returned (with ``months_covered`` fields left ``null``) so the UI can prompt
    the user to enter their expenses. Values are already converted to the base
    currency by the net-worth service.
    """
    net_worth = await get_net_worth(user.id, db, display_currency=display_currency)

    liquid_value = 0.0
    stock_value = 0.0
    breakdown: list[dict] = []

    for item in net_worth.get("breakdown", []):
        asset_type = item["asset_type"]
        value = float(item.get("total_value", 0.0))
        is_liquid = asset_type in _LIQUID_ASSET_TYPES
        if is_liquid:
            liquid_value += value
        elif asset_type in _SEMI_LIQUID_ASSET_TYPES:
            stock_value += value
        breakdown.append(
            {
                "asset_type": asset_type,
                "value": round(value, 2),
                "liquid": is_liquid,
            }
        )

    liquid_incl_stocks = liquid_value + stock_value
    currency = net_worth.get("currency")

    if monthly_expenses <= 0:
        # Neutral state — prompt the user to enter their monthly expenses.
        return {
            "liquid_value": round(liquid_value, 2),
            "liquid_incl_stocks": round(liquid_incl_stocks, 2),
            "monthly_expenses": round(monthly_expenses, 2),
            "months_covered": None,
            "months_covered_incl_stocks": None,
            "status": "unknown",
            "currency": currency,
            "breakdown": breakdown,
        }

    months_covered = liquid_value / monthly_expenses
    months_covered_incl_stocks = liquid_incl_stocks / monthly_expenses

    if months_covered < 3:
        status_label = "critical"
    elif months_covered <= 6:
        status_label = "adequate"
    else:
        status_label = "strong"

    return {
        "liquid_value": round(liquid_value, 2),
        "liquid_incl_stocks": round(liquid_incl_stocks, 2),
        "monthly_expenses": round(monthly_expenses, 2),
        "months_covered": round(months_covered, 2),
        "months_covered_incl_stocks": round(months_covered_incl_stocks, 2),
        "status": status_label,
        "currency": currency,
        "breakdown": breakdown,
    }


@router.post("/assets", response_model=AssetResponse, status_code=status.HTTP_201_CREATED)
async def add_asset(
    body: AssetCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Asset:
    """Add a non-stock asset (crypto, gold, FD, bond, real estate).

    Stocks are automatically pulled from portfolio holdings — use this endpoint
    for other asset types.

    ``current_value`` for a fixed deposit / bond / property is user-maintained:
    nothing accrues it over time, so update it with
    ``PATCH /net-worth/assets/{asset_id}`` as the value changes. Crypto and gold
    with a ticker ``symbol`` are re-priced live on every net-worth read.
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


@router.patch("/assets/{asset_id}", response_model=AssetResponse)
async def update_asset(
    asset_id: int,
    body: AssetUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Asset:
    """Update a non-stock asset — chiefly its ``current_value``.

    Fixed deposits, bonds and property are NOT valued automatically: their
    ``current_value`` is whatever the user last entered (no interest accrual,
    and ``interest_rate`` / ``maturity_date`` are stored for reference only).
    This endpoint is how that stored value is kept honest. Crypto and gold with
    a ticker ``symbol`` are re-priced live and do not need it.

    Only the fields present in the request body are changed. ``asset_type`` is
    immutable — delete and re-add to reclassify. An explicit ``null`` for a
    non-nullable column (name / quantity / prices / currency) is ignored rather
    than blowing up the request; ``symbol``, ``interest_rate``,
    ``maturity_date`` and ``notes`` CAN be nulled to clear them.
    """
    result = await db.execute(
        select(Asset).where(Asset.id == asset_id, Asset.user_id == user.id)
    )
    asset = result.scalar_one_or_none()
    if asset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Asset not found or does not belong to the current user",
        )

    updates = {
        field: value
        for field, value in body.model_dump(exclude_unset=True).items()
        if value is not None or field not in _NON_NULLABLE_ASSET_FIELDS
    }
    if updates.get("name") is not None:
        updates["name"] = updates["name"].strip()
    if updates.get("symbol") is not None:
        updates["symbol"] = updates["symbol"].strip().upper() or None
    for field, value in updates.items():
        setattr(asset, field, value)

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
