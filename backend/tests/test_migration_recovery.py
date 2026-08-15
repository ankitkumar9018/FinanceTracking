"""Regression tests for the schema-ahead-of-stamp migration recovery.

A database whose schema already contains columns that a pending migration
would add (e.g. one that was additively reconciled while stamped at an older
revision) used to crash ``alembic upgrade head`` with "duplicate column name".
``_run_migrations`` now detects that collision and steps revision-by-revision:
each pending revision is applied via ``upgrade +1``, and only revisions whose
DDL collides with the existing schema are stamped past. The old recovery
stamped straight to HEAD, which silently skipped every remaining revision —
including ones whose work was genuinely missing (e.g. 8809e230b920, which
only creates uq_holding_portfolio_symbol_exchange).

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


def _alembic_head() -> str:
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    assert head is not None
    return head


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
    assert version == _alembic_head()
    assert email == "ahead@x.com"


def test_constraint_revision_replayed_not_skipped(tmp_path):
    """The MEDIUM defect: stamp-to-head recovery skipped pending revisions.

    A DB stamped at 9ec39aff1e92 whose holdings table is missing the unique
    constraint that revision 8809e230b920 creates must have that revision
    REPLAYED during recovery (its DDL doesn't collide — the constraint is
    absent), not stamped past. The old recovery stamped straight to head,
    losing the constraint forever.
    """
    db_path = tmp_path / "stepping.db"

    # Full modern schema via create_all, then REBUILD holdings without its
    # unique constraint (SQLite can't DROP the auto-index of an inline
    # constraint, so the table is recreated from its DDL minus the clause).
    # Stamp at 9ec39aff1e92 — before the constraint revision — plus a data
    # row that must survive.
    setup = f"""
import asyncio, os, re, sqlite3
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///{db_path.as_posix()}"
import app.models  # register all models
from app.database import create_tables
asyncio.run(create_tables())
c = sqlite3.connect("{db_path.as_posix()}")
sql = c.execute(
    "SELECT sql FROM sqlite_master WHERE type='table' AND name='holdings'"
).fetchone()[0]
stripped = re.sub(
    r",\\s*CONSTRAINT uq_holding_portfolio_symbol_exchange UNIQUE \\([^)]*\\)",
    "", sql,
)
assert stripped != sql, "constraint clause not found in create_all DDL"
c.execute("PRAGMA foreign_keys=off")
c.execute("DROP TABLE holdings")
c.execute(stripped)
c.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
c.execute("INSERT INTO alembic_version VALUES ('9ec39aff1e92')")
c.execute(
    "INSERT INTO users (email, password_hash, preferred_currency, "
    "theme_preference, notification_preferences, is_active) "
    "VALUES ('step@x.com', 'h', 'INR', 'dark', '{{}}', 1)"
)
c.commit(); c.close()
"""
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db_path.as_posix()}"}
    subprocess.run(
        [sys.executable, "-c", setup], cwd=BACKEND_DIR, env=env, check=True,
        capture_output=True,
    )

    result = subprocess.run(
        [sys.executable, "-c",
         "from app.__main__ import _run_migrations; _run_migrations()"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, f"migration crashed:\n{result.stderr[-2000:]}"

    # Stepping (not stamp-to-head) was used: collisions were skipped one by
    # one, and the constraint revision was genuinely applied.
    assert "Schema is ahead" in result.stdout
    assert "stamping past it" in result.stdout
    assert "Applied pending revision 8809e230b920" in result.stdout

    conn = sqlite3.connect(db_path)
    version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    holdings_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='holdings'"
    ).fetchone()[0]
    users_cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
    email = conn.execute("SELECT email FROM users").fetchone()[0]

    # Recovery reached HEAD (not stuck at the first collision).
    assert version == _alembic_head()
    # The constraint 8809e230b920 creates EXISTS again — the old stamp-to-head
    # recovery lost it forever.
    assert "uq_holding_portfolio_symbol_exchange" in holdings_sql
    # Later revisions' columns are present and pre-existing data survived.
    assert "password_changed_at" in users_cols
    assert email == "step@x.com"

    # The replayed constraint actually enforces uniqueness.
    conn.execute("INSERT INTO portfolios (user_id, name) VALUES (1, 'P')")
    ins = ("INSERT INTO holdings (portfolio_id, stock_symbol, stock_name, "
           "exchange, cumulative_quantity, average_price) "
           "VALUES (1, 'INFY', 'Infosys', 'NSE', 1, 100)")
    conn.execute(ins)
    try:
        conn.execute(ins)
        raise AssertionError("duplicate holding was allowed — constraint missing")
    except sqlite3.IntegrityError:
        pass
    conn.close()


def test_sidecar_secret_generated_persisted_and_reused(tmp_path, monkeypatch):
    """Desktop mode must self-provision a strong, stable SECRET_KEY.

    Regression: the fail-closed default-secret check bricked the packaged
    sidecar (no .env ships with it). The sidecar now generates a per-install
    secret, persists it beside the DB, and reuses it on every later boot.
    """
    from app.__main__ import _ensure_sidecar_secret

    monkeypatch.delenv("SECRET_KEY", raising=False)
    _ensure_sidecar_secret(tmp_path)
    first = os.environ.get("SECRET_KEY")
    assert first and len(first) >= 64 and not first.startswith("dev-secret")
    assert (tmp_path / "secret.key").read_text().strip() == first

    # A later boot reuses the SAME key (sessions survive restarts/upgrades).
    monkeypatch.delenv("SECRET_KEY", raising=False)
    _ensure_sidecar_secret(tmp_path)
    assert os.environ.get("SECRET_KEY") == first

    # An explicit env var always wins over the stored file.
    monkeypatch.setenv("SECRET_KEY", "explicit-operator-key-0123456789abcdef")
    _ensure_sidecar_secret(tmp_path)
    assert os.environ["SECRET_KEY"] == "explicit-operator-key-0123456789abcdef"
