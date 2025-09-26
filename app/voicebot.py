"""Simple wrapper around the OpenAI Chat API used for lead engagement."""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncGenerator, Sequence
from typing import List, MutableSequence

from app.openai_compat import (
    create_async_openai_client,
    is_openai_available,
    missing_openai_error,
)

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
MODEL_NAME = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
logger = logging.getLogger(__name__)
async_client = create_async_openai_client(api_key=os.getenv("OPENAI_API_KEY"))
if not is_openai_available():  # pragma: no cover - exercised when dependency missing
    logger.warning(
        "OpenAI SDK unavailable; streaming replies will raise until installed: %s",
        missing_openai_error(),
    )

# Lower thresholds for faster first audio
_SENTENCE_DELIMITERS = (".", "?", "!", "\n")
_MIN_FLUSH_CHARS = 60     # ~1 short clause
_MAX_FLUSH_CHARS = 80     # hard push to speak
# First-turn token cap to avoid long monologues; tune per use case
_FIRST_TURN_MAX_TOKENS = 90


# -----------------------------------------------------------------------------
# Streaming API
# -----------------------------------------------------------------------------
async def stream_coldcall_reply(
    messages: Sequence[dict],
    *,
    temperature: float = 0.6,
    model: str = MODEL_NAME,
    is_first_turn: bool = True,
) -> AsyncGenerator[str, None]:
    """Yield incremental text responses from the assistant.

    Tokens are buffered until a likely sentence boundary (or a safety length),
    then flushed to the caller. Keeps UX snappy for TTS/voice and chat UIs.
    """
    buffer = ""

    params = {
        "model": model,
        "messages": list(messages),
        "temperature": temperature,
        "stream": True,
    }
    if is_first_turn:
        # Small opener for snappier TTS; you can follow with a continuation call if needed
        params["max_tokens"] = _FIRST_TURN_MAX_TOKENS

    try:
        # Chat Completions remain supported (Responses API is the new default,
        # but this endpoint is still fine for text chat). :contentReference[oaicite:0]{index=0}
        response = await async_client.chat.completions.create(**params)

        async for chunk in response:
            # Defensive: some chunks may not include content deltas.
            if not chunk.choices:
                continue
            delta = getattr(chunk.choices[0].delta, "content", None)
            if not delta:
                continue

            buffer += delta
            if (
                len(buffer) >= _MAX_FLUSH_CHARS
                or any(d in buffer for d in _SENTENCE_DELIMITERS) and len(buffer) >= _MIN_FLUSH_CHARS
            ):
                flushed, buffer = buffer.strip(), ""
                if flushed:
                    yield flushed

    except Exception as e:  # pragma: no cover
        raise RuntimeError(f"AI streaming response failed: {e}") from e

    # Flush trailing text if the stream closed mid-sentence.
    tail = buffer.strip()
    if tail:
        yield tail


# -----------------------------------------------------------------------------
# Convenience collectors
# -----------------------------------------------------------------------------
async def _collect_reply(
    messages: Sequence[dict],
    *,
    temperature: float = 0.6,
    model: str = MODEL_NAME,
    is_first_turn: bool = True,
) -> str:
    parts: MutableSequence[str] = []
    async for part in stream_coldcall_reply(
        messages,
        temperature=temperature,
        model=model,
        is_first_turn=is_first_turn,
    ):
        parts.append(part)
    return " ".join(parts).strip()


def coldcall_lead(
    messages: List[dict],
    temperature: float = 0.6,
    model: str = MODEL_NAME,
    is_first_turn: bool = True,
) -> str:
    """Synchronous wrapper for legacy callers (tests, scripts).

    If you're inside an event loop (e.g., FastAPI/UVicorn request context),
    call `stream_coldcall_reply` directly instead of this helper.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():  # pragma: no cover
        raise RuntimeError(
            "coldcall_lead() cannot be called from a running event loop; "
            "use `stream_coldcall_reply` instead."
        )

    try:
        return asyncio.run(
            _collect_reply(
                messages,
                temperature=temperature,
                model=model,
                is_first_turn=is_first_turn,
            )
        )
    except Exception as e:
        raise RuntimeError(f"AI response failed: {e}") from e
