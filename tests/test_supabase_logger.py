import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))
from app.backend.supabase_logger import (
    ConversationLog,
    log_conversation,
    Lead,
    log_lead,
)


@pytest.mark.asyncio
async def test_log_conversation_posts_payload(monkeypatch):
    """Ensure the logger posts the expected payload to Supabase."""

    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "testkey")

    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = json.loads(request.content.decode())
        return httpx.Response(201)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        log = ConversationLog(user_input="hi", bot_reply="there")
        await log_conversation(log, client=client)

    assert (
        captured["url"]
        == "https://example.supabase.co/rest/v1/conversations"
    )
    assert captured["json"]["user_input"] == "hi"
    assert captured["json"]["bot_reply"] == "there"


@pytest.mark.asyncio
async def test_log_conversation_skips_without_credentials(monkeypatch, capsys):
    """Without credentials the logger should exit gracefully."""

    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)

    log = ConversationLog(user_input="hi", bot_reply="there")
    await log_conversation(log)

    captured = capsys.readouterr()
    assert "Supabase credentials missing" in captured.out


@pytest.mark.asyncio
async def test_log_lead_posts_payload(monkeypatch):
    """Verify lead information is sent to Supabase."""

    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "testkey")

    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = json.loads(request.content.decode())
        return httpx.Response(201)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        lead = Lead(
            name="Alex",
            phone="123",
            property_type="apartment",
            location_area="NYC",
        )
        await log_lead(lead, client=client)

    assert captured["url"] == "https://example.supabase.co/rest/v1/leads"
    assert captured["json"]["name"] == "Alex"

