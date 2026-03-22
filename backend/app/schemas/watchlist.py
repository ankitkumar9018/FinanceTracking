"""Pydantic schemas for watchlist endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class WatchlistCreate(BaseModel):
    stock_symbol: str = Field(min_length=1, max_length=50)
    stock_name: str = Field(min_length=1, max_length=255)
    exchange: str = Field(min_length=1, max_length=20)
    target_buy_price: float | None = None
    lower_mid_range_1: float | None = None
    lower_mid_range_2: float | None = None
    upper_mid_range_1: float | None = None
    upper_mid_range_2: float | None = None
    base_level: float | None = None
    top_level: float | None = None
    notes: str | None = None


class WatchlistPatch(BaseModel):
    stock_name: str | None = None
    target_buy_price: float | None = None
    lower_mid_range_1: float | None = None
    lower_mid_range_2: float | None = None
    upper_mid_range_1: float | None = None
    upper_mid_range_2: float | None = None
    base_level: float | None = None
    top_level: float | None = None
    notes: str | None = None


class WatchlistResponse(BaseModel):
    id: int
    user_id: int
    stock_symbol: str
    stock_name: str
    exchange: str
    target_buy_price: float | None
    lower_mid_range_1: float | None
    lower_mid_range_2: float | None
    upper_mid_range_1: float | None
    upper_mid_range_2: float | None
    base_level: float | None
    top_level: float | None
    current_price: float | None
    current_rsi: float | None
    action_needed: str
    notes: str | None
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}
