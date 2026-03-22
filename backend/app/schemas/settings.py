"""Pydantic schemas for settings endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class UserSettingsResponse(BaseModel):
    display: DisplaySettings
    notifications: NotificationSettings
    market: MarketSettings
    integrations: IntegrationSettings


class DisplaySettings(BaseModel):
    preferred_currency: str = "INR"
    theme_preference: str = "dark"
    display_name: str = ""


class NotificationSettings(BaseModel):
    email_enabled: bool = False
    telegram_enabled: bool = False
    whatsapp_enabled: bool = False
    in_app_enabled: bool = True
    alert_check_interval: int = 60


class MarketSettings(BaseModel):
    price_refresh_interval: int = 5
    default_chart_days: int = 30


class IntegrationSettings(BaseModel):
    llm_provider: str = "ollama"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2"
    has_sendgrid_key: bool = False
    has_telegram_bot: bool = False


class SettingsUpdate(BaseModel):
    """Flat dict of setting keys and values to update."""

    preferred_currency: str | None = None
    theme_preference: str | None = None
    display_name: str | None = None
    notification_preferences: dict | None = None


class HealthStatus(BaseModel):
    database: str
    redis: str
    ollama: str
    broker: str
    overall: str


# Rebuild models that reference forward declarations
UserSettingsResponse.model_rebuild()
