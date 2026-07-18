"""Authentication endpoints: register, login, JWT refresh, 2FA."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.database import get_db
from app.models.password_reset import PasswordReset
from app.models.user import User
from app.schemas.auth import (
    BackupCodesRegenerateRequest,
    BackupCodesResponse,
    BackupCodesStatus,
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserResponse,
)
from app.services import notification_service
from app.utils.audit import audit_log
from app.utils.rate_limiter import limiter
from app.utils.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_totp_secret,
    get_totp_uri,
    hash_password,
    verify_password,
    verify_totp,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Inline schemas for 2FA ────────────────────────────────────────────────────

class TwoFactorCode(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)


class TwoFactorVerify(TwoFactorCode):
    secret: str = Field(..., min_length=16, description="TOTP secret from /2fa/setup")


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


# ── 2FA backup-code helpers ───────────────────────────────────────────────────

_BACKUP_CODE_COUNT = 10


def _normalize_backup_code(code: str) -> str:
    """Normalize a backup code so matching is case- and separator-insensitive."""
    return "".join(ch for ch in code.lower() if ch.isalnum())


def _hash_backup_code(code: str) -> str:
    """SHA-256 hex hash of a normalized backup code."""
    return hashlib.sha256(_normalize_backup_code(code).encode()).hexdigest()


def _generate_backup_codes() -> tuple[list[str], list[str]]:
    """Generate a fresh set of backup codes.

    Returns ``(raw_codes, hashes)``. Raw codes are formatted ``xxxx-xxxx`` and
    are the only time the plaintext exists — only the hashes are persisted.
    """
    raw_codes: list[str] = []
    for _ in range(_BACKUP_CODE_COUNT):
        token = secrets.token_hex(4)  # 8 hex chars
        raw_codes.append(f"{token[:4]}-{token[4:]}")
    hashes = [_hash_backup_code(c) for c in raw_codes]
    return raw_codes, hashes


def _consume_backup_code(user: User, code: str) -> bool:
    """If ``code`` matches an unused backup code, consume it and return True.

    Reassigns ``user.totp_backup_codes`` to a new list so SQLAlchemy detects the
    change to the JSON column.
    """
    codes = user.totp_backup_codes or []
    candidate = _hash_backup_code(code)
    if candidate not in codes:
        return False
    user.totp_backup_codes = [h for h in codes if h != candidate]
    return True


# ── Auth endpoints ────────────────────────────────────────────────────────────

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(
    request: Request,
    body: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Create a new user account."""
    # Check if email already exists
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        )

    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        display_name=body.display_name or "",
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)

    await audit_log(
        db,
        user_id=user.id,
        action="register",
        resource_type="user",
        resource_id=user.id,
        ip_address=request.client.host if request.client else None,
    )

    return user


@router.post("/login", response_model=None)
@limiter.limit("10/minute")
async def login(
    request: Request,
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Login with email and password, returns JWT tokens.

    If 2FA is enabled and no totp_code is provided, returns
    ``{"requires_2fa": true}`` instead of tokens.
    """
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    # ── 2FA check ─────────────────────────────────────────────────────
    if user.totp_secret:
        if not body.totp_code:
            return {"requires_2fa": True, "message": "Please provide TOTP code"}
        # Primary path: a valid TOTP code from the authenticator app.
        if not verify_totp(user.totp_secret, body.totp_code):
            # Fallback: allow a one-time backup code (consumed on use) so a
            # user who lost their authenticator can still get in.
            if not _consume_backup_code(user, body.totp_code):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid TOTP code",
                )
            await db.flush()
            await audit_log(
                db,
                user_id=user.id,
                action="login_backup_code",
                resource_type="user",
                resource_id=user.id,
                details="logged in with a 2FA backup code",
                ip_address=request.client.host if request.client else None,
            )

    token_data = {"sub": str(user.id), "email": user.email}

    await audit_log(
        db,
        user_id=user.id,
        action="login",
        resource_type="user",
        resource_id=user.id,
        ip_address=request.client.host if request.client else None,
    )

    return {
        "access_token": create_access_token(token_data),
        "refresh_token": create_refresh_token(token_data),
        "token_type": "bearer",
    }


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit("20/minute")
async def refresh_token(
    request: Request,
    body: RefreshRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a new access token using a refresh token."""
    payload = decode_token(body.refresh_token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    # Verify user still exists and is active
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )
    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account is deactivated or does not exist",
        )

    token_data = {"sub": str(user.id), "email": user.email}
    return {
        "access_token": create_access_token(token_data),
        "refresh_token": create_refresh_token(token_data),
        "token_type": "bearer",
    }


# ── Password reset endpoints ──────────────────────────────────────────────────

_GENERIC_RESET_MESSAGE = "If that email exists, a reset link has been sent."


@router.post("/forgot-password")
@limiter.limit("3/minute")
async def forgot_password(
    request: Request,
    body: ForgotPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Start a password reset.

    Always returns a generic 200 response so the endpoint never reveals
    whether an account exists for the given email. If the user does exist,
    a single-use token is stored (hashed) and a reset link is emailed.
    """
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()

    if user:
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)

        db.add(
            PasswordReset(
                user_id=user.id,
                token_hash=token_hash,
                expires_at=expires_at,
            )
        )
        await db.flush()

        frontend_base = settings.cors_origins.split(",")[0].strip().rstrip("/")
        reset_link = f"{frontend_base}/reset-password?token={raw_token}"
        subject = "Reset your FinanceTracker password"
        html_body = (
            "<p>We received a request to reset your FinanceTracker password.</p>"
            f'<p><a href="{reset_link}">Click here to reset your password</a>.</p>'
            "<p>Or paste this token into the reset form (valid for 1 hour):</p>"
            f"<p><code>{raw_token}</code></p>"
            "<p>If you did not request this, you can safely ignore this email.</p>"
        )

        # Best-effort: if SendGrid is unconfigured send_email returns False.
        # We still return the generic 200 so callers learn nothing either way.
        sent = await notification_service.send_email(
            to_email=user.email,
            subject=subject,
            body=html_body,
            user_id=user.id,
            db=db,
        )
        if not sent:
            logger.warning(
                "Password reset email not delivered for user %d "
                "(email provider unconfigured or failed)",
                user.id,
            )

    return {"message": _GENERIC_RESET_MESSAGE}


@router.post("/reset-password")
@limiter.limit("5/minute")
async def reset_password(
    request: Request,
    body: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Complete a password reset using a single-use token."""
    token_hash = hashlib.sha256(body.token.encode()).hexdigest()
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(PasswordReset).where(
            PasswordReset.token_hash == token_hash,
            PasswordReset.used_at.is_(None),
            PasswordReset.expires_at > now,
        )
    )
    reset = result.scalar_one_or_none()
    if reset is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired token",
        )

    user_result = await db.execute(select(User).where(User.id == reset.user_id))
    user = user_result.scalar_one_or_none()
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired token",
        )

    user.password_hash = hash_password(body.new_password)
    reset.used_at = now

    # Invalidate this user's other outstanding reset tokens.
    await db.execute(
        update(PasswordReset)
        .where(
            PasswordReset.user_id == user.id,
            PasswordReset.used_at.is_(None),
        )
        .values(used_at=now)
    )
    await db.flush()

    await audit_log(
        db,
        user_id=user.id,
        action="password_change",
        resource_type="user",
        resource_id=user.id,
        details="password reset via token",
        ip_address=request.client.host if request.client else None,
    )

    return {"message": "Password has been reset successfully"}


# ── Current user endpoint ─────────────────────────────────────────────────────

@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    user: User = Depends(get_current_user),
) -> UserResponse:
    """Get the current authenticated user's information."""
    response = UserResponse.model_validate(user)
    response.totp_enabled = user.totp_secret is not None
    return response


# ── 2FA endpoints ────────────────────────────────────────────────────────────

@router.post("/change-password")
async def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Change the current user's password (requires the current password)."""
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )
    user.password_hash = hash_password(body.new_password)
    await db.flush()
    await audit_log(
        db,
        user_id=user.id,
        action="password_change",
        resource_type="user",
        resource_id=user.id,
    )
    return {"message": "Password updated successfully"}


@router.post("/2fa/setup")
async def setup_2fa(
    user: User = Depends(get_current_user),
) -> dict:
    """Generate a TOTP secret and return the provisioning URI.

    The secret is NOT persisted yet — call ``/2fa/verify`` with the secret
    and a valid TOTP code to activate 2FA.
    """
    if user.totp_secret:
        raise HTTPException(status_code=400, detail="2FA is already enabled. Disable it first.")
    secret = generate_totp_secret()
    uri = get_totp_uri(secret, user.email)
    return {"totp_secret": secret, "totp_uri": uri}


@router.post("/2fa/verify")
async def verify_2fa(
    body: TwoFactorVerify,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Verify a TOTP code and activate 2FA.

    Accepts the ``secret`` from ``/2fa/setup`` and a ``code`` from the
    authenticator app.  Only persists the secret on success, preventing
    lockout if the user's authenticator isn't configured correctly.
    """
    if user.totp_secret:
        # Refuse to overwrite an active secret: a leaked access token must
        # not be enough to swap in an attacker-controlled second factor.
        raise HTTPException(status_code=400, detail="2FA is already enabled. Disable it first.")
    if not verify_totp(body.secret, body.code):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")
    user.totp_secret = body.secret
    # Issue one-time recovery codes; the raw values are shown here exactly once.
    raw_codes, hashes = _generate_backup_codes()
    user.totp_backup_codes = hashes  # reassign so SQLAlchemy tracks the change
    await db.flush()
    return {
        "verified": True,
        "message": "2FA is now active",
        "backup_codes": raw_codes,
    }


@router.post("/2fa/disable")
async def disable_2fa(
    body: TwoFactorCode,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Disable 2FA after verifying current code."""
    if not user.totp_secret:
        raise HTTPException(status_code=400, detail="2FA is not enabled")
    if not verify_totp(user.totp_secret, body.code):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")
    user.totp_secret = None
    user.totp_backup_codes = None  # recovery codes are meaningless without 2FA
    await db.flush()
    return {"message": "2FA has been disabled"}


@router.get("/2fa/backup-codes/status", response_model=BackupCodesStatus)
async def backup_codes_status(
    user: User = Depends(get_current_user),
) -> BackupCodesStatus:
    """Return how many unused 2FA backup codes remain (never the codes)."""
    return BackupCodesStatus(remaining=len(user.totp_backup_codes or []))


@router.post("/2fa/backup-codes/regenerate", response_model=BackupCodesResponse)
async def regenerate_backup_codes(
    body: BackupCodesRegenerateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BackupCodesResponse:
    """Generate a fresh set of backup codes, invalidating any previous ones.

    Requires a current TOTP code. The raw codes are returned exactly once.
    """
    if not user.totp_secret:
        raise HTTPException(status_code=400, detail="2FA is not enabled")
    if not verify_totp(user.totp_secret, body.code):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")
    raw_codes, hashes = _generate_backup_codes()
    user.totp_backup_codes = hashes  # reassign so SQLAlchemy tracks the change
    await db.flush()
    await audit_log(
        db,
        user_id=user.id,
        action="regenerate_backup_codes",
        resource_type="user",
        resource_id=user.id,
    )
    return BackupCodesResponse(backup_codes=raw_codes)
