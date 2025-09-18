"""Simple wrapper around the OpenAI Chat API used for lead engagement."""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncGenerator, Sequence
from typing import List, MutableSequence

from openai import AsyncOpenAI

MODEL_NAME = os.getenv("OPENAI_MODEL", "gpt-4")
async_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

_SENTENCE_DELIMITERS = (".", "?", "!", "\n")
_MAX_BUFFER_CHARS = 300


async def stream_coldcall_reply(
    messages: Sequence[dict],
    *,
    temperature: float = 0.7,
    model: str = MODEL_NAME,
) -> AsyncGenerator[str, None]:
    """Yield incremental text responses from the assistant.

    The function mirrors the batching strategy used by the websocket voice agent:
    as tokens are received they are accumulated until a sentence boundary (or a
    safety length) is observed, at which point the buffered text is yielded.
    """

    buffer = ""
    try:
        response = await async_client.chat.completions.create(
            model=model,
            messages=list(messages),
            temperature=temperature,
            stream=True,
        )

        async for chunk in response:
            if not chunk.choices:
                continue
            delta = getattr(chunk.choices[0].delta, "content", None)
            if not delta:
                continue

            buffer += delta
            if any(delim in buffer for delim in _SENTENCE_DELIMITERS) or len(buffer) > _MAX_BUFFER_CHARS:
                flushed, buffer = buffer.strip(), ""
                if flushed:
                    yield flushed

    except Exception as e:  # pragma: no cover - network exceptions are surfaced upstream
        raise RuntimeError(f"AI streaming response failed: {str(e)}") from e

    if buffer.strip():
        yield buffer.strip()


async def _collect_reply(
    messages: Sequence[dict],
    *,
    temperature: float = 0.7,
    model: str = MODEL_NAME,
) -> str:
    parts: MutableSequence[str] = []
    async for part in stream_coldcall_reply(
        messages, temperature=temperature, model=model
    ):
        parts.append(part)
    return " ".join(parts).strip()


def coldcall_lead(
    messages: List[dict],
    temperature: float = 0.7,
    model: str = MODEL_NAME,
) -> str:
    """Return the assistant's reply for the provided chat ``messages``.

    This synchronous helper is retained for legacy callers (tests, background
    utilities).  It internally consumes the streaming generator via ``asyncio``.
    """

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():  # pragma: no cover - defensive, not expected in tests
        raise RuntimeError(
            "coldcall_lead() cannot be called from a running event loop; use "
            "`stream_coldcall_reply` instead."
        )

    try:
        return asyncio.run(
            _collect_reply(messages, temperature=temperature, model=model)
        )
    except Exception as e:
        raise RuntimeError(f"AI response failed: {str(e)}") from e

