import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import AsyncClient, ASGITransport

sys.path.append(str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("OPENAI_API_KEY", "test-key")

import main


@pytest.mark.asyncio
async def test_transcribe_logs_are_awaited(monkeypatch):
    event = asyncio.Event()

    def fake_transcribe_audio(data, rate):
        return "text"

    def fake_coldcall(messages):
        return "reply"

    async def fake_log(entry):
        event.set()

    monkeypatch.setattr(main, "transcribe_audio", fake_transcribe_audio)
    monkeypatch.setattr(main, "coldcall_lead", fake_coldcall)
    monkeypatch.setattr(main, "speak_text", lambda text: None)
    monkeypatch.setattr(main, "log_conversation", fake_log)

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        files = {"file": ("test.wav", b"data", "audio/wav")}
        resp = await client.post("/transcribe", files=files)
        assert resp.status_code == 200

    await asyncio.wait_for(event.wait(), timeout=0.5)


@pytest.mark.asyncio
async def test_call_logs_are_awaited(monkeypatch):
    event = asyncio.Event()

    async def fake_log_lead(lead):
        event.set()

    def fake_create(**kwargs):
        return SimpleNamespace(sid="sid", status="queued")

    fake_client = SimpleNamespace(calls=SimpleNamespace(create=fake_create))

    monkeypatch.setattr(main, "log_lead", fake_log_lead)
    monkeypatch.setitem(
        main.app.dependency_overrides, main.twilio_client, lambda: fake_client
    )
    monkeypatch.setattr(main, "TWILIO_NUMBER", "+10000000000")

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        payload = {
            "phone": "+15551234567",
            "lead_name": "Test",
            "property_type": "type",
            "location_area": "area",
            "callback_offer": "offer",
        }
        resp = await client.post("/call", json=payload)
        assert resp.status_code == 200

    await asyncio.wait_for(event.wait(), timeout=0.5)


@pytest.mark.asyncio
async def test_status_logs_are_awaited(monkeypatch):
    event = asyncio.Event()

    async def fake_log(entry):
        event.set()

    monkeypatch.setattr(main, "log_conversation", fake_log)
    main._call_configs["sid"] = {}

    transport = ASGITransport(app=main.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/status",
            data={"CallSid": "sid", "CallStatus": "ringing"},
        )
        assert resp.status_code == 200

    await asyncio.wait_for(event.wait(), timeout=0.5)
    main._call_configs.clear()
