# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for FinanceTracker backend sidecar.

Build with:  pyinstaller financetracker.spec
Output:      dist/financetracker-backend
"""

import platform
import sys
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None
root = Path(SPECPATH)

# Ensure the backend root is on sys.path so collect_submodules can find 'app'
sys.path.insert(0, str(root))
os.chdir(str(root))

# Collect all submodules — do NOT swallow errors silently
app_hiddenimports = collect_submodules("app")
uvicorn_hiddenimports = collect_submodules("uvicorn")

# Include the venv site-packages so PyInstaller can find all dependencies
# Windows uses .venv/Lib/site-packages, Unix uses .venv/lib/pythonX.Y/site-packages
if platform.system() == "Windows":
    venv_site = str(root / ".venv" / "Lib" / "site-packages")
else:
    venv_site = str(root / ".venv" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages")

a = Analysis(
    [str(root / "sidecar_entry.py")],
    pathex=[str(root), venv_site],
    binaries=[],
    datas=[
        # Include alembic config for DB migrations
        (str(root / "alembic.ini"), "."),
        (str(root / "alembic"), "alembic"),
    ],
    hiddenimports=[
        # --- Explicitly list ALL app subpackages (belt-and-suspenders) ---
        "app",
        "app.api",
        "app.api.deps",
        "app.api.v1",
        "app.api.v1.router",
        "app.api.v1.auth",
        "app.api.v1.portfolio",
        "app.api.v1.holdings",
        "app.api.v1.transactions",
        "app.api.v1.import_export",
        "app.api.v1.market_data",
        "app.api.v1.charts",
        "app.api.v1.alerts",
        "app.api.v1.watchlist",
        "app.api.v1.settings",
        "app.api.v1.tax",
        "app.api.v1.dividends",
        "app.api.v1.mutual_funds",
        "app.api.v1.forex",
        "app.api.v1.indicators",
        "app.api.v1.broker",
        "app.api.v1.ai_chat",
        "app.api.v1.goals",
        "app.api.v1.backtest",
        "app.api.v1.comparison",
        "app.api.v1.columns",
        "app.api.v1.net_worth",
        "app.api.v1.esg",
        "app.api.v1.whatif",
        "app.api.v1.earnings",
        "app.api.v1.fno",
        "app.api.v1.analytics",
        "app.api.v1.ipo",
        "app.api.ws",
        "app.api.ws.price_stream",
        "app.api.ws.alert_stream",
        "app.api.ws.connection_manager",
        "app.config",
        "app.database",
        "app.main",
        "app.models",
        "app.models.user",
        "app.models.portfolio",
        "app.models.holding",
        "app.models.transaction",
        "app.models.alert",
        "app.models.watchlist",
        "app.models.dividend",
        "app.models.mutual_fund",
        "app.models.tax_record",
        "app.models.price_history",
        "app.models.broker_connection",
        "app.models.notification_log",
        "app.models.user_preferences",
        "app.models.app_settings",
        "app.models.chat_session",
        "app.models.forex_rates",
        "app.models.goal",
        "app.models.asset",
        "app.models.fno_position",
        "app.schemas",
        "app.services",
        "app.services.portfolio_service",
        "app.services.market_data_service",
        "app.services.alert_service",
        "app.services.notification_service",
        "app.services.excel_service",
        "app.services.export_service",
        "app.services.csv_import_service",
        "app.services.backup_service",
        "app.services.tax_service",
        "app.services.dividend_service",
        "app.services.mutual_fund_service",
        "app.services.forex_service",
        "app.services.goal_service",
        "app.services.broker_service",
        "app.services.account_aggregator",
        "app.services.benchmark_service",
        "app.services.comparison_service",
        "app.services.stop_loss_service",
        "app.services.net_worth_service",
        "app.services.esg_service",
        "app.services.whatif_service",
        "app.services.earnings_service",
        "app.services.fno_service",
        "app.services.drift_service",
        "app.services.sector_rotation_service",
        "app.services.recurring_detection_service",
        "app.services.sip_calendar_service",
        "app.services.week52_service",
        "app.services.freshness_service",
        "app.services.sheets_export_service",
        "app.services.xirr_service",
        "app.services.ipo_service",
        "app.brokers",
        "app.brokers.base",
        "app.brokers.zerodha",
        "app.brokers.icici_direct",
        "app.brokers.groww",
        "app.brokers.angel_one",
        "app.brokers.upstox",
        "app.brokers.fivepaisa",
        "app.brokers.german",
        "app.brokers.german.deutsche_bank",
        "app.brokers.german.comdirect",
        "app.ml",
        "app.ml.technical_indicators",
        "app.ml.risk_calculator",
        "app.ml.backtester",
        "app.ml.portfolio_optimizer",
        "app.ml.price_predictor",
        "app.ml.anomaly_detector",
        "app.ml.sentiment_analyzer",
        "app.ml.llm_assistant",
        "app.tasks",
        "app.tasks.celery_app",
        "app.tasks.fetch_prices",
        "app.tasks.check_alerts",
        "app.tasks.scheduler",
        "app.utils",
        "app.utils.security",
        "app.utils.audit",
        "app.utils.rate_limiter",
        # --- uvicorn ---
        "uvicorn",
        "uvicorn.config",
        "uvicorn.main",
        "uvicorn.logging",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.loops.asyncio",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.http.h11_impl",
        "uvicorn.protocols.http.httptools_impl",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.protocols.websockets.wsproto_impl",
        "uvicorn.protocols.websockets.websockets_impl",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "uvicorn.lifespan.off",
        "uvicorn.server",
        # --- FastAPI + Starlette ---
        "fastapi",
        "starlette",
        "starlette.middleware",
        "starlette.middleware.cors",
        "starlette.responses",
        "starlette.routing",
        "anyio",
        "anyio._backends",
        "anyio._backends._asyncio",
        # --- async SQLite ---
        "aiosqlite",
        # --- FastAPI / Pydantic ---
        "email_validator",
        "multipart",
        "python_multipart",
        # --- SQLAlchemy ---
        "sqlalchemy",
        "sqlalchemy.dialects.sqlite",
        "sqlalchemy.ext.asyncio",
        # --- Data / Market ---
        "pandas",
        "yfinance",
        "pandas_ta",
        "openpyxl",
        "numpy",
        # --- Auth ---
        "passlib",
        "passlib.handlers",
        "passlib.handlers.bcrypt",
        "bcrypt",
        "jose",
        "jose.jwt",
        # --- HTTP ---
        "httptools",
        "httpx",
        "h11",
        "wsproto",
        "websockets",
        # --- Other ---
        "apscheduler",
        "pyotp",
        "slowapi",
        "cryptography",
        "sendgrid",
        "xhtml2pdf",
    ] + app_hiddenimports + uvicorn_hiddenimports,
    excludes=[
        # Exclude heavy ML dependencies (they degrade gracefully)
        "torch",
        "torchvision",
        "torchaudio",
        "sklearn",
        "scikit-learn",
        "transformers",
        "scipy",
        "tensorflow",
        "keras",
        # Exclude test/dev tools
        "pytest",
        "mypy",
        "ruff",
        "black",
        # Exclude unused GUI
        "tkinter",
        "matplotlib",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(root / "pyinstaller_runtime_hook.py")],
    cipher=block_cipher,
    noarchive=True,  # Extract .pyc to disk — fixes empty __init__.py namespace issues in PYZ
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="financetracker-backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=platform.system() != "Windows",  # Hide console on Windows to avoid flash
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
