"""User preferences access helpers shared across route modules."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_preferences import UserPreferences


async def get_or_create_preferences(
    user_id: int,
    db: AsyncSession,
) -> UserPreferences:
    """Fetch (or lazily create) the user's ``UserPreferences`` row."""
    result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == user_id)
    )
    prefs = result.scalar_one_or_none()
    if prefs is None:
        prefs = UserPreferences(user_id=user_id)
        db.add(prefs)
        await db.flush()
    return prefs
