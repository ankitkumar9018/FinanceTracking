"""SQLAlchemy models — import all models here so Alembic can discover them."""

from app.models.alert import Alert
from app.models.app_settings import AppSetting
from app.models.asset import Asset
from app.models.broker_connection import BrokerConnection
from app.models.chat_session import ChatSession
from app.models.dividend import Dividend
from app.models.fno_position import FnoPosition
from app.models.forex_rates import ForexRate
from app.models.goal import Goal
from app.models.holding import Holding
from app.models.mutual_fund import MutualFund
from app.models.notification_log import NotificationLog
from app.models.portfolio import Portfolio
from app.models.price_history import PriceHistory
from app.models.tax_record import TaxRecord
from app.models.transaction import Transaction
from app.models.user import User
from app.models.user_preferences import UserPreferences
from app.models.watchlist import WatchlistItem

__all__ = [
    "Alert",
    "AppSetting",
    "Asset",
    "BrokerConnection",
    "ChatSession",
    "Dividend",
    "FnoPosition",
    "ForexRate",
    "Goal",
    "Holding",
    "MutualFund",
    "NotificationLog",
    "Portfolio",
    "PriceHistory",
    "TaxRecord",
    "Transaction",
    "User",
    "UserPreferences",
    "WatchlistItem",
]
