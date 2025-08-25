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


class Lead(BaseModel):
    """Metadata describing a call target."""

    name: str
    phone: str
    property_type: str
    location_area: str
    callback_offer: str | None = None

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc), alias="created_at"
    )


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


async def log_lead(lead: Lead, *, client: Optional[httpx.AsyncClient] = None) -> None:
    """Persist ``lead`` information to Supabase."""

    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY")

    if not supabase_url or not supabase_key:
        print("⚠️ Supabase credentials missing — skipping lead log.")
        return

    owns_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=10.0)
        owns_client = True

    try:
        await client.post(
            f"{supabase_url}/rest/v1/leads",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
                "Content-Type": "application/json",
                "Prefer": "return=minimal",
            },
            json=lead.model_dump(mode="json"),
        )
    except Exception as e:  # pragma: no cover - network errors just logged
        print(f"Supabase lead log error: {e}")
    finally:
        if owns_client:
            await client.aclose()


__all__ = ["ConversationLog", "log_conversation", "Lead", "log_lead"]

