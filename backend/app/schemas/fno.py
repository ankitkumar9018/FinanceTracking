"""Pydantic schemas for F&O (Futures & Options) endpoints."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class InstrumentType(str, Enum):
    FUT = "FUT"
    CE = "CE"  # Call option
    PE = "PE"  # Put option


class PositionSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    EXPIRED = "EXPIRED"


class FnoPositionCreate(BaseModel):
    portfolio_id: int
    symbol: str = Field(min_length=1, max_length=50)
    exchange: str = Field(default="NSE", max_length=20)
    instrument_type: InstrumentType
    strike_price: float | None = None  # required for options, null for futures
    expiry_date: date
    lot_size: int = Field(gt=0)
    quantity: int = Field(gt=0, description="Number of lots")
    entry_price: float = Field(gt=0)
    side: PositionSide = PositionSide.BUY
    notes: str | None = None


class FnoPositionUpdate(BaseModel):
    exit_price: float | None = None
    current_price: float | None = None
    status: PositionStatus | None = None
    quantity: int | None = Field(default=None, gt=0)
    notes: str | None = None


class FnoPositionResponse(BaseModel):
    id: int
    portfolio_id: int
    symbol: str
    exchange: str
    instrument_type: str
    strike_price: float | None
    expiry_date: date
    lot_size: int
    quantity: int
    entry_price: float
    exit_price: float | None
    current_price: float | None
    side: str
    status: str
    notes: str | None
    created_at: datetime
    updated_at: datetime | None
    unrealized_pnl: float | None = None

    model_config = {"from_attributes": True}


class FnoPnlSummary(BaseModel):
    portfolio_id: int
    total_realized_pnl: float
    total_unrealized_pnl: float
    total_pnl: float
    open_positions: int
    closed_positions: int
    positions: list[FnoPositionResponse]
