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
    currency: str = "INR"
    quantity: float
    avg_price: float
    current_price: float | None
    action_needed: str
    rsi: float | None
    pnl_percent: float | None
    sector: str | None
    # Offset-aware ISO timestamp of the last successful quote (None = never
    # priced). Without this field the response_model silently dropped the
    # freshness value the service now emits.
    last_price_update: str | None = None
    # The 5-zone levels. The service computes and emits these, but they were
    # absent here, so the response_model silently stripped them and the stock
    # detail panel rendered "—" for every zone plus an empty 52-week bar.
    base_level: float | None = None
    top_level: float | None = None
    lower_mid_range_1: float | None = None
    lower_mid_range_2: float | None = None
    upper_mid_range_1: float | None = None
    upper_mid_range_2: float | None = None
    # Converted values, present only when ?display_currency= was requested AND
    # every needed FX rate resolved. Computed by _add_display_currency; they
    # were being stripped here, which is why the market heatmap and any
    # per-row converted display had nothing to work with.
    invested_display: float | None = None
    current_value_display: float | None = None

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
    # Display-currency conversion (absent unless ?display_currency= was passed
    # and all rates resolved — the endpoint stays all-or-nothing).
    display_currency: str | None = None
    display_base_currency: str | None = None
    display_fx_rate: float | None = None
    total_invested_display: float | None = None
    total_current_value_display: float | None = None
    total_pnl_percent_display: float | None = None
