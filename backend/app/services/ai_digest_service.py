"""AI portfolio digest: grounded, provider-optional summaries.

Three consumers share this module:

1. The ``/ai/digest`` API (on-demand generation + schedule preference).
2. The scheduled digest task (``app.tasks.ai_digest_task``).
3. The report exporter (optional "AI Summary" section) and the alert task
   (one-sentence trigger explanations).

Design rules
------------
- The numbers ALWAYS come first: ``build_portfolio_context`` compiles the
  user's real holdings/P&L/concentration data, and a deterministic plain-text
  digest is built from it with no LLM involved. That digest is the guaranteed
  fallback — the feature works with zero providers configured.
- When a provider IS active, it is asked to summarise ONLY the provided
  context, time-boxed with ``asyncio.wait_for(settings.ai_digest_timeout)``.
  Any timeout/error falls back to the numbers-only digest (provider "none").
- The latest digest and the schedule frequency are persisted per user inside
  the existing ``User.notification_preferences`` JSON column (keys
  ``ai_digest_latest`` / ``ai_digest_frequency``) — no migrations needed, and
  the settings API merges updates so these keys survive preference edits.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.ml.llm_assistant import (
    SYSTEM_PROMPT,
    ChatMessage,
    _compose_system_prompt,
    get_active_provider,
)
from app.models.user import User
from app.services.ai_context_service import build_portfolio_context

logger = logging.getLogger(__name__)

# Keys inside User.notification_preferences (JSON) — no migration required.
DIGEST_LATEST_KEY = "ai_digest_latest"
DIGEST_FREQUENCY_KEY = "ai_digest_frequency"

VALID_FREQUENCIES = ("off", "daily", "weekly")

NOT_ADVICE_NOTE = (
    "AI-generated — educational information only, not financial advice."
)

_DIGEST_PROMPT = (
    "Write a short portfolio digest (5-8 sentences) grounded ONLY in the "
    "portfolio context provided in the system prompt. Cover: total invested "
    "vs current value and overall P&L, the largest positions by weight, "
    "notable gainers/losers, and any concentration or drift flags. Quote the "
    "actual numbers with the correct currency. Do not invent holdings, "
    "prices, or values that are not in the context, and do not predict "
    "future prices. End with a one-line reminder that this is educational "
    "information, not financial advice."
)

_REPORT_SUMMARY_PROMPT = (
    "Write a compact 4-6 sentence summary of this portfolio for the top of "
    "a printed report, grounded ONLY in the portfolio context provided in "
    "the system prompt. Mention total invested vs current value, overall "
    "P&L, the largest positions, and any concentration flags, quoting the "
    "actual numbers. No predictions, no recommendations — educational "
    "information only. Plain text, no markdown headings or bullet lists."
)


# ---------------------------------------------------------------------------
# Deterministic numbers-only digest (the no-LLM path)
# ---------------------------------------------------------------------------


def _build_numbers_digest(context: str, generated_at: str) -> str:
    """Build the deterministic plain-text digest from the compiled context.

    ``build_portfolio_context`` already contains the totals, per-portfolio
    P&L, the top holdings by weight, sector allocation, and concentration
    flags — so the numbers-only digest is that context under a clear header,
    with the standing disclaimer. Works with no LLM provider at all.
    """
    header = f"Portfolio Digest — {generated_at}"
    if not context:
        body = (
            "No holdings found yet. Add stocks to a portfolio to receive a "
            "digest of totals, P&L, top positions, and concentration flags."
        )
    else:
        body = context
    return f"{header}\n\n{body}\n\n{NOT_ADVICE_NOTE}"


# ---------------------------------------------------------------------------
# Preference storage helpers (User.notification_preferences JSON)
# ---------------------------------------------------------------------------


def get_latest_digest(user: User) -> dict | None:
    """Return the stored latest digest for a user, or None."""
    prefs = user.notification_preferences or {}
    digest = prefs.get(DIGEST_LATEST_KEY)
    return digest if isinstance(digest, dict) else None


def get_digest_frequency(user: User) -> str:
    """Return the user's digest schedule frequency ("off" by default)."""
    prefs = user.notification_preferences or {}
    freq = prefs.get(DIGEST_FREQUENCY_KEY, "off")
    return freq if freq in VALID_FREQUENCIES else "off"


def _set_pref(user: User, key: str, value: object) -> None:
    """Set one key in the JSON preferences with proper change detection.

    Plain JSON columns don't track in-place mutation — copy, update, reassign
    (same pattern as the settings API's merge).
    """
    prefs = dict(user.notification_preferences or {})
    prefs[key] = value
    user.notification_preferences = prefs


def set_digest_frequency(user: User, frequency: str) -> None:
    if frequency not in VALID_FREQUENCIES:
        raise ValueError(
            f"Invalid frequency {frequency!r}; valid: {list(VALID_FREQUENCIES)}"
        )
    _set_pref(user, DIGEST_FREQUENCY_KEY, frequency)


# ---------------------------------------------------------------------------
# Digest generation
# ---------------------------------------------------------------------------


async def _grounded_completion(
    prompt: str, context: str, timeout: float
) -> tuple[str, str] | None:
    """Ask the active provider for a completion grounded in ``context``.

    Returns ``(message, provider_name)`` or ``None`` on no provider, timeout,
    error, or an empty reply. Never raises.
    """
    try:
        provider = await get_active_provider()
        if provider is None:
            return None
        system_prompt = _compose_system_prompt(SYSTEM_PROMPT, context)
        response = await asyncio.wait_for(
            provider.chat(
                [ChatMessage(role="user", content=prompt)],
                system_prompt=system_prompt,
            ),
            timeout=timeout,
        )
        message = (response.message or "").strip()
        if not message:
            return None
        return message, response.provider
    except TimeoutError:
        logger.warning("AI completion timed out after %.1fs", timeout)
        return None
    except Exception as exc:
        logger.warning("AI completion failed: %r", exc)
        return None


async def generate_digest(user_id: int, db: AsyncSession) -> dict:
    """Generate (and persist) the portfolio digest for a user.

    Returns ``{generated_at, content, provider, grounded}``. The numbers-only
    digest is always available; the LLM only ever *rewrites* the same grounded
    context, and any failure/timeout falls back to the deterministic text.
    """
    generated_at = datetime.now(UTC).isoformat(timespec="seconds")

    context = ""
    try:
        context = await build_portfolio_context(user_id, db)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("digest: context build failed for user %s: %r", user_id, exc)

    content = _build_numbers_digest(context, generated_at)
    provider_name = "none"

    if context:
        result = await _grounded_completion(
            _DIGEST_PROMPT, context, settings.ai_digest_timeout
        )
        if result is not None:
            content, provider_name = result

    digest = {
        "generated_at": generated_at,
        "content": content,
        "provider": provider_name,
        "grounded": bool(context),
    }

    # Persist as the user's latest digest (best-effort — the digest itself is
    # still returned even if the user row is unexpectedly missing).
    user = await db.get(User, user_id)
    if user is not None:
        _set_pref(user, DIGEST_LATEST_KEY, digest)
        await db.flush()

    return digest


# ---------------------------------------------------------------------------
# Report summary (Feature 2) and alert explanations (Feature 3)
# ---------------------------------------------------------------------------


async def generate_report_summary(user_id: int, db: AsyncSession) -> str | None:
    """Best-effort 4-6 sentence AI summary for the HTML/PDF report.

    Returns None (report proceeds without the section) when no provider is
    active, the context is empty, or the call fails/times out. Never raises.
    """
    try:
        context = await build_portfolio_context(user_id, db)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("report summary: context build failed: %r", exc)
        return None
    if not context:
        return None

    result = await _grounded_completion(
        _REPORT_SUMMARY_PROMPT, context, settings.ai_digest_timeout
    )
    return result[0] if result is not None else None


async def explain_alert_trigger(alert_info: dict) -> str | None:
    """Best-effort ONE-sentence explanation of a triggered alert.

    Gated by ``settings.ai_alert_explanations`` and time-boxed with
    ``settings.ai_alert_explain_timeout`` so alert delivery is never delayed
    beyond the timeout. Returns None on any failure. Never raises.
    """
    if not settings.ai_alert_explanations:
        return None

    try:
        symbol = alert_info.get("stock_symbol", "n/a")
        alert_type = alert_info.get("alert_type", "n/a")
        condition = alert_info.get("condition") or {}
        message = alert_info.get("message", "")
        prompt = (
            "A portfolio price alert just triggered. In ONE short sentence, "
            "explain what this trigger means in plain terms for the holder. "
            "Educational only — no advice, no predictions, no preamble.\n"
            f"Symbol: {symbol}\nAlert type: {alert_type}\n"
            f"Condition: {condition}\nTrigger message: {message}"
        )

        provider = await get_active_provider()
        if provider is None:
            return None
        response = await asyncio.wait_for(
            provider.chat([ChatMessage(role="user", content=prompt)]),
            timeout=settings.ai_alert_explain_timeout,
        )
        text = (response.message or "").strip()
        if not text:
            return None
        # Keep it to one compact line even if the model rambles.
        first_line = text.splitlines()[0].strip()
        return first_line[:300] if first_line else None
    except TimeoutError:
        logger.info("alert explanation timed out — sending plain message")
        return None
    except Exception as exc:
        logger.info("alert explanation skipped: %r", exc)
        return None
