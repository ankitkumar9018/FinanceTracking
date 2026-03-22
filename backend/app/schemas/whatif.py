"""Pydantic schemas for what-if simulator endpoints."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class WhatIfRequest(BaseModel):
    symbol: str = Field(min_length=1, max_length=50)
    exchange: str = Field(default="NSE", max_length=20)
    invest_amount: float = Field(gt=0)
    start_date: date
    end_date: date | None = None  # defaults to today
    benchmark: str | None = None  # NIFTY50, SENSEX, DAX — optional comparison


class BenchmarkComparison(BaseModel):
    benchmark_name: str
    benchmark_start_price: float
    benchmark_end_price: float
    benchmark_return_pct: float


class WhatIfResponse(BaseModel):
    symbol: str
    exchange: str
    invest_amount: float
    start_date: date
    end_date: date
    buy_price: float
    end_price: float
    shares_bought: float
    current_value: float
    absolute_return: float
    percentage_return: float
    annualized_return: float | None = None
    holding_period_days: int
    benchmark: BenchmarkComparison | None = None
