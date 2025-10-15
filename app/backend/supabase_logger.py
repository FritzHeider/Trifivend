# app/backend/supabase_logger.py
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("trifivend.supabase")

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

# Minimal models you referenced
class ConversationLog(BaseModel):
    user_input: str
    bot_reply: str
    meta: Optional[Dict[str, Any]] = None

class Lead(BaseModel):
    name: str
    phone: str
    property_type: str
    location_area: str
    callback_offer: str

class Call(BaseModel):
    lead_id: Optional[str] = None
    call_sid: str
    from_number: str
    to_number: str
    status: str

class CallEvent(BaseModel):
    call_sid: str
    event: str
    payload: Dict[str, Any] = Field(default_factory=dict)

# Best-effort no-op loggers with JSON lines so you can pipe to Loki later
async def log_conversation(data: ConversationLog) -> None:
    if not (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY):
        logger.info("CONVERSATION %s", data.model_dump_json())
        return
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{SUPABASE_URL}/rest/v1/conversations",
                headers={
                    "apikey": SUPABASE_SERVICE_ROLE_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                },
                content=data.model_dump_json(),
            )
            r.raise_for_status()
    except Exception:
        logger.exception("Supabase conversation insert failed; logged to stdout instead")
        logger.info("CONVERSATION %s", data.model_dump_json())

async def log_lead(lead: Lead) -> None:
    if not (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY):
        logger.info("LEAD %s", lead.model_dump_json())
        return
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{SUPABASE_URL}/rest/v1/leads",
                headers={
                    "apikey": SUPABASE_SERVICE_ROLE_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                },
                content=lead.model_dump_json(),
            )
            r.raise_for_status()
    except Exception:
        logger.exception("Supabase lead insert failed; logged to stdout")
        logger.info("LEAD %s", lead.model_dump_json())

async def log_call(call: Call) -> None:
    if not (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY):
        logger.info("CALL %s", call.model_dump_json())
        return
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{SUPABASE_URL}/rest/v1/calls",
                headers={
                    "apikey": SUPABASE_SERVICE_ROLE_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                },
                content=call.model_dump_json(),
            )
            r.raise_for_status()
    except Exception:
        logger.exception("Supabase call insert failed; logged to stdout")
        logger.info("CALL %s", call.model_dump_json())

async def log_call_event(evt: CallEvent) -> None:
    if not (SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY):
        logger.info("CALL_EVENT %s", evt.model_dump_json())
        return
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                f"{SUPABASE_URL}/rest/v1/call_events",
                headers={
                    "apikey": SUPABASE_SERVICE_ROLE_KEY,
                    "Authorization": f"Bearer {SUPABASE_SERVICE_ROLE_KEY}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal",
                },
                content=evt.model_dump_json(),
            )
            r.raise_for_status()
    except Exception:
        logger.exception("Supabase call_event insert failed; logged to stdout")
        logger.info("CALL_EVENT %s", evt.model_dump_json())
