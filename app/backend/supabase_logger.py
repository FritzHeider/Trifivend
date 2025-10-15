# app/backend/supabase_logger.py
from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, Optional, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger("trifivend.supabase")


def _credentials() -> Tuple[str, str]:
    """Return the Supabase URL and service key from the environment."""

    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or ""
    return url, key


def _missing_credentials_message() -> None:
    message = "Supabase credentials missing; logging locally."
    print(message)
    logger.warning(message)


async def _post_json(
    url: str,
    headers: Dict[str, str],
    payload: Dict[str, Any],
    *,
    client: Optional["httpx.AsyncClient"],
) -> None:
    import httpx

    close_client = False
    request_client: "httpx.AsyncClient"
    if client is None:
        request_client = httpx.AsyncClient(timeout=10)
        close_client = True
    else:
        request_client = client

    try:
        response = await request_client.post(url, headers=headers, json=payload)
        response.raise_for_status()
    finally:
        if close_client:
            await request_client.aclose()


async def _get_json(
    url: str,
    headers: Dict[str, str],
    params: Dict[str, str],
    *,
    client: Optional["httpx.AsyncClient"],
) -> Optional[list]:
    import httpx

    close_client = False
    request_client: "httpx.AsyncClient"
    if client is None:
        request_client = httpx.AsyncClient(timeout=10)
        close_client = True
    else:
        request_client = client

    try:
        response = await request_client.get(url, headers=headers, params=params)
        response.raise_for_status()
        return response.json()
    finally:
        if close_client:
            await request_client.aclose()


class ConversationLog(BaseModel):
    user_input: str
    bot_reply: str
    meta: Optional[Dict[str, Any]] = None


class Lead(BaseModel):
    name: str
    phone: str
    property_type: str
    location_area: str
    callback_offer: Optional[str] = None


class LeadScript(BaseModel):
    lead_phone: str
    script_id: str
    script_text: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


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


async def log_conversation(
    data: ConversationLog, *, client: Optional["httpx.AsyncClient"] = None
) -> None:
    url, key = _credentials()
    if not (url and key):
        _missing_credentials_message()
        logger.info("CONVERSATION %s", data.model_dump_json())
        return

    try:
        await _post_json(
            f"{url}/rest/v1/conversations",
            {
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            data.model_dump(),
            client=client,
        )
    except Exception:
        logger.exception("Supabase conversation insert failed; logged locally")
        logger.info("CONVERSATION %s", data.model_dump_json())


async def log_lead(lead: Lead, *, client: Optional["httpx.AsyncClient"] = None) -> None:
    url, key = _credentials()
    if not (url and key):
        _missing_credentials_message()
        logger.info("LEAD %s", lead.model_dump_json())
        return

    try:
        await _post_json(
            f"{url}/rest/v1/leads",
            {
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            lead.model_dump(exclude_none=True),
            client=client,
        )
    except Exception:
        logger.exception("Supabase lead insert failed; logged locally")
        logger.info("LEAD %s", lead.model_dump_json())


async def log_script(
    script: LeadScript, *, client: Optional["httpx.AsyncClient"] = None
) -> None:
    url, key = _credentials()
    if not (url and key):
        _missing_credentials_message()
        logger.info("LEAD_SCRIPT %s", script.model_dump_json())
        return

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal,resolution=merge-duplicates",
    }

    payload = script.model_dump(exclude_none=True)

    try:
        await _post_json(
            f"{url}/rest/v1/lead_scripts?on_conflict=lead_phone,script_id",
            headers,
            payload,
            client=client,
        )
    except Exception:
        logger.exception("Supabase lead_script upsert failed; logged locally")
        logger.info("LEAD_SCRIPT %s", script.model_dump_json())


async def get_script(
    lead_phone: str,
    script_id: str = "default",
    *,
    client: Optional["httpx.AsyncClient"] = None,
) -> Optional[LeadScript]:
    url, key = _credentials()
    if not (url and key):
        _missing_credentials_message()
        return None

    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    params = {
        "select": "*",
        "lead_phone": f"eq.{lead_phone}",
        "script_id": f"eq.{script_id}",
        "order": "updated_at.desc",
        "limit": "1",
    }

    try:
        items = await _get_json(
            f"{url}/rest/v1/lead_scripts",
            headers,
            params,
            client=client,
        )
    except Exception:
        logger.exception("Supabase lead_script fetch failed")
        return None

    if not items:
        return None

    return LeadScript.model_validate(items[0])


async def log_call(call: Call, *, client: Optional["httpx.AsyncClient"] = None) -> None:
    url, key = _credentials()
    if not (url and key):
        _missing_credentials_message()
        logger.info("CALL %s", call.model_dump_json())
        return

    try:
        await _post_json(
            f"{url}/rest/v1/calls",
            {
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            call.model_dump(),
            client=client,
        )
    except Exception:
        logger.exception("Supabase call insert failed; logged locally")
        logger.info("CALL %s", call.model_dump_json())


async def log_call_event(
    evt: CallEvent, *, client: Optional["httpx.AsyncClient"] = None
) -> None:
    url, key = _credentials()
    if not (url and key):
        _missing_credentials_message()
        logger.info("CALL_EVENT %s", evt.model_dump_json())
        return

    try:
        await _post_json(
            f"{url}/rest/v1/call_events",
            {
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            evt.model_dump(),
            client=client,
        )
    except Exception:
        logger.exception("Supabase call_event insert failed; logged locally")
        logger.info("CALL_EVENT %s", evt.model_dump_json())
