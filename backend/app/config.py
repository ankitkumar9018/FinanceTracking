"""Application configuration via pydantic-settings.

All settings can be overridden via:
1. Environment variables
2. .env file
3. In-app Settings UI (stored in app_settings table, highest priority)
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────
    app_name: str = "FinanceTracker"
    app_version: str = "0.1.0"
    debug: bool = False
    api_port: int = 8000

    # ── Security ─────────────────────────────────────────────────────────
    secret_key: str = "dev-secret-CHANGE-IN-PRODUCTION"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7
    fernet_key: str = ""  # Auto-generated on first run if empty

    # ── Database ─────────────────────────────────────────────────────────
    database_url: str = f"sqlite+aiosqlite:///{BASE_DIR / 'finance.db'}"

    # ── Market Data ──────────────────────────────────────────────────────
    price_refresh_interval: int = 5  # minutes
    default_chart_days: int = 30
    market_hours_in: str = "09:15-15:30"  # IST
    market_hours_de: str = "09:00-17:30"  # CET

    # ── Redis (optional) ─────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379"

    # ── Notifications ────────────────────────────────────────────────────
    # Email (SendGrid)
    sendgrid_api_key: str = ""
    email_from: str = ""

    # WhatsApp / SMS (Twilio)
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_whatsapp_from: str = ""
    twilio_sms_from: str = ""

    # Telegram
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # ── LLM (all optional) ──────────────────────────────────────────────
    llm_provider: Literal["ollama", "openai", "anthropic", "google", "none"] = "ollama"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    openai_api_key: str = ""
    openai_model: str = "gpt-4"
    anthropic_api_key: str = ""
    google_api_key: str = ""

    # ── Broker API Keys ─────────────────────────────────────────────────
    zerodha_api_key: str = ""
    zerodha_api_secret: str = ""
    icici_app_key: str = ""
    icici_secret_key: str = ""

    # ── CORS ───────────────────────────────────────────────────────────
    cors_origins: str = "http://localhost:3000,http://localhost:1420,https://tauri.localhost"

    # ── Display Defaults ─────────────────────────────────────────────────
    default_currency: Literal["INR", "EUR", "USD"] = "INR"
    default_theme: Literal["dark", "light", "system"] = "dark"
    alert_check_interval: int = 60  # seconds

    # ── Derived ──────────────────────────────────────────────────────────
    @property
    def is_sqlite(self) -> bool:
        return "sqlite" in self.database_url

    @property
    def redis_available(self) -> bool:
        """Check if Redis URL is configured (actual connectivity checked at runtime)."""
        return bool(self.redis_url)


settings = Settings()
