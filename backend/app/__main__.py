"""CLI entry point for the FinanceTracker backend.

Used by PyInstaller sidecar and for direct invocation:
    python -m app --port 8000 --db-path /path/to/finance.db
    python -m app --port 8000 --db-path /path/to/finance.db --seed
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

import uvicorn


def _run_migrations() -> None:
    """Run Alembic migrations (upgrade head) programmatically.

    Handles three scenarios:
    1. **Fresh install** – no DB exists. Alembic creates all tables via migrations.
    2. **Upgrade** – DB exists with alembic_version. Only pending migrations run.
    3. **Legacy DB** – DB created by create_all() with no alembic_version table.
       Stamp it at ``head`` so future upgrades apply correctly.
    """
    from alembic.config import Config
    from alembic import command
    from sqlalchemy import create_engine, inspect

    db_url = os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///./finance.db")
    # Alembic needs a synchronous driver
    sync_url = db_url.replace("+aiosqlite", "")

    # Locate alembic.ini — inside PyInstaller bundle it's at _MEIPASS root,
    # otherwise at the backend/ directory (one level above app/).
    if hasattr(sys, "_MEIPASS"):
        base_dir = sys._MEIPASS
    else:
        base_dir = str(Path(__file__).resolve().parent.parent)

    ini_path = os.path.join(base_dir, "alembic.ini")
    alembic_dir = os.path.join(base_dir, "alembic")

    if not os.path.isfile(ini_path):
        print(f"[migrate] alembic.ini not found at {ini_path}, falling back to create_all()")
        from app.database import create_tables
        asyncio.run(create_tables())
        return

    cfg = Config(ini_path)
    cfg.set_main_option("sqlalchemy.url", sync_url)
    cfg.set_main_option("script_location", alembic_dir)

    # Check if this is a legacy DB (has app tables but no alembic_version)
    engine = create_engine(sync_url)
    try:
        with engine.connect() as conn:
            inspector = inspect(conn)
            tables = inspector.get_table_names()
            has_app_tables = "users" in tables or "holdings" in tables
            has_alembic = "alembic_version" in tables
    finally:
        engine.dispose()

    if has_app_tables and not has_alembic:
        # Legacy DB created by create_all() — stamp at head so we don't
        # try to recreate existing tables, only future migrations will run.
        print("[migrate] Legacy DB detected (no alembic_version). Stamping at head.")
        command.stamp(cfg, "head")
    else:
        print("[migrate] Running alembic upgrade head...")
        command.upgrade(cfg, "head")
        print("[migrate] Migrations complete.")


def _run_seed() -> None:
    """Run migrations then seed the database with a demo user if needed."""
    # Import here so env vars (DATABASE_URL) are already set
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.models.user import User
    from app.utils.security import hash_password
    from app.models.portfolio import Portfolio

    # Run migrations first (creates/upgrades schema)
    _run_migrations()

    async def seed() -> None:
        async with async_session_factory() as db:
            result = await db.execute(select(User).where(User.email == "demo@financetracker.dev"))
            if result.scalar_one_or_none():
                print("[seed] Demo user already exists, skipping.")
                return

            user = User(
                email="demo@financetracker.dev",
                password_hash=hash_password("demo1234"),
                display_name="Demo User",
                preferred_currency="INR",
                theme_preference="dark",
                is_active=True,
            )
            db.add(user)
            await db.flush()

            portfolio = Portfolio(
                user_id=user.id,
                name="My Portfolio",
                description="Default portfolio",
                is_default=True,
            )
            db.add(portfolio)
            await db.commit()
            print("[seed] Created demo user (demo@financetracker.dev / demo1234)")

    asyncio.run(seed())


def main() -> None:
    parser = argparse.ArgumentParser(description="FinanceTracker Backend")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--db-path", type=str, default="", help="Path to SQLite database file")
    parser.add_argument("--seed", action="store_true", help="Seed demo user on first run")
    args = parser.parse_args()

    if args.db_path:
        # Use forward slashes for SQLAlchemy URL (Windows backslashes break the URL)
        # URL-encode the path to handle spaces (e.g. "C:/Users/John Doe/...")
        from urllib.parse import quote
        db_posix = Path(args.db_path).as_posix()
        db_encoded = quote(db_posix, safe="/:")
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_encoded}"

    # Sidecar mode: allow all origins. The backend binds to 127.0.0.1 only,
    # so this is safe. Avoids CORS mismatches across platform webview engines
    # (macOS WKWebView sends null/tauri://, Windows WebView2 sends https://tauri.localhost, etc.)
    os.environ["CORS_ORIGINS"] = "*"

    if args.seed:
        _run_seed()

    # Import the app object directly instead of using string reference.
    # PyInstaller frozen binaries can't resolve string-based module imports.
    from app.main import app

    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
