"""Aggregate all v1 API routes."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import (
    ai_chat,
    alerts,
    analytics,
    auth,
    backtest,
    broker,
    charts,
    columns,
    comparison,
    dividends,
    earnings,
    esg,
    fno,
    forex,
    goals,
    holdings,
    import_export,
    indicators,
    ipo,
    market_data,
    mutual_funds,
    net_worth,
    portfolio,
    tax,
    transactions,
    watchlist,
    whatif,
)
from app.api.v1 import settings as settings_routes

api_v1_router = APIRouter()

api_v1_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_v1_router.include_router(portfolio.router, prefix="/portfolios", tags=["Portfolios"])
api_v1_router.include_router(holdings.router, prefix="/holdings", tags=["Holdings"])
api_v1_router.include_router(transactions.router, prefix="/transactions", tags=["Transactions"])
api_v1_router.include_router(import_export.router, prefix="/import", tags=["Import/Export"])
api_v1_router.include_router(market_data.router, prefix="/market", tags=["Market Data"])
api_v1_router.include_router(charts.router, prefix="/charts", tags=["Charts"])
api_v1_router.include_router(alerts.router, prefix="/alerts", tags=["Alerts"])
api_v1_router.include_router(watchlist.router, prefix="/watchlist", tags=["Watchlist"])
api_v1_router.include_router(
    settings_routes.router, prefix="/settings", tags=["Settings"]
)
api_v1_router.include_router(tax.router, prefix="/tax", tags=["Tax"])
api_v1_router.include_router(dividends.router, prefix="/dividends", tags=["Dividends"])
api_v1_router.include_router(
    mutual_funds.router, prefix="/mutual-funds", tags=["Mutual Funds"]
)
api_v1_router.include_router(forex.router, prefix="/forex", tags=["Forex"])
api_v1_router.include_router(
    indicators.router, prefix="/indicators", tags=["Indicators & Risk"]
)
api_v1_router.include_router(broker.router, prefix="/broker", tags=["Broker"])
api_v1_router.include_router(ai_chat.router, prefix="/ai", tags=["AI & ML"])
api_v1_router.include_router(goals.router, prefix="/goals", tags=["Goals"])
api_v1_router.include_router(
    backtest.router, prefix="/backtest", tags=["Backtesting & Optimization"]
)
api_v1_router.include_router(
    comparison.router, prefix="/comparison", tags=["Comparison"]
)
api_v1_router.include_router(columns.router, prefix="/columns", tags=["Columns"])
api_v1_router.include_router(
    net_worth.router, prefix="/net-worth", tags=["Net Worth"]
)
api_v1_router.include_router(esg.router, prefix="/esg", tags=["ESG Scores"])
api_v1_router.include_router(whatif.router, prefix="/whatif", tags=["What-If Simulator"])
api_v1_router.include_router(
    earnings.router, prefix="/earnings", tags=["Earnings Calendar"]
)
api_v1_router.include_router(fno.router, prefix="/fno", tags=["F&O"])
api_v1_router.include_router(
    analytics.router, prefix="/analytics", tags=["Analytics"]
)
api_v1_router.include_router(ipo.router, prefix="/ipo", tags=["IPO Tracker"])
