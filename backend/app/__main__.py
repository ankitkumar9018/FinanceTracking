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
    # configparser treats % as interpolation syntax — a URL-encoded path like
    # .../Application%20Support/... (any macOS install!) crashes set_main_option
    # with "invalid interpolation syntax" unless % is escaped as %%.
    cfg.set_main_option("sqlalchemy.url", sync_url.replace("%", "%%"))
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

    # Safety net for upgrades: stamping a legacy DB at head claims newer
    # migrations already ran, so columns they would have added are missing.
    # Reconcile additively so an old DB keeps working with a new build.
    _reconcile_schema(sync_url)


def _reconcile_schema(sync_url: str) -> None:
    """Additive schema reconciliation: create missing tables, add missing columns.

    Never drops, renames, or rewrites anything — existing data is untouched.
    This is what guarantees a database created by an OLDER app version keeps
    working after installing a NEWER build, regardless of how its schema was
    originally created (alembic or create_all).
    """
    from sqlalchemy import create_engine, inspect, text

    import app.models  # noqa: F401 — registers every model on Base.metadata
    from app.database import Base

    engine = create_engine(sync_url)
    try:
        inspector = inspect(engine)
        existing_tables = set(inspector.get_table_names())

        # 1. Tables added in newer versions (create_all only creates absent ones)
        Base.metadata.create_all(engine)

        # 2. Columns added in newer versions. SQLite can't ADD COLUMN with
        #    NOT NULL and no default, so columns are added nullable (or with
        #    the model's scalar default when it has one).
        with engine.begin() as conn:
            for table in Base.metadata.sorted_tables:
                if table.name not in existing_tables:
                    continue
                have = {c["name"] for c in inspector.get_columns(table.name)}
                for column in table.columns:
                    if column.name in have:
                        continue
                    col_type = column.type.compile(dialect=engine.dialect)
                    ddl = f'ALTER TABLE "{table.name}" ADD COLUMN "{column.name}" {col_type}'
                    default = None
                    if column.default is not None and getattr(column.default, "is_scalar", False):
                        default = column.default.arg
                    if isinstance(default, bool):
                        ddl += f" DEFAULT {int(default)}"
                    elif isinstance(default, (int, float)):
                        ddl += f" DEFAULT {default}"
                    elif isinstance(default, str):
                        ddl += " DEFAULT '{}'".format(default.replace("'", "''"))
                    print(f"[migrate] Adding missing column {table.name}.{column.name}")
                    conn.execute(text(ddl))
    except Exception as exc:
        # Never block startup on reconciliation — worst case the app behaves
        # like before this safety net existed.
        print(f"[migrate] Schema reconciliation warning: {exc}")
    finally:
        engine.dispose()


def _run_seed() -> None:
    """Seed the database with a demo user if needed (schema must exist)."""
    # Import here so env vars (DATABASE_URL) are already set
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.models.user import User
    from app.utils.security import hash_password
    from app.models.portfolio import Portfolio

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
        # Use forward slashes for SQLAlchemy URL (Windows backslashes break the URL).
        # Do NOT percent-encode: SQLAlchemy takes the sqlite database path
        # verbatim (no URL-decoding), so an encoded "Application%20Support"
        # becomes a literal %20 directory that doesn't exist. Raw spaces work.
        db_posix = Path(args.db_path).as_posix()
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_posix}"

    # Sidecar mode: allow all origins. The backend binds to 127.0.0.1 only,
    # so this is safe. Avoids CORS mismatches across platform webview engines
    # (macOS WKWebView sends null/tauri://, Windows WebView2 sends https://tauri.localhost, etc.)
    os.environ["CORS_ORIGINS"] = "*"

    # Always migrate/reconcile when a concrete DB path is given (sidecar mode)
    # — not only when seeding — so upgrades work even without --seed.
    if args.db_path or args.seed:
        _run_migrations()

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
