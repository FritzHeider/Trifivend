# app/voicebot.py
from __future__ import annotations

import os
import logging
from typing import List, Dict, Any

logger = logging.getLogger("trifivend.voicebot")

try:
    from app.openai_compat import create_async_openai_client, is_openai_available
except Exception as e:
    create_async_openai_client = None  # type: ignore
    is_openai_available = lambda: False  # type: ignore
    logger.warning("OpenAI compat missing in voicebot: %s", e)

SYSTEM_PROMPT = (
    "You are Ava, a concise, friendly AI cold-caller for TriFiVend. "
    "Qualify property managers for installing premium vending machines. "
    "Ask one question at a time. Keep replies under 25 words."
)

def _trim(text: str, limit: int = 250) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else (text[:limit] + "…")

def coldcall_lead(messages: List[Dict[str, Any]]) -> str:
    """
    Synchronous helper used from threadpool. If OpenAI is present, call it;
    otherwise return a deterministic, helpful canned reply for testing.
    messages: [{"role":"user"|"system"|"assistant","content": "..."}]
    """
    user_utterance = ""
    for m in messages[::-1]:
        if m.get("role") == "user":
            user_utterance = str(m.get("content") or "")
            break

    if is_openai_available and is_openai_available():
        try:
            client = create_async_openai_client(os.getenv("OPENAI_API_KEY", ""))
            # Call chat completions synchronously via .run call (we're in a threadpool)
            import asyncio
            async def _go():
                resp = await client.chat.completions.create(
                    model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                    messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
                    temperature=0.4,
                    max_tokens=90,
                )
                return resp.choices[0].message.content.strip()

            return asyncio.run(_go())  # isolated thread event loop
        except Exception:
            logger.exception("OpenAI chat failure; falling back")

    # Fallback deterministic script
    if not user_utterance:
        return "Hi! Quick question—do you manage multi-unit properties that allow vending machines?"
    if "busy" in user_utterance.lower():
        return "Totally get it. When’s a better time for a 60-second call—today afternoon or tomorrow morning?"
    return "Great. Roughly how many units does your property have and is there foot traffic near a lobby or gym?"
