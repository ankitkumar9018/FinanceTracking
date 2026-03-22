"""AI chat and ML prediction endpoints."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.database import get_db
from app.models.chat_session import ChatSession
from app.models.user import User

router = APIRouter()


class ChatMessageRequest(BaseModel):
    message: str
    session_id: int | None = None


class ChatMessageResponse(BaseModel):
    response: str
    provider: str
    model: str
    session_id: int


@router.post("/chat", response_model=ChatMessageResponse)
async def send_chat_message(
    body: ChatMessageRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Send a message to the AI assistant."""
    from app.ml.llm_assistant import ChatMessage, chat

    # Get or create session
    session = None
    if body.session_id:
        result = await db.execute(
            select(ChatSession).where(
                ChatSession.id == body.session_id,
                ChatSession.user_id == user.id,
            )
        )
        session = result.scalar_one_or_none()

    if session is None:
        session = ChatSession(user_id=user.id, messages=[], context={})
        db.add(session)
        await db.flush()

    # Build message history
    history = [
        ChatMessage(role=m["role"], content=m["content"])
        for m in (session.messages or [])
    ]
    history.append(ChatMessage(role="user", content=body.message))

    # Get AI response
    response = await chat(history, user.id, db)

    # Save to session
    now = datetime.now(UTC).isoformat()
    messages = list(session.messages or [])
    messages.append({"role": "user", "content": body.message, "timestamp": now})
    messages.append(
        {"role": "assistant", "content": response.message, "timestamp": now}
    )
    session.messages = messages
    await db.flush()

    return {
        "response": response.message,
        "provider": response.provider,
        "model": response.model,
        "session_id": session.id,
    }


@router.get("/sessions")
async def list_chat_sessions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    """List user's chat sessions."""
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.user_id == user.id)
        .order_by(ChatSession.created_at.desc())
    )
    sessions = result.scalars().all()

    return [
        {
            "id": s.id,
            "message_count": len(s.messages) if s.messages else 0,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "last_message": (
                s.messages[-1]["content"][:100] if s.messages else None
            ),
        }
        for s in sessions
    ]


@router.get("/sessions/{session_id}")
async def get_chat_session(
    session_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get a specific chat session with all messages."""
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user.id,
        )
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    return {
        "id": session.id,
        "messages": session.messages or [],
        "context": session.context or {},
        "created_at": session.created_at.isoformat() if session.created_at else None,
    }


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_chat_session(
    session_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a chat session."""
    result = await db.execute(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user.id,
        )
    )
    session = result.scalar_one_or_none()
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )
    await db.delete(session)
    await db.flush()


@router.get("/status")
async def ai_status(
    user: User = Depends(get_current_user),
) -> dict:
    """Check AI provider availability."""
    from app.ml.llm_assistant import check_provider_status

    status_map = await check_provider_status()
    active = next(
        (name for name, available in status_map.items() if available), None
    )

    return {
        "providers": status_map,
        "active_provider": active,
        "ai_available": active is not None,
        "configured_provider": (
            settings.llm_provider
            if hasattr(settings, "llm_provider")
            else "none"
        ),
    }


@router.get("/prediction/{symbol}")
async def get_prediction(
    symbol: str,
    exchange: str = Query(default="NSE"),
    days_ahead: int = Query(default=5, ge=1, le=30),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get price prediction for a stock."""
    from app.ml.price_predictor import predict_prices

    result = await predict_prices(symbol, exchange, db, days_ahead)
    return asdict(result)


@router.get("/anomalies/{symbol}")
async def get_anomalies(
    symbol: str,
    exchange: str = Query(default="NSE"),
    days: int = Query(default=90, ge=7, le=365),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Detect anomalies in stock price/volume."""
    from app.ml.anomaly_detector import detect_anomalies

    result = await detect_anomalies(symbol, exchange, db, days)
    return asdict(result)


@router.get("/sentiment/{symbol}")
async def get_sentiment(
    symbol: str,
    user: User = Depends(get_current_user),
) -> dict:
    """Get news sentiment analysis for a stock."""
    from app.ml.sentiment_analyzer import analyze_sentiment

    result = await analyze_sentiment(symbol)
    return asdict(result)


@router.get("/insights")
async def get_portfolio_insights(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Get AI-generated portfolio insights."""
    from app.ml.llm_assistant import ChatMessage, chat
    from app.models.holding import Holding
    from app.models.portfolio import Portfolio

    result = await db.execute(
        select(Portfolio).where(Portfolio.user_id == user.id)
    )
    portfolios = result.scalars().all()

    holdings_summary = []
    for p in portfolios:
        h_result = await db.execute(
            select(Holding).where(Holding.portfolio_id == p.id)
        )
        holdings = h_result.scalars().all()
        for h in holdings:
            pnl = 0.0
            if h.current_price and h.average_price:
                pnl = (
                    (float(h.current_price) - float(h.average_price))
                    / float(h.average_price)
                    * 100
                )
            holdings_summary.append(
                f"{h.stock_symbol}: qty={h.cumulative_quantity}, "
                f"avg=INR{h.average_price}, current=INR{h.current_price or 'N/A'}, "
                f"P&L={pnl:.1f}%, action={h.action_needed}"
            )

    if not holdings_summary:
        return {
            "insights": "No holdings found. Start by adding stocks to your portfolio."
        }

    context = "User's portfolio:\n" + "\n".join(holdings_summary)

    messages = [
        ChatMessage(
            role="user",
            content=(
                "Based on this portfolio data, provide 3-5 brief actionable "
                f"insights:\n\n{context}"
            ),
        )
    ]

    response = await chat(messages, user.id, db)

    return {
        "insights": response.message,
        "provider": response.provider,
        "holdings_analyzed": len(holdings_summary),
    }
