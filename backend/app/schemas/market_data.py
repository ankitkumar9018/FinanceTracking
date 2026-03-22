"""Pydantic schemas for market data endpoints."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class QuoteResponse(BaseModel):
    symbol: str
    exchange: str
    current_price: float
    open: float | None = None
    high: float | None = None
    low: float | None = None
    volume: int | None = None
    previous_close: float | None = None
    change: float | None = None
    change_percent: float | None = None


class OHLCVRow(BaseModel):
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int


class HistoryResponse(BaseModel):
    symbol: str
    exchange: str
    data: list[OHLCVRow]


class RSIRow(BaseModel):
    date: date
    close: float
    rsi: float | None


class RSIResponse(BaseModel):
    symbol: str
    exchange: str
    period: int
    data: list[RSIRow]
