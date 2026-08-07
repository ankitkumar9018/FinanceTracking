"""Regression test for the schema-ahead-of-stamp migration recovery.

A database whose schema already contains columns that a pending migration
would add (e.g. one that was additively reconciled while stamped at an older
revision) used to crash ``alembic upgrade head`` with "duplicate column name".
``_run_migrations`` now detects that collision, stamps head, and relies on the
additive reconcile to fill anything genuinely missing — without touching data.

Run as a subprocess so DATABASE_URL is picked up by a fresh ``app.config``
settings instance, exactly as the launch scripts invoke it.
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent


def test_schema_ahead_of_stamp_recovers(tmp_path):
    db_path = tmp_path / "ahead.db"

    # Build a DB with the FULL current schema (create_all) but stamped at an
    # OLD alembic revision, plus a row of real data that must survive.
    setup = f"""
import asyncio, os, sqlite3
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///{db_path.as_posix()}"
import app.models  # register all models
from app.database import create_tables
asyncio.run(create_tables())
c = sqlite3.connect("{db_path.as_posix()}")
c.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
c.execute("INSERT INTO alembic_version VALUES ('8809e230b920')")
c.execute(
    "INSERT INTO users (email, password_hash, preferred_currency, "
    "theme_preference, notification_preferences, is_active) "
    "VALUES ('ahead@x.com', 'h', 'INR', 'dark', '{{}}', 1)"
)
c.commit(); c.close()
"""
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db_path.as_posix()}"}
    subprocess.run(
        [sys.executable, "-c", setup], cwd=BACKEND_DIR, env=env, check=True,
        capture_output=True,
    )

    # The old behavior crashed here with OperationalError: duplicate column.
    result = subprocess.run(
        [sys.executable, "-c",
         "from app.__main__ import _run_migrations; _run_migrations()"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, f"migration crashed:\n{result.stderr[-2000:]}"
    assert "Schema is ahead" in result.stdout

    # Stamp advanced to head, and the pre-existing data survived.
    conn = sqlite3.connect(db_path)
    version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    email = conn.execute("SELECT email FROM users").fetchone()[0]
    conn.close()
    assert version != "8809e230b920"
    assert email == "ahead@x.com"
