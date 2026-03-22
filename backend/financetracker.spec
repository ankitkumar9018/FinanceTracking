# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for FinanceTracker backend sidecar.

Build with:  pyinstaller financetracker.spec
Output:      dist/financetracker-backend
"""

import platform
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules, collect_data_files

block_cipher = None
root = Path(SPECPATH)

# Collect all submodules of the app package (uvicorn.run uses string import)
app_hiddenimports = collect_submodules("app")
uvicorn_hiddenimports = collect_submodules("uvicorn")

import site
# Include the venv site-packages so PyInstaller can find all dependencies
# Windows uses .venv/Lib/site-packages, Unix uses .venv/lib/pythonX.Y/site-packages
if platform.system() == "Windows":
    venv_site = str(root / ".venv" / "Lib" / "site-packages")
else:
    venv_site = str(root / ".venv" / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages")

a = Analysis(
    [str(root / "app" / "__main__.py")],
    pathex=[str(root), venv_site],
    binaries=[],
    datas=[
        # Include alembic config for DB migrations
        (str(root / "alembic.ini"), "."),
        (str(root / "alembic"), "alembic"),
        # Include the entire app package as data (templates, etc.)
    ],
    hiddenimports=[
        # uvicorn — must include the package itself + internals
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
        # FastAPI + Starlette
        "fastapi",
        "starlette",
        "starlette.middleware",
        "starlette.middleware.cors",
        "starlette.responses",
        "starlette.routing",
        "anyio",
        "anyio._backends",
        "anyio._backends._asyncio",
        # async SQLite
        "aiosqlite",
        # FastAPI / Pydantic
        "email_validator",
        "multipart",
        "python_multipart",
        # SQLAlchemy dialects
        "sqlalchemy",
        "sqlalchemy.dialects.sqlite",
        "sqlalchemy.ext.asyncio",
        # Pandas / yfinance
        "pandas",
        "yfinance",
        "pandas_ta",
        # Auth
        "passlib",
        "passlib.handlers",
        "passlib.handlers.bcrypt",
        "bcrypt",
        "jose",
        "jose.jwt",
        # HTTP
        "httptools",
        "h11",
        "wsproto",
        "websockets",
        # Other
        "apscheduler",
        "pyotp",
        "slowapi",
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
    runtime_hooks=[],
    cipher=block_cipher,
    noarchive=False,
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
