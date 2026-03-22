"""Goal service: CRUD, SIP calculation, portfolio sync."""

from __future__ import annotations

import logging
import math
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.goal import Goal
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.schemas.goal import GoalCreate, GoalUpdate

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure helper: monthly SIP calculation
# ---------------------------------------------------------------------------

def _calculate_monthly_sip(
    target: float,
    current: float,
    months_remaining: int,
    annual_return: float = 0.12,
) -> float | None:
    """Calculate the monthly SIP needed to reach a target amount.

    Uses the future-value-of-annuity formula:
        FV = PMT * [((1+r)^n - 1) / r]
    where FV is the shortfall (target - future value of current), r is monthly
    return, and n is months remaining.

    Returns None when months_remaining <= 0.
    """
    if months_remaining <= 0:
        return None

    monthly_rate = annual_return / 12

    # Future value of current savings
    fv_current = current * ((1 + monthly_rate) ** months_remaining)

    shortfall = target - fv_current
    if shortfall <= 0:
        # Already on track — no SIP needed
        return 0.0

    if monthly_rate == 0:
        return round(shortfall / months_remaining, 4)

    # PMT = shortfall * r / ((1+r)^n - 1)
    denominator = ((1 + monthly_rate) ** months_remaining) - 1
    if denominator == 0:
        return round(shortfall / months_remaining, 4)

    sip = shortfall * monthly_rate / denominator
    return round(sip, 4)


def _months_until(target_date: date | None) -> int:
    """Return months from today until target_date. 0 if None or past."""
    if target_date is None:
        return 0
    today = date.today()
    diff = (target_date.year - today.year) * 12 + (target_date.month - today.month)
    return max(diff, 0)


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

async def create_goal(
    user_id: int,
    data: GoalCreate,
    db: AsyncSession,
) -> Goal:
    """Create a new financial goal and auto-calculate monthly SIP needed."""
    months = _months_until(data.target_date)
    sip = _calculate_monthly_sip(
        target=data.target_amount,
        current=0.0,
        months_remaining=months,
    )

    goal = Goal(
        user_id=user_id,
        name=data.name,
        target_amount=data.target_amount,
        current_amount=0,
        target_date=data.target_date,
        category=data.category.upper(),
        linked_portfolio_id=data.linked_portfolio_id,
        monthly_sip_needed=sip,
    )
    db.add(goal)
    await db.flush()
    await db.refresh(goal)
    return goal


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

async def update_goal(
    goal_id: int,
    user_id: int,
    data: GoalUpdate,
    db: AsyncSession,
) -> Goal:
    """Update a goal with ownership check; recalc SIP if target/date changed."""
    goal = await _get_goal_or_raise(goal_id, user_id, db)

    update_fields = data.model_dump(exclude_unset=True)
    if "category" in update_fields and update_fields["category"] is not None:
        update_fields["category"] = update_fields["category"].upper()

    for field, value in update_fields.items():
        setattr(goal, field, value)

    # Recalculate SIP whenever target_amount, current_amount, or target_date change
    recalc_triggers = {"target_amount", "current_amount", "target_date"}
    if recalc_triggers & update_fields.keys():
        months = _months_until(goal.target_date)
        goal.monthly_sip_needed = _calculate_monthly_sip(
            target=float(goal.target_amount),
            current=float(goal.current_amount),
            months_remaining=months,
        )

    # Auto-achieve check
    if float(goal.current_amount) >= float(goal.target_amount):
        goal.is_achieved = True

    await db.flush()
    await db.refresh(goal)
    return goal


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

async def delete_goal(
    goal_id: int,
    user_id: int,
    db: AsyncSession,
) -> None:
    """Delete a goal with ownership check."""
    goal = await _get_goal_or_raise(goal_id, user_id, db)
    await db.delete(goal)
    await db.flush()


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

async def get_goals(user_id: int, db: AsyncSession) -> list[Goal]:
    """List all goals for the user."""
    result = await db.execute(
        select(Goal)
        .where(Goal.user_id == user_id)
        .order_by(Goal.created_at.desc())
    )
    return list(result.scalars().all())


async def get_goal(goal_id: int, user_id: int, db: AsyncSession) -> Goal:
    """Get a single goal with ownership check."""
    return await _get_goal_or_raise(goal_id, user_id, db)


# ---------------------------------------------------------------------------
# Sync from portfolio
# ---------------------------------------------------------------------------

async def sync_goal_from_portfolio(
    goal_id: int,
    user_id: int,
    db: AsyncSession,
) -> Goal:
    """Update current_amount from the linked portfolio's total value.

    Total value = sum(holding.cumulative_quantity * (holding.current_price or holding.average_price))
    for all holdings in the linked portfolio.
    """
    goal = await _get_goal_or_raise(goal_id, user_id, db)

    if goal.linked_portfolio_id is None:
        raise ValueError("Goal is not linked to any portfolio")

    # Verify portfolio ownership
    port_result = await db.execute(
        select(Portfolio).where(
            Portfolio.id == goal.linked_portfolio_id,
            Portfolio.user_id == user_id,
        )
    )
    portfolio = port_result.scalar_one_or_none()
    if portfolio is None:
        raise ValueError("Linked portfolio not found or does not belong to the current user")

    # Sum holdings value
    holdings_result = await db.execute(
        select(Holding).where(Holding.portfolio_id == portfolio.id)
    )
    holdings = holdings_result.scalars().all()

    total_value = 0.0
    for h in holdings:
        qty = float(h.cumulative_quantity)
        price = float(h.current_price) if h.current_price is not None else float(h.average_price)
        total_value += qty * price

    goal.current_amount = total_value

    # Recalculate SIP
    months = _months_until(goal.target_date)
    goal.monthly_sip_needed = _calculate_monthly_sip(
        target=float(goal.target_amount),
        current=total_value,
        months_remaining=months,
    )

    # Auto-achieve check
    if total_value >= float(goal.target_amount):
        goal.is_achieved = True

    await db.flush()
    await db.refresh(goal)
    return goal


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _get_goal_or_raise(
    goal_id: int,
    user_id: int,
    db: AsyncSession,
) -> Goal:
    """Fetch a goal ensuring ownership, raise ValueError if not found."""
    result = await db.execute(
        select(Goal).where(Goal.id == goal_id, Goal.user_id == user_id)
    )
    goal = result.scalar_one_or_none()
    if goal is None:
        raise ValueError("Goal not found or does not belong to the current user")
    return goal
