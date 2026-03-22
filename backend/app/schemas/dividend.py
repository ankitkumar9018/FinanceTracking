"""Pydantic schemas for dividend endpoints."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, model_validator


class DividendCreate(BaseModel):
    holding_id: int
    ex_date: date
    payment_date: date | None = None
    amount_per_share: float = Field(gt=0)
    total_amount: float = Field(gt=0)
    is_reinvested: bool = False
    reinvest_price: float | None = None
    reinvest_shares: float | None = None

    @model_validator(mode="after")
    def _validate_drip_fields(self) -> "DividendCreate":
        if self.is_reinvested:
            if self.reinvest_price is None or self.reinvest_price <= 0:
                raise ValueError("reinvest_price is required and must be > 0 when is_reinvested is True")
            if self.reinvest_shares is None or self.reinvest_shares <= 0:
                raise ValueError("reinvest_shares is required and must be > 0 when is_reinvested is True")
        return self


class DividendResponse(BaseModel):
    id: int
    holding_id: int
    ex_date: date
    payment_date: date | None
    amount_per_share: float
    total_amount: float
    is_reinvested: bool
    reinvest_price: float | None
    reinvest_shares: float | None
    created_at: datetime
    holding_symbol: str | None = None
    holding_name: str | None = None

    model_config = {"from_attributes": True}


class DividendSummary(BaseModel):
    total_dividends: float
    dividend_yield: float | None
    total_reinvested: float
    count: int
    calendar: list[dict]
