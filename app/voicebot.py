"""Simple wrapper around the OpenAI Chat API used for lead engagement."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator, Sequence
from typing import List, MutableSequence

from openai import AsyncOpenAI

# -----------------------------------------------------------------------------
# Config
# -----------------------------------------------------------------------------
MODEL_NAME = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
async_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

_SENTENCE_DELIMITERS = (".", "?", "!", "\n")
_MAX_BUFFER_CHARS = 300


# -----------------------------------------------------------------------------
# Streaming API
# -----------------------------------------------------------------------------
async def stream_coldcall_reply(
    messages: Sequence[dict],
    *,
    temperature: float = 0.7,
    model: str = MODEL_NAME,
) -> AsyncGenerator[str, None]:
    """Yield incremental text responses from the assistant.

    Tokens are buffered until a likely sentence boundary (or a safety length),
    then flushed to the caller. Keeps UX snappy for TTS/voice and chat UIs.
    """
    buffer = ""

    try:
        # Chat Completions remain supported (Responses API is the new default,
        # but this endpoint is still fine for text chat). :contentReference[oaicite:0]{index=0}
        response = await async_client.chat.completions.create(
            model=model,
            messages=list(messages),
            temperature=temperature,
            stream=True,
        )

        async for chunk in response:
            # Defensive: some chunks may not include content deltas.
            if not chunk.choices:
                continue
            delta = getattr(chunk.choices[0].delta, "content", None)
            if not delta:
                continue

            buffer += delta
            if any(d in buffer for d in _SENTENCE_DELIMITERS) or len(buffer) > _MAX_BUFFER_CHARS:
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
    temperature: float = 0.7,
    model: str = MODEL_NAME,
) -> str:
    parts: MutableSequence[str] = []
    async for part in stream_coldcall_reply(messages, temperature=temperature, model=model):
        parts.append(part)
    return " ".join(parts).strip()


def coldcall_lead(
    messages: List[dict],
    temperature: float = 0.7,
    model: str = MODEL_NAME,
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
        return asyncio.run(_collect_reply(messages, temperature=temperature, model=model))
    except Exception as e:
        raise RuntimeError(f"AI response failed: {e}") from e
