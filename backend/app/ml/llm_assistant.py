"""LLM chat assistant with pluggable providers and graceful degradation.

Primary: Ollama (local, free)
Optional: OpenAI, Anthropic, Google
Fallback: If ALL providers unavailable, returns helpful "AI offline" messages.
"""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import AsyncIterator

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


@dataclass
class ChatMessage:
    role: str  # "user", "assistant", "system"
    content: str
    timestamp: str | None = None


@dataclass
class ChatResponse:
    message: str
    provider: str
    model: str
    tokens_used: int | None = None


class LLMProvider(ABC):
    """Abstract LLM provider interface."""

    NAME: str = ""

    @abstractmethod
    async def chat(
        self, messages: list[ChatMessage], system_prompt: str = ""
    ) -> ChatResponse:
        """Send messages and get a response."""

    @abstractmethod
    async def is_available(self) -> bool:
        """Check if this provider is reachable."""

    @abstractmethod
    async def stream(
        self, messages: list[ChatMessage], system_prompt: str = ""
    ) -> AsyncIterator[str]:
        """Stream response tokens."""


class OllamaProvider(LLMProvider):
    """Ollama local LLM provider."""

    NAME = "ollama"

    def __init__(self, base_url: str | None = None, model: str | None = None):
        self.base_url = (base_url or settings.ollama_url).rstrip("/")
        self.model = model or settings.ollama_model

    async def is_available(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False

    async def chat(
        self, messages: list[ChatMessage], system_prompt: str = ""
    ) -> ChatResponse:
        formatted = []
        if system_prompt:
            formatted.append({"role": "system", "content": system_prompt})
        for m in messages:
            formatted.append({"role": m.role, "content": m.content})

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": formatted,
                    "stream": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return ChatResponse(
            message=data.get("message", {}).get("content", ""),
            provider=self.NAME,
            model=self.model,
            tokens_used=data.get("eval_count"),
        )

    async def stream(
        self, messages: list[ChatMessage], system_prompt: str = ""
    ) -> AsyncIterator[str]:
        formatted = []
        if system_prompt:
            formatted.append({"role": "system", "content": system_prompt})
        for m in messages:
            formatted.append({"role": m.role, "content": m.content})

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": formatted,
                    "stream": True,
                },
            ) as resp:
                async for line in resp.aiter_lines():
                    if line:
                        try:
                            data = json.loads(line)
                            content = data.get("message", {}).get("content", "")
                            if content:
                                yield content
                        except json.JSONDecodeError:
                            continue


class OpenAIProvider(LLMProvider):
    """OpenAI API provider."""

    NAME = "openai"

    def __init__(self):
        self.api_key = settings.openai_api_key
        self.model = settings.openai_model

    async def is_available(self) -> bool:
        if not self.api_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                return resp.status_code == 200
        except Exception:
            return False

    async def chat(
        self, messages: list[ChatMessage], system_prompt: str = ""
    ) -> ChatResponse:
        formatted = []
        if system_prompt:
            formatted.append({"role": "system", "content": system_prompt})
        for m in messages:
            formatted.append({"role": m.role, "content": m.content})

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={"model": self.model, "messages": formatted},
            )
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]
        usage = data.get("usage", {})

        return ChatResponse(
            message=choice["message"]["content"],
            provider=self.NAME,
            model=self.model,
            tokens_used=usage.get("total_tokens"),
        )

    async def stream(
        self, messages: list[ChatMessage], system_prompt: str = ""
    ) -> AsyncIterator[str]:
        formatted = []
        if system_prompt:
            formatted.append({"role": "system", "content": system_prompt})
        for m in messages:
            formatted.append({"role": m.role, "content": m.content})

        async with httpx.AsyncClient(timeout=60.0) as client:
            async with client.stream(
                "POST",
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": formatted,
                    "stream": True,
                },
            ) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        try:
                            data = json.loads(line[6:])
                            delta = data["choices"][0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except (json.JSONDecodeError, KeyError, IndexError):
                            continue


class AnthropicProvider(LLMProvider):
    """Anthropic Claude API provider."""

    NAME = "anthropic"

    def __init__(self):
        self.api_key = settings.anthropic_api_key

    async def is_available(self) -> bool:
        return bool(self.api_key)

    async def chat(
        self, messages: list[ChatMessage], system_prompt: str = ""
    ) -> ChatResponse:
        formatted = [{"role": m.role, "content": m.content} for m in messages]

        body: dict = {
            "model": "claude-sonnet-4-20250514",
            "max_tokens": 2048,
            "messages": formatted,
        }
        if system_prompt:
            body["system"] = system_prompt

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()

        content = data["content"][0]["text"] if data.get("content") else ""
        usage = data.get("usage", {})

        return ChatResponse(
            message=content,
            provider=self.NAME,
            model="claude-sonnet-4-20250514",
            tokens_used=usage.get("input_tokens", 0)
            + usage.get("output_tokens", 0),
        )

    async def stream(
        self, messages: list[ChatMessage], system_prompt: str = ""
    ) -> AsyncIterator[str]:
        # Simplified: just call chat and yield full response
        response = await self.chat(messages, system_prompt)
        yield response.message


class GoogleProvider(LLMProvider):
    """Google Gemini API provider."""

    NAME = "google"

    def __init__(self):
        self.api_key = settings.google_api_key

    async def is_available(self) -> bool:
        return bool(self.api_key)

    async def chat(
        self, messages: list[ChatMessage], system_prompt: str = ""
    ) -> ChatResponse:
        contents = []
        for m in messages:
            role = "user" if m.role == "user" else "model"
            contents.append({"role": role, "parts": [{"text": m.content}]})

        body: dict = {"contents": contents}
        if system_prompt:
            body["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"gemini-pro:generateContent?key={self.api_key}",
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()

        text = ""
        if data.get("candidates"):
            parts = (
                data["candidates"][0].get("content", {}).get("parts", [])
            )
            text = parts[0].get("text", "") if parts else ""

        return ChatResponse(
            message=text,
            provider=self.NAME,
            model="gemini-pro",
            tokens_used=None,
        )

    async def stream(
        self, messages: list[ChatMessage], system_prompt: str = ""
    ) -> AsyncIterator[str]:
        response = await self.chat(messages, system_prompt)
        yield response.message


# -- Provider Registry -----------------------------------------------------

PROVIDER_REGISTRY: dict[str, type[LLMProvider]] = {
    "ollama": OllamaProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "google": GoogleProvider,
}

# Fallback order
FALLBACK_ORDER = ["ollama", "openai", "anthropic", "google"]

SYSTEM_PROMPT = """You are a helpful financial assistant for the FinanceTracker app.
You help users understand their investment portfolio, Indian and German stock markets,
technical indicators (RSI, MACD, Bollinger Bands), tax implications (Indian STCG/LTCG,
German Abgeltungssteuer), and general investment concepts.

Keep responses concise, accurate, and easy to understand for non-technical users.
When discussing specific stocks, always remind users that this is not financial advice.
Format numbers with appropriate currency symbols (INR for INR, EUR for EUR).
"""


async def get_active_provider() -> LLMProvider | None:
    """Get the active LLM provider based on settings, with fallback chain."""
    preferred = settings.llm_provider

    if preferred == "none":
        return None

    # Try preferred provider first
    if preferred in PROVIDER_REGISTRY:
        provider = PROVIDER_REGISTRY[preferred]()
        if await provider.is_available():
            return provider
        logger.warning(
            f"Preferred LLM provider '{preferred}' unavailable, trying fallbacks"
        )

    # Try fallback chain
    for name in FALLBACK_ORDER:
        if name == preferred:
            continue
        if name in PROVIDER_REGISTRY:
            provider = PROVIDER_REGISTRY[name]()
            if await provider.is_available():
                logger.info(f"Using fallback LLM provider: {name}")
                return provider

    logger.warning("No LLM providers available — AI features offline")
    return None


async def chat(
    messages: list[ChatMessage],
    user_id: int,
    db=None,  # AsyncSession, optional for context enrichment
) -> ChatResponse:
    """Send a chat message with provider fallback and graceful degradation."""
    provider = await get_active_provider()

    if provider is None:
        return ChatResponse(
            message="I'm sorry, the AI assistant is currently offline. "
            "No LLM providers are configured or available. "
            "You can configure Ollama (free, local) or other providers "
            "in Settings -> AI.",
            provider="none",
            model="none",
            tokens_used=0,
        )

    try:
        return await provider.chat(messages, system_prompt=SYSTEM_PROMPT)
    except Exception as e:
        logger.error(f"LLM chat failed with {provider.NAME}: {e}")
        return ChatResponse(
            message=f"I encountered an error processing your request. "
            f"The {provider.NAME} provider returned an error. "
            f"Please try again or switch providers in Settings.",
            provider=provider.NAME,
            model="error",
            tokens_used=0,
        )


async def check_provider_status() -> dict[str, bool]:
    """Check availability of all configured providers."""
    status = {}
    for name, cls in PROVIDER_REGISTRY.items():
        try:
            provider = cls()
            status[name] = await provider.is_available()
        except Exception:
            status[name] = False
    return status
