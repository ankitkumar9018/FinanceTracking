"""PyInstaller entry point for FinanceTracker backend sidecar.

This is a thin wrapper that ensures sys.path includes the PyInstaller
extraction directory, then delegates to app.__main__.main().

CRITICAL: Do NOT import app.config, app.database, or app.models here.
Those modules read DATABASE_URL from the environment, which is set by
__main__.py from the --db-path CLI argument. Importing them early would
initialize the database engine with the WRONG default path, causing
data to be written to a different file than expected.
"""
import sys
import os

# Ensure the PyInstaller bundle root is on sys.path
base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
if base not in sys.path:
    sys.path.insert(0, base)

# Run the app — __main__.py sets env vars first, then imports app modules
from app.__main__ import main  # noqa: E402

if __name__ == "__main__":
    main()
