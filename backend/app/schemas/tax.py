"""Pydantic schemas for tax endpoints."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class TaxRecordCreate(BaseModel):
    financial_year: str = Field(..., description="e.g. '2024-25' for India or '2024' for Germany")
    tax_jurisdiction: Literal["IN", "DE"]
    gain_type: Literal["STCG", "LTCG", "ABGELTUNGSSTEUER", "VORABPAUSCHALE"]
    purchase_date: date
    sale_date: date | None = None
    purchase_price: float = Field(gt=0)
    sale_price: float | None = None
    gain_amount: float | None = None
    tax_amount: float | None = None
    holding_period_days: int | None = None
    currency: str = Field(default="INR", max_length=10)
    transaction_id: int | None = None


class TaxRecordResponse(BaseModel):
    id: int
    user_id: int
    transaction_id: int | None
    financial_year: str
    tax_jurisdiction: str
    gain_type: str
    purchase_date: date
    sale_date: date | None
    purchase_price: float
    sale_price: float | None
    gain_amount: float | None
    tax_amount: float | None
    holding_period_days: int | None
    currency: str
    created_at: datetime

    model_config = {"from_attributes": True}


class TaxReportRequest(BaseModel):
    financial_year: str
    tax_jurisdiction: Literal["IN", "DE"]


class TaxSummary(BaseModel):
    financial_year: str
    tax_jurisdiction: str
    total_stcg: float
    total_ltcg: float
    total_tax: float
    exemption_used: float
    records_count: int


class TaxHarvestingSuggestion(BaseModel):
    holding_id: int
    stock_symbol: str
    unrealized_loss: float
    potential_tax_saving: float
    gain_type: str
