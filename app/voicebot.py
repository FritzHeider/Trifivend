# app/voicebot.py
from __future__ import annotations

import asyncio
import os
import logging
from typing import AsyncGenerator, List, Dict, Any

logger = logging.getLogger("trifivend.voicebot")

try:
    from app.openai_compat import (
        create_async_openai_client,
        is_openai_available,
        missing_openai_error,
    )
except Exception as e:  # pragma: no cover - import guard
    create_async_openai_client = None  # type: ignore
    is_openai_available = lambda: False  # type: ignore
    missing_openai_error = lambda: str(e)  # type: ignore
    logger.warning("OpenAI compat missing in voicebot: %s", e)

async_client = None

if create_async_openai_client and callable(is_openai_available) and is_openai_available():
    try:
        async_client = create_async_openai_client(os.getenv("OPENAI_API_KEY", ""))
    except Exception as exc:  # pragma: no cover - best effort
        async_client = None
        logger.warning("Failed to initialize OpenAI async client: %s", exc)

SYSTEM_PROMPT = (
    "You are Ava, a concise, friendly AI cold-caller for TriFiVend. "
    "Qualify property managers for installing premium vending machines. "
    "Ask one question at a time. Keep replies under 25 words."
)

def _trim(text: str, limit: int = 250) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else (text[:limit] + "…")

def _require_async_client():
    if async_client is None:
        raise RuntimeError(f"OpenAI client unavailable: {missing_openai_error()}")
    return async_client


async def stream_coldcall_reply(
    messages: List[Dict[str, Any]]
) -> AsyncGenerator[str, None]:
    client = _require_async_client()
    try:
        stream = await client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            temperature=0.4,
            max_tokens=120,
            stream=True,
        )
    except Exception as exc:  # pragma: no cover - network path
        logger.exception("Streaming chat failed")
        raise RuntimeError("OpenAI streaming failed") from exc

    async for chunk in stream:
        delta = getattr(chunk.choices[0].delta, "content", None)
        if delta:
            yield delta


def coldcall_lead(messages: List[Dict[str, Any]]) -> str:
    """Synchronous helper used from a threadpool."""
    user_utterance = ""
    for m in messages[::-1]:
        if m.get("role") == "user":
            user_utterance = str(m.get("content") or "")
            break

    client = _require_async_client()

    async def _complete() -> str:
        response = await client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
            temperature=0.4,
            max_tokens=90,
        )
        return response.choices[0].message.content.strip()

    try:
        return asyncio.run(_complete())
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(_complete())
        finally:
            loop.close()
    except Exception as exc:  # pragma: no cover - network path
        logger.exception("OpenAI chat failure: %s", exc)
        raise RuntimeError("OpenAI chat failed") from exc
