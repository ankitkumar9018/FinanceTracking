"""IPO tracker endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_current_user
from app.models.user import User
from app.services.ipo_service import get_ipos

router = APIRouter()


@router.get("")
async def list_ipos(
    status: str | None = Query(None, description="Filter by: upcoming, open, listed"),
    exchange: str = Query("NSE", description="Exchange: NSE, BSE, XETRA"),
    _user: User = Depends(get_current_user),
) -> dict:
    """Return IPO listings filtered by status and exchange.

    Returns an empty list if no IPO data is available from upstream sources.
    """
    ipos = await get_ipos(status=status, exchange=exchange)
    return {"ipos": ipos, "count": len(ipos)}
