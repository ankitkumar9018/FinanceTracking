"""PyInstaller entry point for FinanceTracker backend sidecar.

This wrapper forces PyInstaller to include every app module by importing
them explicitly. PyInstaller traces imports from the entry point file,
so listing them here guarantees they end up in the frozen binary.

Previous approaches (collect_submodules, hiddenimports, runtime hooks,
noarchive) all failed on Windows. Explicit imports are the nuclear option
that cannot fail — if Python can parse this file, the modules are included.
"""
import sys
import os

# Ensure the bundle root is on sys.path
base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
if base not in sys.path:
    sys.path.insert(0, base)

# ---------------------------------------------------------------------------
# Force-import every app subpackage so PyInstaller MUST include them.
# Without this, PyInstaller's analysis misses app.models on Windows.
# ---------------------------------------------------------------------------

# Core
import app  # noqa: F401, E402
import app.config  # noqa: F401, E402
import app.database  # noqa: F401, E402
import app.main  # noqa: F401, E402

# Models (the package that was failing)
import app.models  # noqa: F401, E402
import app.models.user  # noqa: F401, E402
import app.models.portfolio  # noqa: F401, E402
import app.models.holding  # noqa: F401, E402
import app.models.transaction  # noqa: F401, E402
import app.models.alert  # noqa: F401, E402
import app.models.watchlist  # noqa: F401, E402
import app.models.dividend  # noqa: F401, E402
import app.models.mutual_fund  # noqa: F401, E402
import app.models.tax_record  # noqa: F401, E402
import app.models.price_history  # noqa: F401, E402
import app.models.broker_connection  # noqa: F401, E402
import app.models.notification_log  # noqa: F401, E402
import app.models.user_preferences  # noqa: F401, E402
import app.models.app_settings  # noqa: F401, E402
import app.models.chat_session  # noqa: F401, E402
import app.models.forex_rates  # noqa: F401, E402
import app.models.goal  # noqa: F401, E402
import app.models.asset  # noqa: F401, E402
import app.models.fno_position  # noqa: F401, E402

# Schemas
import app.schemas  # noqa: F401, E402
import app.schemas.auth  # noqa: F401, E402
import app.schemas.holding  # noqa: F401, E402
import app.schemas.portfolio  # noqa: F401, E402
import app.schemas.transaction  # noqa: F401, E402
import app.schemas.alert  # noqa: F401, E402
import app.schemas.watchlist  # noqa: F401, E402
import app.schemas.dividend  # noqa: F401, E402
import app.schemas.mutual_fund  # noqa: F401, E402
import app.schemas.tax  # noqa: F401, E402
import app.schemas.forex  # noqa: F401, E402
import app.schemas.goal  # noqa: F401, E402
import app.schemas.broker  # noqa: F401, E402
import app.schemas.market_data  # noqa: F401, E402
import app.schemas.settings  # noqa: F401, E402
import app.schemas.net_worth  # noqa: F401, E402
import app.schemas.esg  # noqa: F401, E402
import app.schemas.whatif  # noqa: F401, E402
import app.schemas.earnings  # noqa: F401, E402
import app.schemas.fno  # noqa: F401, E402

# API
import app.api  # noqa: F401, E402
import app.api.deps  # noqa: F401, E402
import app.api.v1  # noqa: F401, E402
import app.api.v1.router  # noqa: F401, E402
import app.api.v1.auth  # noqa: F401, E402
import app.api.v1.portfolio  # noqa: F401, E402
import app.api.v1.holdings  # noqa: F401, E402
import app.api.v1.transactions  # noqa: F401, E402
import app.api.v1.import_export  # noqa: F401, E402
import app.api.v1.market_data  # noqa: F401, E402
import app.api.v1.charts  # noqa: F401, E402
import app.api.v1.alerts  # noqa: F401, E402
import app.api.v1.watchlist  # noqa: F401, E402
import app.api.v1.settings  # noqa: F401, E402
import app.api.v1.tax  # noqa: F401, E402
import app.api.v1.dividends  # noqa: F401, E402
import app.api.v1.mutual_funds  # noqa: F401, E402
import app.api.v1.forex  # noqa: F401, E402
import app.api.v1.indicators  # noqa: F401, E402
import app.api.v1.broker  # noqa: F401, E402
import app.api.v1.ai_chat  # noqa: F401, E402
import app.api.v1.goals  # noqa: F401, E402
import app.api.v1.backtest  # noqa: F401, E402
import app.api.v1.comparison  # noqa: F401, E402
import app.api.v1.columns  # noqa: F401, E402
import app.api.v1.net_worth  # noqa: F401, E402
import app.api.v1.esg  # noqa: F401, E402
import app.api.v1.whatif  # noqa: F401, E402
import app.api.v1.earnings  # noqa: F401, E402
import app.api.v1.fno  # noqa: F401, E402
import app.api.v1.analytics  # noqa: F401, E402
import app.api.v1.ipo  # noqa: F401, E402
import app.api.ws  # noqa: F401, E402
import app.api.ws.price_stream  # noqa: F401, E402
import app.api.ws.alert_stream  # noqa: F401, E402
import app.api.ws.connection_manager  # noqa: F401, E402

# Services
import app.services  # noqa: F401, E402
import app.services.portfolio_service  # noqa: F401, E402
import app.services.market_data_service  # noqa: F401, E402
import app.services.alert_service  # noqa: F401, E402
import app.services.notification_service  # noqa: F401, E402
import app.services.excel_service  # noqa: F401, E402
import app.services.export_service  # noqa: F401, E402
import app.services.csv_import_service  # noqa: F401, E402
import app.services.backup_service  # noqa: F401, E402
import app.services.tax_service  # noqa: F401, E402
import app.services.dividend_service  # noqa: F401, E402
import app.services.mutual_fund_service  # noqa: F401, E402
import app.services.forex_service  # noqa: F401, E402
import app.services.goal_service  # noqa: F401, E402
import app.services.broker_service  # noqa: F401, E402
import app.services.account_aggregator  # noqa: F401, E402
import app.services.benchmark_service  # noqa: F401, E402
import app.services.comparison_service  # noqa: F401, E402
import app.services.stop_loss_service  # noqa: F401, E402
import app.services.net_worth_service  # noqa: F401, E402
import app.services.esg_service  # noqa: F401, E402
import app.services.whatif_service  # noqa: F401, E402
import app.services.earnings_service  # noqa: F401, E402
import app.services.fno_service  # noqa: F401, E402
import app.services.drift_service  # noqa: F401, E402
import app.services.sector_rotation_service  # noqa: F401, E402
import app.services.recurring_detection_service  # noqa: F401, E402
import app.services.sip_calendar_service  # noqa: F401, E402
import app.services.week52_service  # noqa: F401, E402
import app.services.freshness_service  # noqa: F401, E402
import app.services.sheets_export_service  # noqa: F401, E402
import app.services.xirr_service  # noqa: F401, E402
import app.services.ipo_service  # noqa: F401, E402

# Brokers
import app.brokers  # noqa: F401, E402
import app.brokers.base  # noqa: F401, E402
import app.brokers.zerodha  # noqa: F401, E402
import app.brokers.icici_direct  # noqa: F401, E402
import app.brokers.groww  # noqa: F401, E402
import app.brokers.angel_one  # noqa: F401, E402
import app.brokers.upstox  # noqa: F401, E402
import app.brokers.fivepaisa  # noqa: F401, E402
import app.brokers.german  # noqa: F401, E402
import app.brokers.german.deutsche_bank  # noqa: F401, E402
import app.brokers.german.comdirect  # noqa: F401, E402

# ML (graceful degradation — these use try/except internally)
import app.ml  # noqa: F401, E402
import app.ml.technical_indicators  # noqa: F401, E402
import app.ml.risk_calculator  # noqa: F401, E402
import app.ml.backtester  # noqa: F401, E402
import app.ml.portfolio_optimizer  # noqa: F401, E402
import app.ml.price_predictor  # noqa: F401, E402
import app.ml.anomaly_detector  # noqa: F401, E402
import app.ml.sentiment_analyzer  # noqa: F401, E402
import app.ml.llm_assistant  # noqa: F401, E402

# Tasks
import app.tasks  # noqa: F401, E402
import app.tasks.celery_app  # noqa: F401, E402
import app.tasks.fetch_prices  # noqa: F401, E402
import app.tasks.check_alerts  # noqa: F401, E402
import app.tasks.scheduler  # noqa: F401, E402

# Utils
import app.utils  # noqa: F401, E402
import app.utils.security  # noqa: F401, E402
import app.utils.audit  # noqa: F401, E402
import app.utils.rate_limiter  # noqa: F401, E402

# ---------------------------------------------------------------------------
# Now run the actual entry point
# ---------------------------------------------------------------------------
from app.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
