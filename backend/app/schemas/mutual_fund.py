"""Pydantic schemas for mutual fund endpoints."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class MutualFundCreate(BaseModel):
    portfolio_id: int
    scheme_code: str = Field(min_length=1, max_length=50)
    scheme_name: str = Field(min_length=1, max_length=255)
    folio_number: str | None = None
    units: float = Field(gt=0)
    nav: float = Field(gt=0)
    invested_amount: float = Field(gt=0)


class MutualFundUpdate(BaseModel):
    scheme_name: str | None = None
    units: float | None = None
    nav: float | None = None
    invested_amount: float | None = None
    current_value: float | None = None


class MutualFundResponse(BaseModel):
    id: int
    portfolio_id: int
    scheme_code: str
    scheme_name: str
    folio_number: str | None
    units: float
    nav: float
    invested_amount: float
    current_value: float | None
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class MutualFundSummary(BaseModel):
    total_invested: float
    total_current_value: float
    total_gain: float
    gain_percent: float | None
    xirr: float | None
    fund_count: int
