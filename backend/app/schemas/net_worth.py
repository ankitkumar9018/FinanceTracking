"""Pydantic schemas for net worth endpoints."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class AssetType(str, Enum):
    STOCK = "STOCK"
    CRYPTO = "CRYPTO"
    GOLD = "GOLD"
    FIXED_DEPOSIT = "FIXED_DEPOSIT"
    BOND = "BOND"
    REAL_ESTATE = "REAL_ESTATE"


class AssetCreate(BaseModel):
    asset_type: AssetType
    name: str = Field(min_length=1, max_length=255)
    symbol: str | None = None  # e.g. BTC-USD, ETH-USD, GC=F
    quantity: float = Field(default=0, ge=0)
    purchase_price: float = Field(default=0, ge=0)
    current_value: float = Field(default=0, ge=0)
    currency: str = Field(default="INR", max_length=10)
    interest_rate: float | None = None
    maturity_date: date | None = None
    notes: str | None = None


class AssetResponse(BaseModel):
    id: int
    user_id: int
    asset_type: str
    name: str
    symbol: str | None
    quantity: float
    purchase_price: float
    current_value: float
    currency: str
    interest_rate: float | None
    maturity_date: date | None
    notes: str | None
    created_at: datetime
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class AssetTypeBreakdown(BaseModel):
    asset_type: str
    total_value: float
    count: int
    items: list[dict]


class NetWorthResponse(BaseModel):
    total_net_worth: float
    breakdown: list[AssetTypeBreakdown]
    currency: str
