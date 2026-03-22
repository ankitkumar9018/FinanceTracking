"""Goal management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.database import get_db
from app.models.user import User
from app.schemas.goal import GoalCreate, GoalResponse, GoalUpdate
from app.services.goal_service import (
    create_goal,
    delete_goal,
    get_goal,
    get_goals,
    sync_goal_from_portfolio,
    update_goal,
)

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
