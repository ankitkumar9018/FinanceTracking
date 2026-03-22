"""Dynamic column management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.models.user_preferences import UserPreferences

router = APIRouter()

BUILT_IN_COLUMNS = [
    {"name": "stock_symbol", "label": "Symbol", "type": "text", "removable": False},
    {"name": "stock_name", "label": "Name", "type": "text", "removable": False},
    {"name": "cumulative_quantity", "label": "Quantity", "type": "number", "removable": False},
    {"name": "average_price", "label": "Avg Price", "type": "number", "removable": False},
    {"name": "current_price", "label": "Current Price", "type": "number", "removable": False},
    {"name": "action_needed", "label": "Action", "type": "text", "removable": False},
    {"name": "current_rsi", "label": "RSI", "type": "number", "removable": False},
    {"name": "pnl_amount", "label": "P&L Amount", "type": "number", "removable": True},
    {"name": "pnl_percent", "label": "P&L %", "type": "number", "removable": True},
    {"name": "sector", "label": "Sector", "type": "text", "removable": True},
    {"name": "exchange", "label": "Exchange", "type": "text", "removable": True},
    {"name": "day_change", "label": "Day Change", "type": "number", "removable": True},
    {"name": "notes", "label": "Notes", "type": "text", "removable": True},
]


class CustomColumnCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50, pattern=r"^[a-z_][a-z0-9_]*$")
    label: str = Field(..., min_length=1, max_length=50)
    type: str = Field("text", pattern=r"^(text|number|date)$")


class ColumnOrderUpdate(BaseModel):
    column_order: list[str]


@router.get("/")
async def list_columns(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """List all available columns (built-in + custom) and current display order."""
    prefs = await _get_or_create_prefs(user.id, db)
    custom_columns = prefs.custom_columns or []
    column_order = prefs.column_order or [c["name"] for c in BUILT_IN_COLUMNS]

    return {
        "built_in": BUILT_IN_COLUMNS,
        "custom": custom_columns,
        "column_order": column_order,
    }


@router.post("/", status_code=201)
async def create_custom_column(
    body: CustomColumnCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Add a custom column definition."""
    # Check name doesn't conflict with built-in
    built_in_names = {c["name"] for c in BUILT_IN_COLUMNS}
    if body.name in built_in_names:
        raise HTTPException(400, detail=f"Column name '{body.name}' conflicts with a built-in column")

    prefs = await _get_or_create_prefs(user.id, db)
    custom = list(prefs.custom_columns or [])

    if any(c["name"] == body.name for c in custom):
        raise HTTPException(400, detail=f"Custom column '{body.name}' already exists")

    new_col = {"name": body.name, "label": body.label, "type": body.type}
    custom.append(new_col)
    prefs.custom_columns = custom

    # Add to column_order
    order = list(prefs.column_order or [c["name"] for c in BUILT_IN_COLUMNS])
    order.append(body.name)
    prefs.column_order = order

    await db.flush()
    return new_col


@router.delete("/{column_name}")
async def delete_custom_column(
    column_name: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove a custom column."""
    prefs = await _get_or_create_prefs(user.id, db)
    custom = list(prefs.custom_columns or [])

    original_len = len(custom)
    custom = [c for c in custom if c["name"] != column_name]
    if len(custom) == original_len:
        raise HTTPException(404, detail=f"Custom column '{column_name}' not found")

    prefs.custom_columns = custom
    order = [n for n in (prefs.column_order or []) if n != column_name]
    prefs.column_order = order

    await db.flush()
    return {"deleted": column_name}


@router.put("/order")
async def update_column_order(
    body: ColumnOrderUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the display order of columns."""
    prefs = await _get_or_create_prefs(user.id, db)
    prefs.column_order = body.column_order
    await db.flush()
    return {"column_order": body.column_order}


async def _get_or_create_prefs(user_id: int, db: AsyncSession) -> UserPreferences:
    """Get or create UserPreferences record."""
    result = await db.execute(
        select(UserPreferences).where(UserPreferences.user_id == user_id)
    )
    prefs = result.scalar_one_or_none()
    if prefs is None:
        prefs = UserPreferences(user_id=user_id)
        db.add(prefs)
        await db.flush()
    return prefs
