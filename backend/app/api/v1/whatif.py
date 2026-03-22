"""What-If Simulator API — simulate historical investment returns."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.whatif import WhatIfRequest, WhatIfResponse
from app.services.whatif_service import simulate

router = APIRouter()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.post("/simulate", response_model=WhatIfResponse)
async def run_simulation(
    body: WhatIfRequest,
    user: User = Depends(get_current_user),
) -> dict:
    """Run a what-if investment simulation.

    Simulates buying a stock on ``start_date`` with ``invest_amount`` and
    calculates the returns as of ``end_date`` (defaults to today).

    Optionally compares against a benchmark index (NIFTY50, SENSEX, DAX, S&P500, NASDAQ).
    """
    try:
        result = await simulate(
            symbol=body.symbol.upper().strip(),
            exchange=body.exchange.upper().strip(),
            invest_amount=body.invest_amount,
            start_date=body.start_date,
            end_date=body.end_date,
            benchmark=body.benchmark,
        )
        return result
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        ) from e
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Simulation failed: {e}",
        ) from e
