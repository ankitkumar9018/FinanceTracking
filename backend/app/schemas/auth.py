"""Pydantic schemas for authentication."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = None


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
    totp_code: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    email: str
    display_name: str
    preferred_currency: str
    theme_preference: str
    is_active: bool
    created_at: datetime
    totp_enabled: bool = False
    phone: str | None = None
    telegram_chat_id: str | None = None

    model_config = {"from_attributes": True}


# ── 2FA backup codes ──────────────────────────────────────────────────────────

class BackupCodesRegenerateRequest(BaseModel):
    """Request to regenerate 2FA backup codes — requires a current TOTP code."""

    code: str = Field(..., min_length=6, max_length=6, description="Current TOTP code")


class BackupCodesResponse(BaseModel):
    """Raw backup codes, returned exactly once at generation time."""

    backup_codes: list[str]
    message: str = (
        "Save these backup codes now — each works once and they will not be shown again."
    )


class BackupCodesStatus(BaseModel):
    """How many unused backup codes remain (the codes themselves are never returned)."""

    remaining: int
