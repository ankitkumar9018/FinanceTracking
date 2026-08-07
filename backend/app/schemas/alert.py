"""Pydantic schemas for alert endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# One source of truth for valid values: a typo'd channel previously passed
# create/update untouched and the alert then silently never notified.
Channel = Literal["in_app", "email", "telegram", "whatsapp", "sms"]
AlertType = Literal["PRICE_RANGE", "RSI", "CUSTOM"]


def _default_channels() -> list[Channel]:
    return ["in_app"]


class AlertCreate(BaseModel):
    holding_id: int | None = None
    watchlist_item_id: int | None = None
    alert_type: AlertType = "PRICE_RANGE"
    condition: dict = Field(
        ...,
        description="Alert condition, e.g. {'above': 150.0} or {'rsi_above': 70}",
    )
    is_active: bool = True
    channels: list[Channel] = Field(default_factory=_default_channels)


class AlertUpdate(BaseModel):
    alert_type: AlertType | None = None
    condition: dict | None = None
    is_active: bool | None = None


class AlertChannelUpdate(BaseModel):
    channels: list[Channel] = Field(
        ...,
        description="List of notification channels: in_app, email, telegram, whatsapp, sms",
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
