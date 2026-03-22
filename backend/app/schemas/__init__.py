"""Pydantic schemas — re-export for convenience."""

from app.schemas.alert import (
    AlertChannelUpdate,
    AlertCreate,
    AlertHistoryEntry,
    AlertResponse,
    AlertUpdate,
)
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.schemas.holding import HoldingCreate, HoldingPatch, HoldingResponse
from app.schemas.market_data import (
    HistoryResponse,
    OHLCVRow,
    QuoteResponse,
    RSIResponse,
    RSIRow,
)
from app.schemas.portfolio import (
    HoldingSummaryRow,
    PortfolioCreate,
    PortfolioResponse,
    PortfolioSummaryResponse,
    PortfolioUpdate,
)
from app.schemas.settings import (
    DisplaySettings,
    HealthStatus,
    IntegrationSettings,
    MarketSettings,
    NotificationSettings,
    SettingsUpdate,
    UserSettingsResponse,
)
from app.schemas.transaction import TransactionCreate, TransactionPatch, TransactionResponse
from app.schemas.dividend import DividendCreate, DividendResponse, DividendSummary
from app.schemas.forex import ConversionRequest, ConversionResponse, ForexRateResponse
from app.schemas.mutual_fund import (
    MutualFundCreate,
    MutualFundResponse,
    MutualFundSummary,
    MutualFundUpdate,
)
from app.schemas.tax import (
    TaxHarvestingSuggestion,
    TaxRecordCreate,
    TaxRecordResponse,
    TaxReportRequest,
    TaxSummary,
)
from app.schemas.broker import (
    BrokerConnectRequest,
    BrokerConnectionResponse,
    BrokerStatusResponse,
    BrokerSyncResponse,
)
from app.schemas.goal import GoalCreate, GoalResponse, GoalSummary, GoalUpdate
from app.schemas.watchlist import WatchlistCreate, WatchlistPatch, WatchlistResponse

__all__ = [
    # Auth
    "RegisterRequest",
    "LoginRequest",
    "RefreshRequest",
    "TokenResponse",
    "UserResponse",
    # Portfolio
    "PortfolioCreate",
    "PortfolioUpdate",
    "PortfolioResponse",
    "PortfolioSummaryResponse",
    "HoldingSummaryRow",
    # Holding
    "HoldingCreate",
    "HoldingPatch",
    "HoldingResponse",
    # Transaction
    "TransactionCreate",
    "TransactionPatch",
    "TransactionResponse",
    # Alert
    "AlertCreate",
    "AlertUpdate",
    "AlertChannelUpdate",
    "AlertResponse",
    "AlertHistoryEntry",
    # Watchlist
    "WatchlistCreate",
    "WatchlistPatch",
    "WatchlistResponse",
    # Market Data
    "QuoteResponse",
    "OHLCVRow",
    "HistoryResponse",
    "RSIRow",
    "RSIResponse",
    # Settings
    "UserSettingsResponse",
    "DisplaySettings",
    "NotificationSettings",
    "MarketSettings",
    "IntegrationSettings",
    "SettingsUpdate",
    "HealthStatus",
    # Tax
    "TaxRecordCreate",
    "TaxRecordResponse",
    "TaxReportRequest",
    "TaxSummary",
    "TaxHarvestingSuggestion",
    # Dividend
    "DividendCreate",
    "DividendResponse",
    "DividendSummary",
    # Mutual Fund
    "MutualFundCreate",
    "MutualFundUpdate",
    "MutualFundResponse",
    "MutualFundSummary",
    # Forex
    "ForexRateResponse",
    "ConversionRequest",
    "ConversionResponse",
    # Broker
    "BrokerConnectRequest",
    "BrokerConnectionResponse",
    "BrokerSyncResponse",
    "BrokerStatusResponse",
    # Goal
    "GoalCreate",
    "GoalUpdate",
    "GoalResponse",
    "GoalSummary",
]
