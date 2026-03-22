"""Pydantic schemas for ESG scoring endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class StockESGScore(BaseModel):
    symbol: str
    total_esg: float | None = None
    environment_score: float | None = None
    social_score: float | None = None
    governance_score: float | None = None
    esg_available: bool = False


class PortfolioESGResponse(BaseModel):
    portfolio_id: int
    portfolio_name: str
    weighted_total_esg: float | None = None
    weighted_environment: float | None = None
    weighted_social: float | None = None
    weighted_governance: float | None = None
    holdings_with_esg: int = 0
    holdings_without_esg: int = 0
    stock_scores: list[StockESGScore]
