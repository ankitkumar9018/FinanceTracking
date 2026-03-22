"""Pydantic schemas for portfolio endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class PortfolioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    currency: str = Field(default="INR", max_length=10)
    is_default: bool = False


class PortfolioUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    currency: str | None = Field(default=None, max_length=10)
    is_default: bool | None = None


class PortfolioResponse(BaseModel):
    id: int
    user_id: int
    name: str
    description: str | None
    currency: str
    is_default: bool
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class HoldingSummaryRow(BaseModel):
    """One row in the main portfolio summary output table."""

    holding_id: int
    stock_symbol: str
    stock_name: str
    exchange: str
    quantity: float
    avg_price: float
    current_price: float | None
    action_needed: str
    rsi: float | None
    pnl_percent: float | None
    sector: str | None

    model_config = {"from_attributes": True}


class PortfolioSummaryResponse(BaseModel):
    """The main output table for a portfolio."""

    portfolio_id: int
    portfolio_name: str
    currency: str
    total_invested: float
    total_current_value: float
    total_pnl_percent: float | None
    holdings: list[HoldingSummaryRow]
