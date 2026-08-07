"""Shared API dependencies: authentication, authorization, ownership checks."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.user import User
from app.utils.security import decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def validate_pcat(payload: dict, user: User) -> bool:
    """Return ``False`` if the token predates the user's last password change.

    The ``pcat`` claim carries the ``password_changed_at`` epoch at mint time;
    if the stored stamp is newer, this token was minted before a credential
    change and must not be honoured (defends against stolen tokens surviving a
    password reset). A missing/garbled claim is treated as 0, so legacy tokens
    without ``pcat`` stay valid until the user actually changes their password.

    Shared by ``get_current_user`` (access tokens), the ``/auth/refresh``
    endpoint (refresh tokens) and the WebSocket authenticator.
    """
    token_pcat_raw = payload.get("pcat", 0)
    try:
        token_pcat = int(token_pcat_raw)
    except (TypeError, ValueError):
        token_pcat = 0
    if user.password_changed_at is not None:
        current_pcat = int(user.password_changed_at.timestamp())
        if token_pcat < current_pcat:
            return False
    return True


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract and validate the current user from the JWT Authorization header.

    Raises HTTP 401 if the token is missing, expired, or invalid,
    or if the referenced user no longer exists / is deactivated.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_token(token)
    if payload is None:
        raise credentials_exception

    if payload.get("type") != "access":
        raise credentials_exception

    user_id_str: str | None = payload.get("sub")
    if user_id_str is None:
        raise credentials_exception

    try:
        user_id = int(user_id_str)
    except (ValueError, TypeError):
        raise credentials_exception from None

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is deactivated",
        )

    # Reject tokens minted before the user's most recent password change/reset.
    if not validate_pcat(payload, user):
        raise credentials_exception

    return user


# ---------------------------------------------------------------------------
# Shared ownership checks
# ---------------------------------------------------------------------------

async def verify_portfolio_ownership(
    portfolio_id: int,
    user: User,
    db: AsyncSession,
) -> Portfolio:
    """Fetch a portfolio, ensuring it exists and belongs to ``user``.

    Raises HTTP 404 otherwise — this is the single canonical ownership check
    shared by every route family (holdings, analytics, tax, exports, F&O, …)
    so a missing / other-user portfolio always yields the same response.
    """
    result = await db.execute(
        select(Portfolio).where(
            Portfolio.id == portfolio_id,
            Portfolio.user_id == user.id,
        )
    )
    portfolio = result.scalar_one_or_none()
    if portfolio is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Portfolio not found or does not belong to the current user",
        )
    return portfolio


async def verify_holding_ownership(
    holding_id: int,
    user: User,
    db: AsyncSession,
) -> Holding:
    """Fetch a holding, verifying it belongs to one of ``user``'s portfolios.

    Raises HTTP 404 otherwise — canonical counterpart of
    :func:`verify_portfolio_ownership` for holding-scoped routes.
    """
    result = await db.execute(
        select(Holding)
        .join(Portfolio, Holding.portfolio_id == Portfolio.id)
        .where(Holding.id == holding_id, Portfolio.user_id == user.id)
    )
    holding = result.scalar_one_or_none()
    if holding is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Holding not found or does not belong to the current user",
        )
    return holding
