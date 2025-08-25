"""Asynchronous utility to log conversations to Supabase.

This module provides a small data model and helper function for persisting
conversation transcripts.  The previous implementation used the synchronous
``httpx.Client`` which could block the main event loop.  The new version uses an
``AsyncClient`` and a Pydantic model for stronger typing and easier testing.
"""

from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Optional

import httpx
from pydantic import BaseModel, Field


class ConversationLog(BaseModel):
    """Structured representation of a single conversation exchange."""

    user_input: str
    bot_reply: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class LeadScript(BaseModel):
    """Persisted script and system prompt for a lead."""

    lead_name: str
    call_script: str
    system_prompt: str


async def log_conversation(
    log: ConversationLog, *, client: Optional[httpx.AsyncClient] = None
) -> None:
    """Persist ``log`` to Supabase if credentials are available.

    Parameters
    ----------
    log:
        The conversation to persist.
    client:
        Optional ``httpx.AsyncClient`` instance.  Primarily used for testing.
    """

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY")

    if not supabase_url or not supabase_key:
        print("⚠️ Supabase credentials missing — skipping log.")
        return

    owns_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=10.0)
        owns_client = True

    try:
        await client.post(
            f"{supabase_url}/rest/v1/conversations",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json=log.model_dump(mode="json"),
        )
    except Exception as e:  # pragma: no cover - network errors just logged
        print(f"Supabase log error: {e}")
    finally:
        if owns_client:
            await client.aclose()


async def log_lead_script(
    log: LeadScript, *, client: Optional[httpx.AsyncClient] = None
) -> None:
    """Store the ``log`` for reuse of prompts per lead."""

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY")

    if not supabase_url or not supabase_key:
        print("⚠️ Supabase credentials missing — skipping log.")
        return

    owns_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=10.0)
        owns_client = True

    try:
        await client.post(
            f"{supabase_url}/rest/v1/lead_scripts",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json=log.model_dump(mode="json"),
        )
    except Exception as e:  # pragma: no cover
        print(f"Supabase log error: {e}")
    finally:
        if owns_client:
            await client.aclose()


async def fetch_lead_script(
    lead_name: str, *, client: Optional[httpx.AsyncClient] = None
) -> Optional[LeadScript]:
    """Retrieve previously stored script/prompt for ``lead_name``."""

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY")

    if not supabase_url or not supabase_key:
        return None

    owns_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=10.0)
        owns_client = True

    try:
        resp = await client.get(
            f"{supabase_url}/rest/v1/lead_scripts",
            params={"lead_name": f"eq.{lead_name}", "limit": 1},
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
            },
        )
        data = resp.json()
        if data:
            return LeadScript(**data[0])
    except Exception:  # pragma: no cover
        return None
    finally:
        if owns_client:
            await client.aclose()

    return None


__all__ = [
    "ConversationLog",
    "LeadScript",
    "log_conversation",
    "log_lead_script",
    "fetch_lead_script",
]

