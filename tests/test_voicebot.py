import asyncio
import contextlib
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

import app.voicebot as voicebot


def test_stream_coldcall_reply_requires_async_client(monkeypatch):
    monkeypatch.setattr(voicebot, "async_client", None)

    async def consume() -> None:
        stream = voicebot.stream_coldcall_reply(
            [{"role": "user", "content": "Hello"}]
        )
        try:
            await stream.__anext__()
        finally:
            with contextlib.suppress(Exception):
                await stream.aclose()

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(consume())

    assert voicebot.missing_openai_error() in str(exc_info.value)


def test_coldcall_lead_requires_async_client(monkeypatch):
    monkeypatch.setattr(voicebot, "async_client", None)

    with pytest.raises(RuntimeError) as exc_info:
        voicebot.coldcall_lead([{"role": "user", "content": "Hello"}])

    assert voicebot.missing_openai_error() in str(exc_info.value)
