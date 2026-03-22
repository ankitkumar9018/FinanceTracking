"""PyInstaller entry point for FinanceTracker backend sidecar.

This wrapper exists outside the 'app' package so that 'app' is a proper
importable package relative to this script. When PyInstaller bundles
app/__main__.py directly, the 'app' package sometimes isn't on sys.path
on Windows, causing 'No module named app.models'.
"""
import sys
import os

# Ensure the bundle root is on sys.path
base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
if base not in sys.path:
    sys.path.insert(0, base)

# Now import and run the actual entry point
from app.__main__ import main

if __name__ == "__main__":
    main()
