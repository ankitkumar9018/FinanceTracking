"""Process-wide logging configuration.

Nothing in this backend ever called ``logging.basicConfig`` / ``dictConfig``.
Under uvicorn's default ``LOGGING_CONFIG`` only the ``uvicorn*`` loggers are
configured — the ROOT logger keeps zero handlers at its default ``WARNING``
level, so every ``app.*`` and ``audit`` logger inherited WARNING and every
``logger.info`` call in the codebase was discarded. In particular the entire
security audit trail (``app.utils.audit.audit_log``, which persists nothing to
the database and only calls ``logger.info``) went nowhere at all: a brute-force
login left no record on disk or on screen. The warnings/errors that *did* fire
were emitted through ``logging.lastResort``, i.e. bare message text with no
timestamp, level or logger name.

This module installs a real root handler exactly once, driven by the
already-documented ``LOG_LEVEL`` environment variable (also read from
``backend/.env``, which is where the documented knob actually lives for most
installs).

Two invariants worth keeping:

* It never removes a handler it does not own, so an operator's own
  ``dictConfig`` (or pytest's capture handler) keeps working.
* The ``audit`` logger is pinned at INFO regardless of the root level, so
  raising LOG_LEVEL to WARNING to quieten the app can never silently switch
  the audit trail off.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import IO

__all__ = [
    "AUDIT_LOGGER_NAME",
    "DEFAULT_LOG_LEVEL",
    "LOG_DATE_FORMAT",
    "LOG_FORMAT",
    "configure_logging",
    "resolve_log_level",
]

DEFAULT_LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

#: The audit trail's logger. Pinned at INFO by :func:`configure_logging`.
AUDIT_LOGGER_NAME = "audit"

_VALID_LEVELS = ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG")

# Marker attribute stamped on the handler we install, so repeat calls can
# recognise (and replace) our own handler without touching anyone else's.
_OWNED = "_financetracker_owned"

_ENV_VAR = "LOG_LEVEL"


def _dotenv_log_level() -> str | None:
    """Read ``LOG_LEVEL`` out of ``backend/.env``.

    ``Settings`` declares no ``log_level`` field and its ``model_config`` sets
    ``extra="ignore"``, so a ``LOG_LEVEL`` line in .env is dropped before any
    code can see it. Since .env is where the documented knob actually lives,
    parse that one key directly (a five-line parser beats booting a second
    settings model just to read a string).
    """
    try:
        from app.config import BASE_DIR

        env_path = Path(BASE_DIR) / ".env"
        raw = env_path.read_text(encoding="utf-8")
    except Exception:  # pragma: no cover - missing/unreadable .env is normal
        return None

    value: str | None = None
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, raw_value = stripped.partition("=")
        if key.strip().upper() != _ENV_VAR:
            continue
        # Last assignment wins, matching dotenv semantics.
        value = raw_value.split("#", 1)[0].strip().strip("\"'") or None
    return value


def resolve_log_level(explicit: str | None = None) -> str:
    """Resolve the effective log level name.

    Precedence: explicit argument → ``LOG_LEVEL`` env var → ``LOG_LEVEL`` in
    ``backend/.env`` → :data:`DEFAULT_LOG_LEVEL`. An unrecognised value falls
    back to the default rather than crashing startup.
    """
    candidates = (explicit, os.environ.get(_ENV_VAR), _dotenv_log_level())
    for candidate in candidates:
        if not candidate:
            continue
        name = candidate.strip().upper()
        if name in _VALID_LEVELS:
            return name
        logging.getLogger(__name__).warning(
            "Ignoring unknown %s=%r (expected one of %s)",
            _ENV_VAR,
            candidate,
            ", ".join(_VALID_LEVELS),
        )
    return DEFAULT_LOG_LEVEL


def configure_logging(
    level: str | None = None,
    *,
    reinstall: bool = False,
    stream: IO[str] | None = None,
) -> str:
    """Attach a formatted stderr handler to the root logger and set its level.

    Idempotent: calling it twice does not double up handlers, and it never
    installs a second handler when something else (an operator's dictConfig,
    pytest's capture handler) already owns the root logger.

    Parameters
    ----------
    level:
        Explicit level name; otherwise resolved via :func:`resolve_log_level`.
    reinstall:
        Drop and recreate our own handler (used from the app lifespan, after a
        framework such as uvicorn has run its own ``dictConfig``).
    stream:
        Write to this stream instead of ``sys.stderr``. Passing a stream also
        forces installation — used by tests.

    Returns the level name that was applied.
    """
    level_name = resolve_log_level(level)
    numeric = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    owned = [h for h in root.handlers if getattr(h, _OWNED, False)]
    had_owned = bool(owned)

    if reinstall or stream is not None:
        for handler in owned:
            root.removeHandler(handler)
        owned = []

    # Install when we have no handler of our own AND either nobody else has
    # claimed the root logger, or we are replacing a handler we already owned,
    # or a stream was explicitly requested.
    others = [h for h in root.handlers if not getattr(h, _OWNED, False)]
    target = stream if stream is not None else sys.stderr
    # A frozen windowed build can have no stderr at all; attaching a handler to
    # None would turn every log call into a "--- Logging error ---" traceback.
    if not owned and target is not None and (had_owned or not others or stream is not None):
        handler = logging.StreamHandler(target)
        handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
        setattr(handler, _OWNED, True)
        root.addHandler(handler)

    root.setLevel(numeric)

    # The audit trail must survive a quieter root: a record only has to clear
    # its own logger's level, then every ancestor HANDLER sees it regardless of
    # the ancestor loggers' levels.
    logging.getLogger(AUDIT_LOGGER_NAME).setLevel(min(numeric, logging.INFO))

    return level_name
