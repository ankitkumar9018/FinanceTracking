"""AI chat and ML prediction endpoints."""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)

router = APIRouter()

# Cost controls: only the most recent messages are replayed to the provider,
# and the (expensive) portfolio context is cached per session for a short TTL.
HISTORY_LIMIT = 20
CTX_CACHE_TTL_SECONDS = 300


class ChatMessageRequest(BaseModel):
    message: str
    session_id: int | None = None


class ProposedActionPayload(BaseModel):
    id: str
    type: str
    summary: str
    params: dict


class ChatMessageResponse(BaseModel):
    response: str
    provider: str
    model: str
    session_id: int
    proposed_action: ProposedActionPayload | None = None


class ActionSessionRef(BaseModel):
    session_id: int | None = None


async def _get_cached_context(
    session: ChatSession, user_id: int, db: AsyncSession
) -> str:
    """Portfolio context for the system prompt, cached in ``session.context``.

    Rebuilt when older than ``CTX_CACHE_TTL_SECONDS``. The JSON column has no
    mutation tracking, so ``session.context`` is reassigned with a new dict to
    persist the cache.
    """
    from app.services.ai_context_service import build_portfolio_context

    ctx = dict(session.context or {})
    cache = ctx.get("ctx_cache") or {}
    at_raw = cache.get("at")
    if isinstance(at_raw, str):
        try:
            at = datetime.fromisoformat(at_raw)
            if at.tzinfo is None:
                at = at.replace(tzinfo=UTC)
            age = (datetime.now(UTC) - at).total_seconds()
            if 0 <= age < CTX_CACHE_TTL_SECONDS:
                return str(cache.get("text") or "")
        except ValueError:
            pass

    text = await build_portfolio_context(user_id, db)
    ctx["ctx_cache"] = {"text": text, "at": datetime.now(UTC).isoformat()}
    session.context = ctx
    return text


@router.post("/chat", response_model=ChatMessageResponse)
async def send_chat_message(
    body: ChatMessageRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Send a message to the AI assistant.

    Before asking the LLM for a normal reply, a lightweight intent pass checks
    whether the message asks for an action (add transaction / add holding /
    create alert). Detected actions are NEVER executed directly: they are
    returned as ``proposed_action`` and stored in the session until the user
    confirms via ``POST /ai/chat/actions/{id}/execute``.
    """
    from app.ml.llm_assistant import (
        SYSTEM_PROMPT,
        ChatMessage,
        ChatResponse,
        _compose_system_prompt,
        chat,
        get_active_provider,
    )
    from app.services import ai_action_service

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
            # A stale/foreign session id must not silently fork a new session
            # (the client would keep sending the old id and fragment the
            # conversation, answered with no history each time).
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Chat session not found",
            )

    if session is None:
        session = ChatSession(user_id=user.id, messages=[], context={})
        db.add(session)
        await db.flush()

    provider = await get_active_provider()

    # Intent pass (requires an active provider; skipped — and fast — without one)
    proposal = None
    note = None
    if provider is not None:
        detection = await ai_action_service.detect_action(
            body.message, user.id, db, provider=provider
        )
        proposal, note = detection.proposal, detection.note

    proposed_payload: dict | None = None
    if proposal is not None and provider is not None:
        # Confirmation turn: the reply is composed server-side (never trusted
        # to the LLM) and the proposal is parked in the session until the user
        # confirms or dismisses it.
        ai_action_service.store_pending_action(session, proposal)
        response = ChatResponse(
            message=(
                f"I can do that, but it needs your confirmation first: "
                f"{proposal.summary} Confirm to execute this action, or "
                "dismiss it."
            ),
            provider=provider.NAME,
            model=str(getattr(provider, "model", provider.NAME)),
        )
        proposed_payload = {
            "id": proposal.id,
            "type": proposal.type,
            "summary": proposal.summary,
            "params": proposal.params,
        }
    elif note is not None and provider is not None:
        # Action-shaped but unresolvable (ambiguous symbol, unknown holding,
        # no portfolio): reply with the server-composed explanation.
        response = ChatResponse(
            message=note,
            provider=provider.NAME,
            model=str(getattr(provider, "model", provider.NAME)),
        )
    elif provider is None:
        # Delegate to chat() for the canonical graceful-offline message.
        response = await chat(
            [ChatMessage(role="user", content=body.message)], user.id, None
        )
    else:
        # Normal reply: replay only the most recent history and reuse the
        # cached portfolio context when it is fresh enough.
        history = [
            ChatMessage(role=m["role"], content=m["content"])
            for m in (session.messages or [])
        ]
        history.append(ChatMessage(role="user", content=body.message))
        history = history[-HISTORY_LIMIT:]

        context_text = await _get_cached_context(session, user.id, db)
        system_prompt = _compose_system_prompt(SYSTEM_PROMPT, context_text)
        try:
            response = await provider.chat(history, system_prompt=system_prompt)
        except Exception as exc:
            logger.error("LLM chat failed with %s: %r", provider.NAME, exc)
            response = ChatResponse(
                message=(
                    "I encountered an error processing your request. "
                    f"The {provider.NAME} provider returned an error. "
                    "Please try again or switch providers in Settings."
                ),
                provider=provider.NAME,
                model="error",
                tokens_used=0,
            )

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
        "proposed_action": proposed_payload,
    }


# ---------------------------------------------------------------------------
# Confirm-before-execute actions
# ---------------------------------------------------------------------------

async def _find_pending_action(
    action_id: str,
    session_id: int | None,
    user: User,
    db: AsyncSession,
) -> tuple[ChatSession, dict]:
    """Locate a live pending action in the user's sessions (404 otherwise).

    Expired entries are treated as missing, so a foreign or stale ``action_id``
    and an expired one are indistinguishable to the caller (both 404).
    """
    from app.services import ai_action_service

    stmt = select(ChatSession).where(ChatSession.user_id == user.id)
    if session_id is not None:
        stmt = stmt.where(ChatSession.id == session_id)
    result = await db.execute(stmt)
    for session in result.scalars().all():
        entry = ai_action_service.get_pending_action(session, action_id)
        if entry is not None:
            return session, entry
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Action not found or expired",
    )


@router.post("/chat/actions/{action_id}/execute")
async def execute_chat_action(
    action_id: str,
    body: ActionSessionRef | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Execute a previously proposed action after user confirmation.

    Params are re-validated and ownership re-checked; execution goes through
    the same code paths as the manual routes (incl. the SELL ledger guard).
    """
    from app.services import ai_action_service

    session, entry = await _find_pending_action(
        action_id, body.session_id if body else None, user, db
    )
    detail, result = await ai_action_service.execute_action(
        str(entry.get("type")), dict(entry.get("params") or {}), user, db
    )
    ai_action_service.remove_pending_action(session, action_id)
    await db.flush()
    return {"status": "executed", "detail": detail, "result": result}


@router.post(
    "/chat/actions/{action_id}/dismiss",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def dismiss_chat_action(
    action_id: str,
    body: ActionSessionRef | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Dismiss (discard) a previously proposed action without executing it."""
    from app.services import ai_action_service

    session, _entry = await _find_pending_action(
        action_id, body.session_id if body else None, user, db
    )
    ai_action_service.remove_pending_action(session, action_id)
    await db.flush()


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
    """Get AI-generated portfolio insights, grounded in the user's real data.

    The rich portfolio context (holdings, P&L, diversification, allocation
    drift, and risk metrics) is compiled and injected into the system prompt by
    ``chat`` itself via ``build_portfolio_context`` — here we only pose the
    analysis question, so the context is built exactly once.
    """
    from app.ml.llm_assistant import ChatMessage, chat
    from app.models.holding import Holding
    from app.models.portfolio import Portfolio

    # Cheap existence check so an empty account gets a helpful message instead
    # of paying an LLM round-trip.
    exists = await db.execute(
        select(Holding.id)
        .join(Portfolio, Holding.portfolio_id == Portfolio.id)
        .where(Portfolio.user_id == user.id)
        .limit(1)
    )
    if exists.first() is None:
        return {
            "insights": "No holdings found. Start by adding stocks to your portfolio."
        }

    messages = [
        ChatMessage(
            role="user",
            content=(
                "Analyze my portfolio and give 3-5 specific, actionable insights. "
                "Call out concentration or allocation risks, notable gains or losses, "
                "and anything that needs attention. Ground every point in my actual "
                "numbers. Keep it educational — not financial advice."
            ),
        )
    ]

    response = await chat(messages, user.id, db)

    return {
        "insights": response.message,
        "provider": response.provider,
    }
