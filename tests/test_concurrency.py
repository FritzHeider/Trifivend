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
    monkeypatch.setattr(main, "log_conversation", lambda entry: None)

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

    monkeypatch.setattr(
        main.openai_client.chat.completions, "create", fake_create
    )
    monkeypatch.setattr(main, "log_conversation", lambda *a, **k: None)

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        params = {
            "lead_name": "a",
            "property_type": "b",
            "location_area": "c",
            "callback_offer": "d",
        }

        async def get():
            resp = await client.get("/mcp/sse", params=params)
            assert resp.status_code == 200
            assert "hello" in resp.text

        start = time.perf_counter()
        await asyncio.gather(get(), get())
        assert time.perf_counter() - start < 0.45

