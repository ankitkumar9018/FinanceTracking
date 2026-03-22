"""Pydantic schemas for transaction endpoints."""

from __future__ import annotations

import datetime as _dt
from typing import Literal, Optional

from pydantic import BaseModel, Field


class TransactionCreate(BaseModel):
    holding_id: int
    transaction_type: Literal["BUY", "SELL"]
    date: _dt.date
    quantity: float = Field(gt=0)
    price: float = Field(gt=0)
    brokerage: float = Field(default=0.0, ge=0)
    notes: str | None = None
    source: Literal["MANUAL", "EXCEL", "BROKER"] = "MANUAL"


class TransactionPatch(BaseModel):
    transaction_type: Literal["BUY", "SELL"] | None = None
    date: Optional[_dt.date] = None
    quantity: float | None = Field(default=None, gt=0)
    price: float | None = Field(default=None, gt=0)
    brokerage: float | None = Field(default=None, ge=0)
    notes: str | None = None


class TransactionResponse(BaseModel):
    id: int
    holding_id: int
    transaction_type: str
    date: _dt.date
    quantity: float
    price: float
    brokerage: float
    notes: str | None
    source: str
    created_at: _dt.datetime

    model_config = {"from_attributes": True}
