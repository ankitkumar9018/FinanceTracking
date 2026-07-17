"""Goal management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.goal import GoalCreate, GoalResponse, GoalUpdate
from app.services import fire_service
from app.services.goal_service import (
    create_goal,
    delete_goal,
    get_goal,
    get_goals,
    sip_projection,
    sync_goal_from_portfolio,
    update_goal,
)
from app.services.net_worth_service import get_net_worth

router = APIRouter()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/", response_model=list[GoalResponse])
async def list_goals_endpoint(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list:
    """List all financial goals for the current user."""
    goals = await get_goals(user_id=user.id, db=db)
    return [GoalResponse.from_goal(g) for g in goals]


@router.post("/", response_model=GoalResponse, status_code=status.HTTP_201_CREATED)
async def create_goal_endpoint(
    body: GoalCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> object:
    """Create a new financial goal."""
    goal = await create_goal(user_id=user.id, data=body, db=db)
    return GoalResponse.from_goal(goal)


# ---------------------------------------------------------------------------
# Calculators (FIRE + SIP step-up) — declared before /{goal_id} so the
# literal paths are not shadowed by the goal-id path parameter.
# ---------------------------------------------------------------------------


@router.get("/fire")
async def fire_projection_endpoint(
    monthly_contribution: float = Query(..., ge=0),
    annual_return_pct: float = Query(...),
    annual_expenses: float = Query(..., gt=0),
    current_net_worth: float | None = Query(None, ge=0),
    withdrawal_rate_pct: float = Query(4.0, gt=0),
    step_up_pct: float = Query(0.0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Project a path to FIRE (financial independence / early retirement).

    When ``current_net_worth`` is omitted it is sourced from the user's
    aggregated net worth.
    """
    net_worth = current_net_worth
    if net_worth is None:
        try:
            nw_data = await get_net_worth(user_id=user.id, db=db)
            net_worth = float(nw_data.get("total_net_worth", 0.0) or 0.0)
        except Exception:
            net_worth = 0.0

    result = fire_service.compute_fire(
        current_net_worth=net_worth,
        monthly_contribution=monthly_contribution,
        annual_return_pct=annual_return_pct,
        annual_expenses=annual_expenses,
        withdrawal_rate_pct=withdrawal_rate_pct,
        step_up_pct=step_up_pct,
    )
    result["current_net_worth"] = round(float(net_worth), 2)
    return result


@router.get("/sip-projection")
async def sip_projection_endpoint(
    monthly_sip: float = Query(..., ge=0),
    annual_return_pct: float = Query(...),
    years: int = Query(..., gt=0, le=100),
    current_amount: float = Query(0.0, ge=0),
    step_up_pct: float = Query(0.0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Project a SIP's corpus with vs. without an annual step-up."""
    return sip_projection(
        current_amount=current_amount,
        monthly_sip=monthly_sip,
        annual_return_pct=annual_return_pct,
        years=years,
        step_up_pct=step_up_pct,
    )


@router.get("/{goal_id}", response_model=GoalResponse)
async def get_goal_endpoint(
    goal_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> object:
    """Get a single financial goal by ID."""
    try:
        goal = await get_goal(goal_id=goal_id, user_id=user.id, db=db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    return GoalResponse.from_goal(goal)


@router.put("/{goal_id}", response_model=GoalResponse)
async def update_goal_endpoint(
    goal_id: int,
    body: GoalUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> object:
    """Update a financial goal."""
    try:
        goal = await update_goal(goal_id=goal_id, user_id=user.id, data=body, db=db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    return GoalResponse.from_goal(goal)


@router.delete("/{goal_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_goal_endpoint(
    goal_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a financial goal."""
    try:
        await delete_goal(goal_id=goal_id, user_id=user.id, db=db)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )


@router.post("/{goal_id}/sync", response_model=GoalResponse)
async def sync_goal_endpoint(
    goal_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> object:
    """Sync goal's current_amount from its linked portfolio value."""
    try:
        goal = await sync_goal_from_portfolio(
            goal_id=goal_id, user_id=user.id, db=db
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    return GoalResponse.from_goal(goal)
