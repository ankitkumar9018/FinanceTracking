"""FinanceTracker API — FastAPI application entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.database import create_tables, dispose_engine
from app.utils.rate_limiter import limiter

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application startup and shutdown events."""
    # ── Startup ──────────────────────────────────────────────────────
    logger.info("Starting %s v%s", settings.app_name, settings.app_version)

    # Security warnings
    if settings.secret_key.startswith("dev-secret"):
        logger.warning(
            "SECRET_KEY is using the default development value. "
            "Set SECRET_KEY in .env for production use."
        )

    # Create database tables (safe to call if they already exist)
    await create_tables()
    logger.info("Database ready (%s)", "SQLite" if settings.is_sqlite else "PostgreSQL")

    # Check optional services and log status
    await _log_service_status()

    # Start background task scheduler (APScheduler fallback when Celery unavailable)
    from app.tasks.scheduler import start_scheduler

    start_scheduler()

    yield

    # ── Shutdown ─────────────────────────────────────────────────────
    from app.tasks.scheduler import stop_scheduler

    stop_scheduler()
    await dispose_engine()
    logger.info("Shutdown complete")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Personal investment portfolio tracking for Indian & German markets",
    lifespan=lifespan,
)

# ── Rate Limiting ─────────────────────────────────────────────────────────
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS ─────────────────────────────────────────────────────────────────
_cors_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
_allow_all = "*" in _cors_origins
if not _cors_origins and not _allow_all:
    logger.warning("CORS: No origins configured — all cross-origin requests will be blocked")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if _allow_all else _cors_origins,
    allow_credentials=not _allow_all,  # credentials incompatible with wildcard per CORS spec
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# ── Routes ───────────────────────────────────────────────────────────────
from app.api.v1.router import api_v1_router  # noqa: E402
from app.api.ws.alert_stream import router as ws_alert_router  # noqa: E402
from app.api.ws.price_stream import router as ws_price_router  # noqa: E402

app.include_router(api_v1_router, prefix="/api/v1")
app.include_router(ws_price_router)
app.include_router(ws_alert_router)


# ── Health Check ─────────────────────────────────────────────────────────
@app.get("/health")
async def health_check() -> dict:
    """Basic health check endpoint."""
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
    }


# ── Service Status ───────────────────────────────────────────────────────
async def _log_service_status() -> None:
    """Log the status of optional services on startup."""
    status_lines = [f"  Database: {'SQLite' if settings.is_sqlite else 'PostgreSQL'} ✓"]

    # Check Redis
    try:
        import redis.asyncio as aioredis

        r = aioredis.from_url(settings.redis_url, decode_responses=True)
        await r.ping()
        await r.aclose()
        status_lines.append("  Redis:    Connected ✓")
    except Exception:
        status_lines.append("  Redis:    Not available ⚠ (using in-memory fallback)")

    # Check Ollama
    if settings.llm_provider == "ollama":
        try:
            import httpx

            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{settings.ollama_url}/api/tags")
                if resp.status_code == 200:
                    status_lines.append(f"  Ollama:   Connected ✓ ({settings.ollama_model})")
                else:
                    status_lines.append("  Ollama:   Not responding ⚠ (AI features disabled)")
        except Exception:
            status_lines.append("  Ollama:   Not available ⚠ (AI features disabled)")
    else:
        provider = settings.llm_provider
        status_lines.append(f"  LLM:      {provider} configured")

    # Notifications
    notif_channels = []
    if settings.sendgrid_api_key:
        notif_channels.append("Email")
    if settings.twilio_account_sid:
        notif_channels.append("WhatsApp/SMS")
    if settings.telegram_bot_token:
        notif_channels.append("Telegram")
    if notif_channels:
        status_lines.append(f"  Alerts:   {', '.join(notif_channels)} ✓")
    else:
        status_lines.append("  Alerts:   No channels configured ⚠ (in-app only)")

    logger.info("Service Status:\n%s", "\n".join(status_lines))
