"""Forex rate and conversion endpoints."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.forex import ConversionRequest, ConversionResponse, ForexRateResponse
from app.services.forex_service import convert_amount, get_exchange_rate, get_rate_history

router = APIRouter()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/rate", response_model=ForexRateResponse)
async def current_rate(
    from_currency: str = Query(..., description="Source currency, e.g. EUR"),
    to_currency: str = Query(..., description="Target currency, e.g. INR"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get the current exchange rate for a currency pair."""
    today = date.today()
    try:
        rate = await get_exchange_rate(from_currency, to_currency, today, db)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc

    return {
        "from_currency": from_currency.upper(),
        "to_currency": to_currency.upper(),
        "rate": rate,
        "date": today,
        "source": "yfinance",
    }


@router.post("/convert", response_model=ConversionResponse)
async def convert(
    body: ConversionRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Convert an amount between two currencies."""
    try:
        result = await convert_amount(
            amount=body.amount,
            from_currency=body.from_currency,
            to_currency=body.to_currency,
            db=db,
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    return result


@router.get("/history")
async def rate_history(
    from_currency: str = Query(..., description="Source currency, e.g. EUR"),
    to_currency: str = Query(..., description="Target currency, e.g. INR"),
    days: int = Query(default=30, ge=1, le=365, description="Number of days of history"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get exchange rate history for a currency pair over the last N days."""
    history = await get_rate_history(from_currency, to_currency, days, db)
    return {
        "from_currency": from_currency.upper(),
        "to_currency": to_currency.upper(),
        "days": days,
        "rates": history,
    }
