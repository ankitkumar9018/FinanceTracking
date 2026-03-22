"""PyInstaller runtime hook -- fix sys.path for frozen binary.

When PyInstaller bundles app/__main__.py as the entry point, the 'app'
package may not be on sys.path. This hook adds the bundle's base directory
(where the extracted/embedded files live) so that 'import app.models' etc. work.
"""
import sys
import os

# _MEIPASS is set by PyInstaller to the temp extraction directory (onefile)
# or the directory containing the executable (onedir).
base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))

if base not in sys.path:
    sys.path.insert(0, base)

# Also ensure the parent of 'app' is on the path
# In case _MEIPASS contains app/ as a subdirectory
app_parent = base
if os.path.isdir(os.path.join(base, 'app')):
    app_parent = base
elif os.path.isdir(os.path.join(os.path.dirname(base), 'app')):
    app_parent = os.path.dirname(base)

if app_parent not in sys.path:
    sys.path.insert(0, app_parent)
