"""Authentication endpoints: register, login, JWT refresh, 2FA."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
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

router = APIRouter()


# ── Inline schemas for 2FA ────────────────────────────────────────────────────

class TwoFactorCode(BaseModel):
    code: str = Field(..., min_length=6, max_length=6)


class TwoFactorVerify(TwoFactorCode):
    secret: str = Field(..., min_length=16, description="TOTP secret from /2fa/setup")


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
        if not verify_totp(user.totp_secret, body.totp_code):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid TOTP code",
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


# ── Current user endpoint ─────────────────────────────────────────────────────

@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    user: User = Depends(get_current_user),
) -> User:
    """Get the current authenticated user's information."""
    return user


# ── 2FA endpoints ────────────────────────────────────────────────────────────

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
    if not verify_totp(body.secret, body.code):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")
    user.totp_secret = body.secret
    await db.flush()
    return {"verified": True, "message": "2FA is now active"}


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
    await db.flush()
    return {"message": "2FA has been disabled"}
