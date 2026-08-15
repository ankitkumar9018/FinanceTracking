"""AI portfolio digest endpoints (on-demand generation + schedule preference).

Mounted at ``/ai/digest`` (see router.py). Storage lives in the user's
``notification_preferences`` JSON column — see ``ai_digest_service``.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.services.ai_digest_service import (
    generate_digest,
    get_digest_frequency,
    get_latest_digest,
    set_digest_frequency,
)

router = APIRouter()


class ScheduleBody(BaseModel):
    frequency: Literal["off", "daily", "weekly"]


@router.get("/")
async def latest_digest(user: User = Depends(get_current_user)) -> dict:
    """Return the latest stored digest, or 404 with a hint if none exists."""
    digest = get_latest_digest(user)
    if digest is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No digest generated yet. POST /api/v1/ai/digest/generate to "
                "create one, or PUT /api/v1/ai/digest/schedule to receive it "
                "daily or weekly."
            ),
        )
    return digest


@router.post("/generate")
async def generate_now(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Generate the digest now, store it as the latest, and return it."""
    return await generate_digest(user.id, db)


@router.get("/schedule")
async def get_schedule(user: User = Depends(get_current_user)) -> dict:
    """Return the user's digest schedule frequency (default "off")."""
    return {"frequency": get_digest_frequency(user)}


@router.put("/schedule")
async def set_schedule(
    body: ScheduleBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Set the digest schedule frequency: "off", "daily", or "weekly"."""
    set_digest_frequency(user, body.frequency)
    await db.flush()
    return {"frequency": body.frequency}
