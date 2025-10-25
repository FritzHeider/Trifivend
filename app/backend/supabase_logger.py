# app/backend/supabase_logger.py
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger("trifivend.supabase")


@dataclass(frozen=True)
class _SupabaseConfig:
    """Small helper describing the credentials required for Supabase."""

    url: str
    key: str

    def headers(self, extras: Optional[Iterable[tuple[str, str]]] = None) -> Dict[str, str]:
        base = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": "application/json",
        }
        if extras:
            for extra_key, value in extras:
                base[extra_key] = value
        return base


def _credentials() -> Optional[_SupabaseConfig]:
    """Return Supabase credentials if fully configured."""

    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or ""
    if not (url and key):
        return None
    return _SupabaseConfig(url=url, key=key)


def _missing_credentials_message() -> None:
    message = "Supabase credentials missing; logging locally."
    print(message)
    logger.warning(message)


@asynccontextmanager
async def _client_context(client: Optional["httpx.AsyncClient"], timeout: float = 10.0):
    import httpx

    if client is not None:
        yield client
        return

    managed_client = httpx.AsyncClient(timeout=timeout)
    try:
        yield managed_client
    finally:
        await managed_client.aclose()


async def _request(
    method: str,
    path: str,
    *,
    config: _SupabaseConfig,
    payload: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, str]] = None,
    prefer: Optional[str] = None,
    client: Optional["httpx.AsyncClient"] = None,
) -> Optional[Any]:
    headers_extra: Optional[Iterable[tuple[str, str]]] = None
    if prefer:
        headers_extra = (("Prefer", prefer),)

    headers = config.headers(headers_extra)
    url = f"{config.url}{path}"

    async with _client_context(client) as http_client:
        response = await http_client.request(
            method,
            url,
            headers=headers,
            json=payload,
            params=params,
        )
        response.raise_for_status()
        return response.json() if method.upper() == "GET" else None


def _log_locally(prefix: str, payload: BaseModel) -> None:
    logger.info("%s %s", prefix, payload.model_dump_json())


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
    config = _credentials()
    if not config:
        _missing_credentials_message()
        _log_locally("CONVERSATION", data)
        return

    try:
        await _request(
            "POST",
            "/rest/v1/conversations",
            config=config,
            payload=data.model_dump(),
            prefer="return=minimal",
            client=client,
        )
    except Exception:
        logger.exception("Supabase conversation insert failed; logged locally")
        _log_locally("CONVERSATION", data)


async def log_lead(lead: Lead, *, client: Optional["httpx.AsyncClient"] = None) -> None:
    config = _credentials()
    if not config:
        _missing_credentials_message()
        _log_locally("LEAD", lead)
        return

    try:
        await _request(
            "POST",
            "/rest/v1/leads",
            config=config,
            payload=lead.model_dump(exclude_none=True),
            prefer="return=minimal",
            client=client,
        )
    except Exception:
        logger.exception("Supabase lead insert failed; logged locally")
        _log_locally("LEAD", lead)


async def log_script(
    script: LeadScript, *, client: Optional["httpx.AsyncClient"] = None
) -> None:
    config = _credentials()
    if not config:
        _missing_credentials_message()
        _log_locally("LEAD_SCRIPT", script)
        return

    try:
        await _request(
            "POST",
            "/rest/v1/lead_scripts?on_conflict=lead_phone,script_id",
            config=config,
            payload=script.model_dump(exclude_none=True),
            prefer="return=minimal,resolution=merge-duplicates",
            client=client,
        )
    except Exception:
        logger.exception("Supabase lead_script upsert failed; logged locally")
        _log_locally("LEAD_SCRIPT", script)


async def get_script(
    lead_phone: str,
    script_id: str = "default",
    *,
    client: Optional["httpx.AsyncClient"] = None,
) -> Optional[LeadScript]:
    config = _credentials()
    if not config:
        _missing_credentials_message()
        return None

    params = {
        "select": "*",
        "lead_phone": f"eq.{lead_phone}",
        "script_id": f"eq.{script_id}",
        "order": "updated_at.desc",
        "limit": "1",
    }

    try:
        items = await _request(
            "GET",
            "/rest/v1/lead_scripts",
            config=config,
            params=params,
            client=client,
        )
    except Exception:
        logger.exception("Supabase lead_script fetch failed")
        return None

    if not items:
        return None

    return LeadScript.model_validate(items[0])


async def log_call(call: Call, *, client: Optional["httpx.AsyncClient"] = None) -> None:
    config = _credentials()
    if not config:
        _missing_credentials_message()
        _log_locally("CALL", call)
        return

    try:
        await _request(
            "POST",
            "/rest/v1/calls",
            config=config,
            payload=call.model_dump(),
            prefer="return=minimal",
            client=client,
        )
    except Exception:
        logger.exception("Supabase call insert failed; logged locally")
        _log_locally("CALL", call)


async def log_call_event(
    evt: CallEvent, *, client: Optional["httpx.AsyncClient"] = None
) -> None:
    config = _credentials()
    if not config:
        _missing_credentials_message()
        _log_locally("CALL_EVENT", evt)
        return

    try:
        await _request(
            "POST",
            "/rest/v1/call_events",
            config=config,
            payload=evt.model_dump(),
            prefer="return=minimal",
            client=client,
        )
    except Exception:
        logger.exception("Supabase call_event insert failed; logged locally")
        _log_locally("CALL_EVENT", evt)
