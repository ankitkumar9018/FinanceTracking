"""Tests for the grounded portfolio context fed to the LLM assistant.

Covers, without any real LLM provider:
- ``build_portfolio_context`` returns "" for an empty account.
- ``build_portfolio_context`` includes real holdings, totals and diversification.
- ``chat`` injects that context into the provider's system prompt (stub provider).
- ``chat`` falls back to the plain system prompt when no DB session is given.
- ``chat`` returns the graceful offline message when no provider is available.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ml import llm_assistant
from app.ml.llm_assistant import (
    SYSTEM_PROMPT,
    ChatMessage,
    ChatResponse,
    _compose_system_prompt,
    chat,
)
from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.models.user import User
from app.services.ai_context_service import build_portfolio_context


async def _seed(db: AsyncSession, email: str = "ctx@example.com") -> User:
    user = User(email=email, password_hash="x", display_name="Ctx Tester")
    db.add(user)
    await db.flush()
    portfolio = Portfolio(user_id=user.id, name="Core", currency="INR")
    db.add(portfolio)
    await db.flush()
    db.add_all([
        Holding(
            portfolio_id=portfolio.id, stock_symbol="RELIANCE",
            stock_name="Reliance Industries", exchange="NSE", currency="INR",
            cumulative_quantity=10.0, average_price=2500.0, current_price=2800.0,
            sector="Energy",
        ),
        Holding(
            portfolio_id=portfolio.id, stock_symbol="TCS",
            stock_name="Tata Consultancy", exchange="NSE", currency="INR",
            cumulative_quantity=5.0, average_price=3500.0, current_price=3400.0,
            sector="IT",
        ),
    ])
    await db.flush()
    return user


class _StubProvider:
    """Captures the system prompt it is handed and returns a canned reply."""

    NAME = "stub"

    def __init__(self) -> None:
        self.seen_system_prompt: str | None = None

    async def chat(self, messages, system_prompt: str = "") -> ChatResponse:
        self.seen_system_prompt = system_prompt
        return ChatResponse(message="ok", provider=self.NAME, model="stub", tokens_used=1)


@pytest.mark.asyncio
async def test_context_empty_for_user_without_holdings(db: AsyncSession):
    user = User(email="empty-ctx@example.com", password_hash="x", display_name="Empty")
    db.add(user)
    await db.flush()
    assert await build_portfolio_context(user.id, db) == ""


@pytest.mark.asyncio
async def test_context_includes_holdings_totals_and_diversification(db: AsyncSession):
    user = await _seed(db)
    ctx = await build_portfolio_context(user.id, db)

    assert "Portfolio: Core (INR)" in ctx
    assert "RELIANCE" in ctx and "TCS" in ctx
    # Totals: invested = 10*2500 + 5*3500 = 42500
    assert "42,500" in ctx or "42500" in ctx
    # Diversification section is present with sector allocation
    assert "Diversification" in ctx
    assert "Sector allocation" in ctx
    assert "Energy" in ctx and "IT" in ctx


@pytest.mark.asyncio
async def test_chat_injects_context_into_system_prompt(db: AsyncSession, monkeypatch):
    user = await _seed(db, email="chatctx@example.com")
    stub = _StubProvider()

    async def _fake_active():
        return stub

    monkeypatch.setattr(llm_assistant, "get_active_provider", _fake_active)

    resp = await chat([ChatMessage(role="user", content="How am I doing?")], user.id, db)

    assert resp.provider == "stub"
    assert stub.seen_system_prompt is not None
    # The injected context block (marker only present when context is attached)
    # AND the real holdings reached the provider.
    assert "=== END PORTFOLIO CONTEXT ===" in stub.seen_system_prompt
    assert "RELIANCE" in stub.seen_system_prompt
    # Guardrails survive.
    assert "not financial advice" in stub.seen_system_prompt.lower()


@pytest.mark.asyncio
async def test_chat_without_db_uses_plain_prompt(monkeypatch):
    stub = _StubProvider()

    async def _fake_active():
        return stub

    monkeypatch.setattr(llm_assistant, "get_active_provider", _fake_active)

    await chat([ChatMessage(role="user", content="hi")], user_id=1, db=None)
    assert stub.seen_system_prompt == SYSTEM_PROMPT
    # No context block was attached (the injection marker is absent).
    assert "=== END PORTFOLIO CONTEXT ===" not in stub.seen_system_prompt


@pytest.mark.asyncio
async def test_chat_offline_when_no_provider(monkeypatch):
    async def _no_provider():
        return None

    monkeypatch.setattr(llm_assistant, "get_active_provider", _no_provider)
    resp = await chat([ChatMessage(role="user", content="hi")], user_id=1, db=None)
    assert resp.provider == "none"
    assert "offline" in resp.message.lower()


def test_compose_system_prompt():
    assert _compose_system_prompt("BASE", "") == "BASE"
    composed = _compose_system_prompt("BASE", "ctx-data")
    assert "BASE" in composed and "ctx-data" in composed
    assert "PORTFOLIO CONTEXT" in composed


@pytest.mark.asyncio
async def test_context_caps_large_portfolio(db: AsyncSession):
    """A portfolio with more than _MAX_HOLDINGS holdings is truncated in the
    per-holding list (but totals/diversification still cover everything)."""
    from app.services.ai_context_service import _MAX_HOLDINGS

    user = User(email="big@example.com", password_hash="x", display_name="Big")
    db.add(user)
    await db.flush()
    p = Portfolio(user_id=user.id, name="Big", currency="INR")
    db.add(p)
    await db.flush()
    for i in range(_MAX_HOLDINGS + 5):
        db.add(Holding(
            portfolio_id=p.id, stock_symbol=f"S{i}", stock_name=f"S{i}",
            exchange="NSE", currency="INR", cumulative_quantity=1.0,
            average_price=100.0, current_price=100.0, sector="IT",
        ))
    await db.flush()

    ctx = await build_portfolio_context(user.id, db)
    assert "more holdings not listed" in ctx
    # Individual holding bullet lines are bounded by the per-portfolio cap.
    assert ctx.count("\n- ") <= _MAX_HOLDINGS


@pytest.mark.asyncio
async def test_compute_portfolio_risk_batched_price_history(db: AsyncSession):
    """The risk DB path — refactored from a per-holding N+1 into one batched
    query — still computes metrics from stored PriceHistory for >1 holding."""
    from datetime import date, timedelta

    from app.ml.risk_calculator import compute_portfolio_risk
    from app.models.price_history import PriceHistory

    user = User(email="risk@example.com", password_hash="x", display_name="Risk")
    db.add(user)
    await db.flush()
    p = Portfolio(user_id=user.id, name="Risk P", currency="INR")
    db.add(p)
    await db.flush()
    db.add_all([
        Holding(portfolio_id=p.id, stock_symbol="AAA", stock_name="AAA",
                exchange="NSE", currency="INR", cumulative_quantity=10.0,
                average_price=100.0, current_price=110.0),
        Holding(portfolio_id=p.id, stock_symbol="BBB", stock_name="BBB",
                exchange="NSE", currency="INR", cumulative_quantity=5.0,
                average_price=200.0, current_price=190.0),
    ])
    await db.flush()

    base = date.today() - timedelta(days=60)
    for i in range(40):
        d = base + timedelta(days=i)
        ac = 100 + i * 0.5 + (i % 3)
        bc = 200 - i * 0.3 + (i % 2)
        db.add(PriceHistory(stock_symbol="AAA", exchange="NSE", date=d,
                            open=ac, high=ac + 1, low=ac - 1, close=ac, volume=1000))
        db.add(PriceHistory(stock_symbol="BBB", exchange="NSE", date=d,
                            open=bc, high=bc + 1, low=bc - 1, close=bc, volume=800))
    await db.flush()

    rm = await compute_portfolio_risk(user.id, p.id, db)
    # Metrics came from the batched price history (not the empty fallback).
    assert rm.volatility_annual is not None
    assert rm.max_drawdown is not None
