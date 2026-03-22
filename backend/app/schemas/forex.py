"""Pydantic schemas for forex endpoints."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class ForexRateResponse(BaseModel):
    from_currency: str
    to_currency: str
    rate: float
    date: date
    source: str

    model_config = {"from_attributes": True}


class ConversionRequest(BaseModel):
    amount: float = Field(gt=0)
    from_currency: str = Field(min_length=3, max_length=10)
    to_currency: str = Field(min_length=3, max_length=10)


class ConversionResponse(BaseModel):
    original_amount: float
    from_currency: str
    to_currency: str
    converted_amount: float
    rate: float
    rate_date: date
