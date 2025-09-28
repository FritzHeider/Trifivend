# app/backend/supabase_logger.py
"""
Non-blocking Supabase logger (REST/PostgREST) for Trifivend.

Design goals
------------
- Zero import-time side effects (never crashes your app at startup)
- Works with Service Role OR anon key (prefers Service Role)
- Pydantic v2 models; extra fields are ignored
- Fire-and-forget style: ALL public functions swallow errors and log warnings
- Flexible: env-configurable table names, HTTP timeout, optional upsert
- Supports single-row and bulk inserts
- Safe for Twilio webhooks (captures raw payload as JSONB)

Required env
------------
SUPABASE_URL                      e.g. https://xxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY         preferred (server-side only)
# or SUPABASE_ANON_KEY            fallback (limited)

Optional env
------------
SUPABASE_LEADS_TABLE=leads
SUPABASE_CONVERSATIONS_TABLE=conversations
SUPABASE_CALLS_TABLE=calls
SUPABASE_CALL_EVENTS_TABLE=call_events
SUPABASE_HTTP_TIMEOUT=5           # seconds
SUPABASE_UPSERT=0                 # 1 to enable upsert (see _rest_insert)

Schema recommendations
----------------------
- call_events.payload JSONB DEFAULT '{}'::jsonb NOT NULL
- Indexes:
    create index if not exists idx_calls_call_sid on public.calls (call_sid);
    create index if not exists idx_leads_phone on public.leads (phone);
    create index if not exists idx_call_events_call_sid on public.call_events (call_sid);
"""

from __future__ import annotations

import os
import json
import time
import logging
from typing import Any, Dict, List, Optional, Sequence

import httpx
from pydantic import BaseModel, Field, ConfigDict

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# Environment / configuration (lazy-read only; no side effects at import)
# ──────────────────────────────────────────────────────────────────────────────

SUPABASE_URL_ENV = "SUPABASE_URL"
SUPABASE_KEY_ENV = "SUPABASE_SERVICE_ROLE_KEY"   # prefer server key
ALT_KEY_ENV      = "SUPABASE_SERVICE_KEY"        # legacy alias used in some configs/tests
FALLBACK_KEY_ENV = "SUPABASE_ANON_KEY"           # fallback if you must

LEADS_TABLE       = os.getenv("SUPABASE_LEADS_TABLE", "leads")
CONV_TABLE        = os.getenv("SUPABASE_CONVERSATIONS_TABLE", "conversations")
CALLS_TABLE       = os.getenv("SUPABASE_CALLS_TABLE", "calls")
CALL_EVENTS_TABLE = os.getenv("SUPABASE_CALL_EVENTS_TABLE", "call_events")
SCRIPTS_TABLE     = os.getenv("SUPABASE_LEAD_SCRIPTS_TABLE", "lead_scripts")

DEFAULT_TIMEOUT_SECS = float(os.getenv("SUPABASE_HTTP_TIMEOUT", "5"))
UPSERT_ENABLED       = os.getenv("SUPABASE_UPSERT", "0").strip() in {"1", "true", "True"}


def _env_supabase() -> Optional[dict]:
    """
    Return Supabase REST credentials from env, or None if misconfigured.
    No network calls; never raises at import/startup.
    """
    url = (os.getenv(SUPABASE_URL_ENV) or "").strip()
    key = (
        os.getenv(SUPABASE_KEY_ENV)
        or os.getenv(ALT_KEY_ENV)
        or os.getenv(FALLBACK_KEY_ENV)
        or ""
    ).strip()

    if not url or not key:
        logger.warning(
            "Supabase disabled (missing %s and/or %s/%s/%s). Logging will be no-op.",
            SUPABASE_URL_ENV,
            SUPABASE_KEY_ENV,
            ALT_KEY_ENV,
            FALLBACK_KEY_ENV,
        )
        return None

    return {"url": url.rstrip("/"), "key": key}


# ──────────────────────────────────────────────────────────────────────────────
# Pydantic v2 models (extra-safe; ignore unknown fields)
# ──────────────────────────────────────────────────────────────────────────────

class Lead(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str = Field(default="")
    phone: str = Field(default="")
    property_type: str = Field(default="")
    location_area: str = Field(default="")
    callback_offer: str = Field(default="")
    meta: Dict[str, Any] = Field(default_factory=dict)


class ConversationLog(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_input: str
    bot_reply: str
    meta: Dict[str, Any] = Field(default_factory=dict)
    # optional join keys if you later associate logs:
    call_sid: Optional[str] = None
    lead_id: Optional[str] = None


class Call(BaseModel):
    """
    Mirrors `calls` table (id is DB-generated).
    Store times as ISO8601 strings (UTC) or let DB defaults handle them.
    """
    model_config = ConfigDict(extra="ignore")
    lead_id: Optional[str] = None
    call_sid: str
    from_number: Optional[str] = None
    to_number: Optional[str] = None
    status: Optional[str] = None
    started_at: Optional[str] = None  # ISO8601 (e.g., datetime.utcnow().isoformat())
    ended_at: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


class CallEvent(BaseModel):
    """
    Mirrors `call_events` table (id is DB-generated).
    """
    model_config = ConfigDict(extra="ignore")
    call_sid: str
    event: str
    created_at: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class LeadScript(BaseModel):
    model_config = ConfigDict(extra="ignore")
    lead_phone: str
    script_id: str = Field(default="default")
    script_text: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    meta: Dict[str, Any] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────

def _headers(key: str) -> Dict[str, str]:
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=minimal" + (",resolution=merge-duplicates" if UPSERT_ENABLED else ""),
    }


async def _rest_insert(
    table: str,
    rows: Dict[str, Any] | List[Dict[str, Any]],
    *,
    on_conflict: Optional[str] = None,   # e.g., "call_sid" when UPSERT_ENABLED=1
    timeout: float = DEFAULT_TIMEOUT_SECS,
    client: Optional[httpx.AsyncClient] = None,
) -> bool:
    """
    Minimal insert via Supabase REST (PostgREST).
    - Accepts one dict OR a list of dicts.
    - Returns True on 2xx, False otherwise.
    - Never raises to callers; logs details for diagnosis.
    - Optional upsert support when UPSERT_ENABLED is set (adds Prefer: resolution=merge-duplicates).
      To use upsert effectively, pass `on_conflict="column_name"`.
    """
    cfg = _env_supabase()
    if not cfg:
        print("Supabase credentials missing; skipping log.")
        return False

    url = f"{cfg['url']}/rest/v1/{table}"
    if on_conflict:
        url += f"?on_conflict={on_conflict}"

    headers = _headers(cfg["key"])
    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=timeout)

    try:
        response = await http_client.post(url, headers=headers, json=rows, timeout=timeout)
        if 200 <= response.status_code < 300:
            return True
        logger.warning("Supabase insert to %s failed: %s %s", table, response.status_code, response.text)
        return False
    except Exception as e:  # pragma: no cover
        logger.warning("Supabase insert error on %s: %s", table, e)
        return False
    finally:
        if owns_client:
            await http_client.aclose()


def _now_ms() -> int:
    return int(time.time() * 1000)


# ──────────────────────────────────────────────────────────────────────────────
# Public logging API (fire-and-forget; NEVER throws)
# ──────────────────────────────────────────────────────────────────────────────

async def log_lead(lead: Lead, *, client: Optional[httpx.AsyncClient] = None) -> None:
    """
    Insert a single lead row. No-op on failure/misconfig.
    """
    payload = {
        "name": lead.name,
        "phone": lead.phone,
        "property_type": lead.property_type,
        "location_area": lead.location_area,
        "callback_offer": lead.callback_offer,
        "meta": lead.meta or {},
        "created_at_ms": _now_ms(),
    }
    ok = await _rest_insert(
        LEADS_TABLE,
        payload,
        on_conflict="phone" if UPSERT_ENABLED else None,
        client=client,
    )
    if not ok:
        logger.info("Lead log no-op or failed (see warnings).")


async def log_conversation(
    entry: ConversationLog,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> None:
    """
    Insert a single conversation turn. No-op on failure/misconfig.
    """
    payload = {
        "user_input": entry.user_input,
        "bot_reply": entry.bot_reply,
        "meta": entry.meta or {},
        "call_sid": entry.call_sid,
        "lead_id": entry.lead_id,
        "created_at_ms": _now_ms(),
    }
    ok = await _rest_insert(CONV_TABLE, payload, client=client)
    if not ok:
        logger.info("Conversation log no-op or failed (see warnings).")


async def log_call(call: Call, *, client: Optional[httpx.AsyncClient] = None) -> None:
    """
    Insert a `calls` row. Pass whatever you have; extras ignored by model.
    Examples:
        await log_call(Call(call_sid=sid, from_number=from_, to_number=to, status="initiated"))
        await log_call(Call(call_sid=sid, status="completed", ended_at=iso_ended))
    """
    payload = {
        "lead_id": call.lead_id,
        "call_sid": call.call_sid,
        "from_number": call.from_number,
        "to_number": call.to_number,
        "status": call.status,
        "started_at": call.started_at,
        "ended_at": call.ended_at,
        "meta": call.meta or {},
        "created_at_ms": _now_ms(),
    }
    ok = await _rest_insert(
        CALLS_TABLE,
        payload,
        on_conflict="call_sid" if UPSERT_ENABLED else None,
        client=client,
    )
    if not ok:
        logger.info("Call log no-op or failed (see warnings).")


async def log_call_event(
    event: CallEvent,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> None:
    """
    Insert a `call_events` row. Capture arbitrary Twilio webhook payloads safely.
    Examples:
        await log_call_event(CallEvent(call_sid=sid, event="ringing", payload=form_dict))
    """
    payload = {
        "call_sid": event.call_sid,
        "event": event.event,
        "created_at": event.created_at,  # allow DB default if None
        "payload": event.payload or {},
        "created_at_ms": _now_ms(),
    }
    ok = await _rest_insert(CALL_EVENTS_TABLE, payload, client=client)
    if not ok:
        logger.info("Call event log no-op or failed (see warnings).")


async def log_script(
    script: LeadScript,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> None:
    """Persist a lead script (upsert on lead_phone + script_id)."""

    payload = {
        "lead_phone": script.lead_phone,
        "script_id": script.script_id,
        "script_text": script.script_text,
        "meta": script.meta or {},
        "created_at": script.created_at,
        "updated_at": script.updated_at,
        "created_at_ms": _now_ms(),
    }

    ok = await _rest_insert(
        SCRIPTS_TABLE,
        payload,
        on_conflict="lead_phone,script_id",
        client=client,
    )
    if not ok:
        logger.info("Lead script log no-op or failed (see warnings).")


async def get_script(
    lead_phone: str,
    script_id: str = "default",
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> Optional[LeadScript]:
    """Fetch a stored lead script by phone + id."""

    cfg = _env_supabase()
    if not cfg:
        print("Supabase credentials missing; cannot fetch lead script.")
        return None

    url = f"{cfg['url']}/rest/v1/{SCRIPTS_TABLE}"
    params = {
        "lead_phone": f"eq.{lead_phone}",
        "script_id": f"eq.{script_id}",
        "select": "*",
        "limit": 1,
    }

    headers = _headers(cfg["key"])
    owns_client = client is None
    http_client = client or httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECS)

    try:
        response = await http_client.get(url, headers=headers, params=params, timeout=DEFAULT_TIMEOUT_SECS)
        if response.status_code != 200:
            logger.warning(
                "Supabase fetch from %s failed: %s %s",
                SCRIPTS_TABLE,
                response.status_code,
                response.text,
            )
            return None

        data = response.json() or []
        if not data:
            return None
        return LeadScript.model_validate(data[0])
    except Exception as e:  # pragma: no cover
        logger.warning("Supabase fetch error on %s: %s", SCRIPTS_TABLE, e)
        return None
    finally:
        if owns_client:
            await http_client.aclose()


# ──────────────────────────────────────────────────────────────────────────────
# Bulk helpers (small batches; safe no-throw)
# ──────────────────────────────────────────────────────────────────────────────

async def bulk_log_call_events(
    events: Sequence[CallEvent],
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> None:
    """
    Efficiently insert many call_events at once.
    """
    if not events:
        return
    rows = [{
        "call_sid": e.call_sid,
        "event": e.event,
        "created_at": e.created_at,
        "payload": e.payload or {},
        "created_at_ms": _now_ms(),
    } for e in events]
    ok = await _rest_insert(CALL_EVENTS_TABLE, rows, client=client)
    if not ok:
        logger.info("Bulk call event log no-op or failed (see warnings).")


async def bulk_log_conversations(
    entries: Sequence[ConversationLog],
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> None:
    """
    Bulk insert for conversation turns (useful for imports/backfills).
    """
    if not entries:
        return
    rows = [{
        "user_input": e.user_input,
        "bot_reply": e.bot_reply,
        "meta": e.meta or {},
        "call_sid": e.call_sid,
        "lead_id": e.lead_id,
        "created_at_ms": _now_ms(),
    } for e in entries]
    ok = await _rest_insert(CONV_TABLE, rows, client=client)
    if not ok:
        logger.info("Bulk conversation log no-op or failed (see warnings).")
