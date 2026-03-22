"""Pydantic schemas for holding endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class HoldingCreate(BaseModel):
    portfolio_id: int
    stock_symbol: str = Field(min_length=1, max_length=50)
    stock_name: str = Field(min_length=1, max_length=255)
    exchange: str = Field(min_length=1, max_length=20)  # NSE / BSE / XETRA
    cumulative_quantity: float = Field(default=0.0, ge=0)
    average_price: float = Field(default=0.0, ge=0)
    lower_mid_range_1: float | None = None
    lower_mid_range_2: float | None = None
    upper_mid_range_1: float | None = None
    upper_mid_range_2: float | None = None
    base_level: float | None = None
    top_level: float | None = None
    currency: str = Field(default="INR", max_length=10)
    sector: str | None = None
    notes: str | None = None
    custom_fields: dict | None = None


class HoldingPatch(BaseModel):
    """Partial update — any field can be changed inline."""

    stock_name: str | None = None
    exchange: str | None = None
    currency: str | None = None
    cumulative_quantity: float | None = None
    average_price: float | None = None
    lower_mid_range_1: float | None = None
    lower_mid_range_2: float | None = None
    upper_mid_range_1: float | None = None
    upper_mid_range_2: float | None = None
    base_level: float | None = None
    top_level: float | None = None
    sector: str | None = None
    notes: str | None = None
    custom_fields: dict | None = None


class HoldingResponse(BaseModel):
    id: int
    portfolio_id: int
    stock_symbol: str
    stock_name: str
    exchange: str
    currency: str
    cumulative_quantity: float
    average_price: float
    lower_mid_range_1: float | None
    lower_mid_range_2: float | None
    upper_mid_range_1: float | None
    upper_mid_range_2: float | None
    base_level: float | None
    top_level: float | None
    current_price: float | None
    current_rsi: float | None
    action_needed: str
    custom_fields: dict
    notes: str | None
    sector: str | None
    last_price_update: datetime | None
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}
