"""Pydantic schemas for earnings calendar endpoints."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class StockEarnings(BaseModel):
    symbol: str
    earnings_date: date | None = None
    earnings_dates: list[date] = []
    revenue_estimate: float | None = None
    earnings_estimate: float | None = None
    data_available: bool = False


class PortfolioEarningsResponse(BaseModel):
    portfolio_id: int
    portfolio_name: str
    upcoming_earnings: list[StockEarnings]
    total_holdings: int
    holdings_with_data: int
