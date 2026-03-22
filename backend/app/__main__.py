"""CLI entry point for the FinanceTracker backend.

Used by PyInstaller sidecar and for direct invocation:
    python -m app --port 8000 --db-path /path/to/finance.db
    python -m app --port 8000 --db-path /path/to/finance.db --seed
"""

import argparse
import asyncio
import os
from pathlib import Path

import uvicorn


def _run_seed() -> None:
    """Seed the database with a demo user if it doesn't exist."""
    # Import here so env vars (DATABASE_URL) are already set
    from sqlalchemy import select

    from app.database import async_session_factory, create_tables
    from app.models.user import User
    from app.utils.security import hash_password
    from app.models.portfolio import Portfolio

    async def seed() -> None:
        await create_tables()
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
