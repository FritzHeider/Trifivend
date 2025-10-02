import asyncio
import time
from types import SimpleNamespace
from pathlib import Path
import sys
import os

import pytest
from httpx import AsyncClient, ASGITransport

sys.path.append(str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("OPENAI_API_KEY", "test-key")
import main


@pytest.mark.asyncio
async def test_transcribe_concurrent(monkeypatch):
    def fake_transcribe_audio(data, rate):
        time.sleep(0.1)
        return "text"

    def fake_coldcall(messages):
        time.sleep(0.1)
        return "reply"

    monkeypatch.setattr(main, "transcribe_audio", fake_transcribe_audio)
    monkeypatch.setattr(main, "coldcall_lead", fake_coldcall)
    monkeypatch.setattr(main, "speak_text", lambda text: None)
    async def fake_log_conversation(entry):
        return None

    monkeypatch.setattr(main, "log_conversation", fake_log_conversation)
    monkeypatch.setattr(
        main,
        "ConversationLog",
        lambda *args, **kwargs: SimpleNamespace(*args, **kwargs),
    )

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        async def post():
            files = {"file": ("test.wav", b"data", "audio/wav")}
            resp = await client.post("/transcribe", files=files)
            assert resp.status_code == 200

        start = time.perf_counter()
        await asyncio.gather(post(), post())
        assert time.perf_counter() - start < 0.45


@pytest.mark.asyncio
async def test_sse_concurrent(monkeypatch):
    async def fake_create(*args, **kwargs):
        async def gen():
            await asyncio.sleep(0.1)
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="hello"))]
            )

        return gen()

    if main.openai_client is None:
        main.openai_client = SimpleNamespace()
    if getattr(main.openai_client, "chat", None) is None:
        main.openai_client.chat = SimpleNamespace()  # type: ignore[attr-defined]
    if getattr(main.openai_client.chat, "completions", None) is None:
        main.openai_client.chat.completions = SimpleNamespace()  # type: ignore[attr-defined]
    main.openai_client.chat.completions.create = fake_create  # type: ignore[attr-defined]
    async def fake_log_conversation(*_args, **_kwargs):
        return None

    monkeypatch.setattr(main, "log_conversation", fake_log_conversation)

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        params = {
            "lead_name": "a",
            "phone": "123",
            "property_type": "b",
            "location_area": "c",
            "callback_offer": "d",
        }

        async def get():
            resp = await client.get("/sse", params=params)
            assert resp.status_code == 200
            assert "hello" in resp.text

        start = time.perf_counter()
        await asyncio.gather(get(), get())
        assert time.perf_counter() - start < 0.45


@pytest.mark.asyncio
async def test_sse_generator_single_waiter_during_heartbeats():
    queue: asyncio.Queue[str] = asyncio.Queue()
    gen = main._sse_event_stream(queue, heartbeat_interval=0.01)

    try:
        for _ in range(3):
            event = await asyncio.wait_for(anext(gen), timeout=1)
            assert event == {"event": "ping", "data": "{}"}
            getters = getattr(queue, "_getters", [])
            assert len(getters) == 1

        await queue.put("[DONE]")
        done_event = await asyncio.wait_for(anext(gen), timeout=1)
        assert done_event == {"event": "done", "data": "{}"}
        assert not getattr(queue, "_getters", [])
    finally:
        await gen.aclose()

