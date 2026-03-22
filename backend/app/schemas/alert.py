"""Pydantic schemas for alert endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class AlertCreate(BaseModel):
    holding_id: int | None = None
    watchlist_item_id: int | None = None
    alert_type: Literal["PRICE_RANGE", "RSI", "CUSTOM"] = "PRICE_RANGE"
    condition: dict = Field(
        ...,
        description="Alert condition, e.g. {'above': 150.0} or {'rsi_above': 70}",
    )
    is_active: bool = True
    channels: list[str] = Field(default_factory=lambda: ["in_app"])


class AlertUpdate(BaseModel):
    alert_type: str | None = None
    condition: dict | None = None
    is_active: bool | None = None


class AlertChannelUpdate(BaseModel):
    channels: list[str] = Field(
        ...,
        description="List of notification channels: in_app, email, telegram, whatsapp",
    )


class AlertResponse(BaseModel):
    id: int
    user_id: int
    holding_id: int | None
    watchlist_item_id: int | None
    alert_type: str
    condition: dict
    is_active: bool
    last_triggered: datetime | None
    channels: list
    created_at: datetime

    model_config = {"from_attributes": True}


class AlertHistoryEntry(BaseModel):
    alert_id: int
    alert_type: str
    condition: dict
    triggered_at: datetime
    stock_symbol: str | None
    message: str
