"""Corporate-actions endpoints — detect and apply splits/bonuses.

All endpoints are auth-scoped; ownership is verified inside the service via
holding -> portfolio -> user.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.corporate_actions_service import (
    apply_corporate_action,
    detect_corporate_actions,
    dismiss_corporate_action,
    list_corporate_actions,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _map_value_error(exc: ValueError) -> HTTPException:
    """Translate a service ValueError into a 404 (not found) or 400 (state)."""
    message = str(exc)
    code = (
        status.HTTP_404_NOT_FOUND
        if "not found" in message.lower()
        else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(status_code=code, detail=message)


@router.post("/detect")
async def detect(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Scan all of the user's holdings for new splits/bonuses via yfinance.

    Records any newly found action as DETECTED and returns the full pending
    (DETECTED) list. Best-effort: unreachable tickers are skipped silently.
    """
    return await detect_corporate_actions(user.id, db)


@router.get("/")
async def list_actions(
    status_filter: str | None = Query(
        default=None,
        alias="status",
        description="Filter by status: DETECTED / APPLIED / DISMISSED",
    ),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List the user's corporate actions, optionally filtered by status."""
    actions = await list_corporate_actions(user.id, db, status_filter=status_filter)
    return {"count": len(actions), "actions": actions}


@router.post("/{action_id}/apply")
async def apply_action(
    action_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Apply a detected split/bonus, adjusting the holding's quantity and
    average price (idempotent)."""
    try:
        return await apply_corporate_action(action_id, user.id, db)
    except ValueError as exc:
        raise _map_value_error(exc)


@router.post("/{action_id}/dismiss")
async def dismiss_action(
    action_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Dismiss a detected corporate action without adjusting the holding."""
    try:
        return await dismiss_corporate_action(action_id, user.id, db)
    except ValueError as exc:
        raise _map_value_error(exc)
