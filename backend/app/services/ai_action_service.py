"""Confirm-before-execute agentic actions for the AI chat.

``detect_action`` runs a lightweight LLM intent pass over the user's message
and, when it clearly asks for one of the supported actions, returns a fully
validated, ownership-checked :class:`ProposedAction`. The proposal is stored
in the chat session's ``context`` JSON and only executed after the user
explicitly confirms via ``POST /ai/chat/actions/{id}/execute`` — the LLM can
never mutate data directly, and every parameter the LLM produced is
re-validated server-side both at proposal time and again at execution time.

Execution reuses the REAL route code paths (the transactions / holdings /
alerts create handlers), so the ledger sell-guard, the cumulative-holding
recompute and the ownership checks are byte-for-byte the same as the manual
UI flows — nothing is forked.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any, Literal

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.holding import Holding
from app.models.portfolio import Portfolio
from app.schemas.alert import AlertType, Channel
from app.utils.dates import parse_date

if TYPE_CHECKING:
    from app.ml.llm_assistant import LLMProvider
    from app.models.chat_session import ChatSession
    from app.models.user import User

logger = logging.getLogger(__name__)

ACTION_TYPES = ("add_transaction", "add_holding", "create_alert")

DETECTION_TIMEOUT_SECONDS = 20.0
PENDING_TTL_SECONDS = 900  # proposals expire 15 minutes after creation
MAX_PENDING_ACTIONS = 5  # per chat session

# The stub-detectable marker phrase "intent detector" is part of the contract
# with the tests; keep it if the prompt is reworded.
DETECTION_PROMPT = """You are an intent detector for a portfolio tracker. \
Decide whether the user's message is a clear request to PERFORM exactly one of these actions:

1. "add_transaction" — record a BUY or SELL of a stock the user already holds.
   params: {"transaction_type": "BUY" or "SELL", "symbol": "<ticker>", \
"exchange": "NSE"|"BSE"|"XETRA" (only if stated), "quantity": <number>, \
"price": <number per unit>, "date": "YYYY-MM-DD" (only if stated), \
"brokerage": <number, only if stated>}
2. "add_holding" — add a brand-new stock position.
   params: {"symbol": "<ticker>", "stock_name": "<company name, if stated>", \
"exchange": "NSE"|"BSE"|"XETRA" (use "NSE" for Indian stocks when unstated), \
"quantity": <number>, "average_price": <number>, \
"portfolio": "<portfolio name, only if stated>", "sector": "<only if stated>"}
3. "create_alert" — create a price or RSI alert on a holding.
   params: {"symbol": "<ticker>", "alert_type": "PRICE_RANGE"|"RSI"|"CUSTOM", \
"condition": {"above": <price>} or {"below": <price>} or {"rsi_above": <n>} or {"rsi_below": <n>}, \
"channels": ["in_app","email","telegram","whatsapp","sms"] (only if stated)}

If (and only if) the message clearly asks to perform one of these actions and \
states the required numbers, respond with ONLY minified JSON on one line: \
{"type":"<action>","params":{...}}
No prose, no markdown, no code fences.
For anything else — questions, analysis, chit-chat, unclear or hypothetical \
requests — respond with exactly: NONE"""


# ---------------------------------------------------------------------------
# Result containers
# ---------------------------------------------------------------------------

@dataclass
class ProposedAction:
    """A validated, ownership-checked action awaiting user confirmation."""

    type: str
    summary: str
    params: dict
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class DetectionResult:
    """Outcome of the intent pass.

    ``proposal`` is set when a valid action was detected; ``note`` carries a
    server-composed reply when the request was action-shaped but could not be
    resolved (ambiguous symbol, no matching holding, no portfolio). Both are
    ``None`` for a plain conversational message.
    """

    proposal: ProposedAction | None = None
    note: str | None = None


# ---------------------------------------------------------------------------
# Per-action parameter models (server-side validation of LLM output)
# ---------------------------------------------------------------------------

def _default_channels() -> list[Channel]:
    return ["in_app"]


class AddTransactionParams(BaseModel):
    transaction_type: Literal["BUY", "SELL"]
    symbol: str = Field(min_length=1, max_length=50)
    exchange: str | None = Field(default=None, max_length=20)
    quantity: float = Field(gt=0)
    price: float = Field(gt=0)
    date: str | None = None  # normalised to ISO by the validator
    brokerage: float = Field(default=0.0, ge=0)
    notes: str | None = Field(default=None, max_length=500)
    # Resolved server-side from symbol+exchange; never trusted from the LLM.
    holding_id: int | None = None

    @field_validator("symbol", "exchange")
    @classmethod
    def _normalise(cls, v: str | None) -> str | None:
        return v.upper().strip() if isinstance(v, str) else v

    @field_validator("date")
    @classmethod
    def _parseable_date(cls, v: str | None) -> str | None:
        if v is None:
            return None
        parsed = parse_date(v)
        if parsed is None:
            raise ValueError(f"unparseable date: {v!r}")
        return parsed.isoformat()


class AddHoldingParams(BaseModel):
    symbol: str = Field(min_length=1, max_length=50)
    stock_name: str | None = Field(default=None, max_length=255)
    exchange: str = Field(min_length=1, max_length=20)
    quantity: float = Field(gt=0)
    average_price: float = Field(gt=0)
    portfolio: str | None = Field(default=None, max_length=255)  # name hint
    sector: str | None = Field(default=None, max_length=100)
    currency: str | None = Field(default=None, max_length=10)
    # Resolved server-side; never trusted from the LLM.
    portfolio_id: int | None = None

    @field_validator("symbol", "exchange")
    @classmethod
    def _normalise(cls, v: str) -> str:
        return v.upper().strip()


class CreateAlertParams(BaseModel):
    symbol: str | None = Field(default=None, max_length=50)
    exchange: str | None = Field(default=None, max_length=20)
    alert_type: AlertType = "PRICE_RANGE"
    condition: dict[str, Any]
    channels: list[Channel] = Field(default_factory=_default_channels)
    # Resolved server-side; never trusted from the LLM.
    holding_id: int | None = None

    @field_validator("symbol", "exchange")
    @classmethod
    def _normalise(cls, v: str | None) -> str | None:
        return v.upper().strip() if isinstance(v, str) else v

    @field_validator("condition")
    @classmethod
    def _non_empty(cls, v: dict) -> dict:
        if not v:
            raise ValueError("alert condition must not be empty")
        return v


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict | None:
    """Parse the first balanced ``{...}`` block; None on any failure."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    parsed = json.loads(text[start : i + 1])
                except json.JSONDecodeError:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


async def detect_action(
    message: str,
    user_id: int,
    db: AsyncSession,
    provider: LLMProvider | None = None,
) -> DetectionResult:
    """Run the LLM intent pass and return a validated proposal (or nothing).

    Without an active LLM provider, detection is skipped entirely and this
    returns fast. Any parse/validation/resolution failure yields *no*
    proposal — a broken proposal is never surfaced.
    """
    from app.ml.llm_assistant import ChatMessage, get_active_provider

    if provider is None:
        provider = await get_active_provider()
    if provider is None:
        return DetectionResult()

    try:
        response = await asyncio.wait_for(
            provider.chat(
                [ChatMessage(role="user", content=message)],
                system_prompt=DETECTION_PROMPT,
            ),
            timeout=DETECTION_TIMEOUT_SECONDS,
        )
    except Exception as exc:  # timeout, provider error — never break the chat
        logger.debug("ai-action: intent pass failed: %s", exc)
        return DetectionResult()

    raw = _extract_json(response.message or "")
    if raw is None:
        return DetectionResult()
    action_type = raw.get("type")
    params = raw.get("params")
    if action_type not in ACTION_TYPES or not isinstance(params, dict):
        return DetectionResult()

    try:
        if action_type == "add_transaction":
            return await _propose_transaction(params, user_id, db)
        if action_type == "add_holding":
            return await _propose_holding(params, user_id, db)
        return await _propose_alert(params, user_id, db)
    except ValidationError as exc:
        logger.debug("ai-action: invalid %s params: %s", action_type, exc)
        return DetectionResult()


async def _matching_holdings(
    symbol: str, exchange: str | None, user_id: int, db: AsyncSession
) -> list[Holding]:
    stmt = (
        select(Holding)
        .join(Portfolio, Holding.portfolio_id == Portfolio.id)
        .where(Portfolio.user_id == user_id, Holding.stock_symbol == symbol)
    )
    if exchange:
        stmt = stmt.where(Holding.exchange == exchange)
    result = await db.execute(stmt)
    return list(result.scalars().all())


def _holding_result(
    symbol: str, exchange: str | None, holdings: list[Holding]
) -> DetectionResult | Holding:
    """Map a symbol lookup to a unique holding or a server-composed note."""
    if not holdings:
        where = f" on {exchange}" if exchange else ""
        return DetectionResult(
            note=(
                f"I couldn't find a holding for {symbol}{where} in your "
                "portfolios, so I haven't set anything up. If it's a new "
                "position, ask me to add it as a holding first."
            )
        )
    if len(holdings) > 1:
        places = ", ".join(
            f"{h.stock_symbol} ({h.exchange}, portfolio #{h.portfolio_id})"
            for h in holdings
        )
        return DetectionResult(
            note=(
                f"You hold {symbol} in more than one place ({places}), so I "
                "haven't set anything up. Please specify the exchange or "
                "portfolio and ask again."
            )
        )
    return holdings[0]


async def _propose_transaction(
    params: dict, user_id: int, db: AsyncSession
) -> DetectionResult:
    p = AddTransactionParams.model_validate(params)
    found = _holding_result(
        p.symbol, p.exchange, await _matching_holdings(p.symbol, p.exchange, user_id, db)
    )
    if isinstance(found, DetectionResult):
        return found
    p.holding_id = found.id
    p.exchange = found.exchange
    if p.date is None:
        p.date = date.today().isoformat()
    verb = "Buy" if p.transaction_type == "BUY" else "Sell"
    brokerage = f" (brokerage {p.brokerage:g})" if p.brokerage else ""
    summary = (
        f"{verb} {p.quantity:g} {p.symbol} ({p.exchange}) at {p.price:g} "
        f"on {p.date}{brokerage}."
    )
    return DetectionResult(
        proposal=ProposedAction(
            type="add_transaction", summary=summary, params=p.model_dump()
        )
    )


async def _propose_holding(
    params: dict, user_id: int, db: AsyncSession
) -> DetectionResult:
    p = AddHoldingParams.model_validate(params)

    result = await db.execute(select(Portfolio).where(Portfolio.user_id == user_id))
    portfolios = list(result.scalars().all())
    target: Portfolio | None = None
    if p.portfolio:
        wanted = p.portfolio.strip().lower()
        matches = [pf for pf in portfolios if (pf.name or "").strip().lower() == wanted]
        target = matches[0] if len(matches) == 1 else None
    else:
        defaults = [pf for pf in portfolios if pf.is_default]
        if len(defaults) == 1:
            target = defaults[0]
        elif len(portfolios) == 1:
            target = portfolios[0]
    if target is None:
        return DetectionResult(
            note=(
                "I couldn't work out which portfolio this new holding should "
                "go into, so I haven't set anything up. Please name the "
                "portfolio and ask again."
            )
        )

    p.portfolio_id = target.id
    summary = (
        f"Add {p.quantity:g} {p.symbol} ({p.exchange}) at average price "
        f"{p.average_price:g} to portfolio '{target.name}'."
    )
    return DetectionResult(
        proposal=ProposedAction(
            type="add_holding", summary=summary, params=p.model_dump()
        )
    )


async def _propose_alert(
    params: dict, user_id: int, db: AsyncSession
) -> DetectionResult:
    p = CreateAlertParams.model_validate(params)
    if not p.symbol:
        return DetectionResult(
            note=(
                "I can set up an alert, but I need to know which holding it "
                "is for — please mention the stock symbol."
            )
        )
    found = _holding_result(
        p.symbol, p.exchange, await _matching_holdings(p.symbol, p.exchange, user_id, db)
    )
    if isinstance(found, DetectionResult):
        return found
    p.holding_id = found.id
    p.exchange = found.exchange
    summary = (
        f"Create a {p.alert_type} alert on {p.symbol} ({p.exchange}) with "
        f"condition {json.dumps(p.condition)}, notifying via "
        f"{', '.join(p.channels)}."
    )
    return DetectionResult(
        proposal=ProposedAction(
            type="create_alert", summary=summary, params=p.model_dump()
        )
    )


# ---------------------------------------------------------------------------
# Pending-action storage in ChatSession.context (plain JSON column: always
# reassign ``session.context`` with a new dict so the change is persisted)
# ---------------------------------------------------------------------------

def _entry_expired(entry: dict, now: datetime) -> bool:
    try:
        created = datetime.fromisoformat(str(entry.get("created_at")))
    except (TypeError, ValueError):
        return True
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return (now - created).total_seconds() > PENDING_TTL_SECONDS


def store_pending_action(session: ChatSession, proposal: ProposedAction) -> None:
    """Add a proposal to the session's pending map (pruned + capped at 5)."""
    now = datetime.now(UTC)
    ctx = dict(session.context or {})
    pending = {
        k: v
        for k, v in dict(ctx.get("pending_actions") or {}).items()
        if isinstance(v, dict) and not _entry_expired(v, now)
    }
    while len(pending) >= MAX_PENDING_ACTIONS:
        oldest = min(pending, key=lambda k: str(pending[k].get("created_at", "")))
        pending.pop(oldest)
    pending[proposal.id] = {
        "type": proposal.type,
        "params": proposal.params,
        "summary": proposal.summary,
        "created_at": now.isoformat(),
    }
    ctx["pending_actions"] = pending
    session.context = ctx


def get_pending_action(session: ChatSession, action_id: str) -> dict | None:
    """Return a live pending entry, or None (expired entries are dropped)."""
    ctx = session.context or {}
    pending = ctx.get("pending_actions") or {}
    entry = pending.get(action_id)
    if not isinstance(entry, dict):
        return None
    if _entry_expired(entry, datetime.now(UTC)):
        remove_pending_action(session, action_id)
        return None
    return entry


def remove_pending_action(session: ChatSession, action_id: str) -> None:
    ctx = dict(session.context or {})
    pending = dict(ctx.get("pending_actions") or {})
    if action_id in pending:
        pending.pop(action_id)
        ctx["pending_actions"] = pending
        session.context = ctx


# ---------------------------------------------------------------------------
# Execution — via the real route code paths (never forked)
# ---------------------------------------------------------------------------

async def execute_action(
    action_type: str, params: dict, user: User, db: AsyncSession
) -> tuple[str, dict]:
    """Re-validate and execute a confirmed action; return (detail, result ids).

    Ownership re-checks (HTTP 404) and business guards such as the ledger
    sell-guard (HTTP 400) are enforced by the reused route handlers.
    Validation failures on the stored params raise HTTP 400.
    """
    try:
        if action_type == "add_transaction":
            return await _execute_transaction(params, user, db)
        if action_type == "add_holding":
            return await _execute_holding(params, user, db)
        if action_type == "create_alert":
            return await _execute_alert(params, user, db)
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Action parameters failed validation: {exc.error_count()} error(s)",
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unsupported action type: {action_type}",
    )


def _require(value: int | None, what: str) -> int:
    if value is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Stored action is missing its resolved {what}",
        )
    return value


async def _execute_transaction(
    params: dict, user: User, db: AsyncSession
) -> tuple[str, dict]:
    from app.api.v1.transactions import create_transaction
    from app.schemas.transaction import TransactionCreate

    p = AddTransactionParams.model_validate(params)
    holding_id = _require(p.holding_id, "holding")
    body = TransactionCreate(
        holding_id=holding_id,
        transaction_type=p.transaction_type,
        date=parse_date(p.date) or date.today(),
        quantity=p.quantity,
        price=p.price,
        brokerage=p.brokerage,
        notes=p.notes,
        source="MANUAL",
    )
    # Reused route handler: ownership 404, SELL ledger guard 400, and the
    # cumulative-holding recompute all come from the real code path.
    tx = await create_transaction(body, user, db)
    detail = (
        f"Recorded {p.transaction_type} of {p.quantity:g} {p.symbol} "
        f"at {p.price:g} and recalculated the holding."
    )
    return detail, {"transaction_id": tx.id, "holding_id": tx.holding_id}


async def _execute_holding(
    params: dict, user: User, db: AsyncSession
) -> tuple[str, dict]:
    from app.api.v1.holdings import create_holding
    from app.schemas.holding import HoldingCreate

    p = AddHoldingParams.model_validate(params)
    portfolio_id = _require(p.portfolio_id, "portfolio")
    body = HoldingCreate(
        portfolio_id=portfolio_id,
        stock_symbol=p.symbol,
        stock_name=p.stock_name or p.symbol,
        exchange=p.exchange,
        cumulative_quantity=p.quantity,
        average_price=p.average_price,
        sector=p.sector,
        currency=p.currency or "INR",
    )
    holding = await create_holding(body, user, db)
    detail = (
        f"Added {p.quantity:g} {p.symbol} ({p.exchange}) at average price "
        f"{p.average_price:g} with an initial BUY transaction."
    )
    return detail, {"holding_id": holding.id, "portfolio_id": holding.portfolio_id}


async def _execute_alert(
    params: dict, user: User, db: AsyncSession
) -> tuple[str, dict]:
    from app.api.v1.alerts import create_alert
    from app.schemas.alert import AlertCreate

    p = CreateAlertParams.model_validate(params)
    holding_id = _require(p.holding_id, "holding")
    body = AlertCreate(
        holding_id=holding_id,
        alert_type=p.alert_type,
        condition=p.condition,
        channels=p.channels,
    )
    alert = await create_alert(body, user, db)
    detail = (
        f"Created a {p.alert_type} alert on {p.symbol} with condition "
        f"{json.dumps(p.condition)}."
    )
    return detail, {"alert_id": alert.id, "holding_id": holding_id}
