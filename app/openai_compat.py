# app/openai_compat.py
"""Compatibility layer for OpenAI SDK (safe, lazy, async + sync)."""

from __future__ import annotations

import os
import logging
from typing import Optional, Any, Tuple

logger = logging.getLogger(__name__)

# Cache import error for diagnostics
_OPENAI_IMPORT_ERR: Optional[str] = None


def _import_openai() -> Tuple[Optional[Any], Optional[Any]]:
    """
    Lazily import the OpenAI SDK.
    Returns (AsyncOpenAI, OpenAI) or (None, None) if unavailable.
    """
    global _OPENAI_IMPORT_ERR
    try:
        from openai import AsyncOpenAI, OpenAI  # type: ignore
        return AsyncOpenAI, OpenAI
    except Exception as e:  # pragma: no cover
        _OPENAI_IMPORT_ERR = f"{type(e).__name__}: {e}"
        return None, None


def _resolve_key(explicit: Optional[str] = None) -> Optional[str]:
    key = (explicit or os.getenv("OPENAI_API_KEY") or "").strip()
    return key or None


def create_async_openai_client(api_key: Optional[str] = None) -> Optional[Any]:
    """
    Create an AsyncOpenAI client if SDK + key are present; otherwise return None.
    No network calls. Safe to invoke at any time.
    """
    AsyncOpenAI, _ = _import_openai()
    if AsyncOpenAI is None:
        logger.warning("OpenAI SDK not importable: %s", _OPENAI_IMPORT_ERR)
        return None

    key = _resolve_key(api_key)
    if not key:
        logger.warning("OPENAI_API_KEY not set; async OpenAI client disabled.")
        return None

    try:
        return AsyncOpenAI(api_key=key)
    except Exception as e:  # pragma: no cover
        logger.error("Failed to instantiate AsyncOpenAI: %s", e)
        return None


def create_sync_openai_client(api_key: Optional[str] = None) -> Optional[Any]:
    """
    Create a synchronous OpenAI client if SDK + key are present; otherwise None.
    No network calls. Safe to invoke at any time.
    """
    _, OpenAI = _import_openai()
    if OpenAI is None:
        logger.warning("OpenAI SDK not importable: %s", _OPENAI_IMPORT_ERR)
        return None

    key = _resolve_key(api_key)
    if not key:
        logger.warning("OPENAI_API_KEY not set; sync OpenAI client disabled.")
        return None

    try:
        return OpenAI(api_key=key)
    except Exception as e:  # pragma: no cover
        logger.error("Failed to instantiate OpenAI client: %s", e)
        return None


def is_openai_available() -> bool:
    """True only if the SDK can import AND an API key is present."""
    AsyncOpenAI, OpenAI = _import_openai()
    if AsyncOpenAI is None and OpenAI is None:
        return False
    return bool((os.getenv("OPENAI_API_KEY") or "").strip())


def missing_openai_error() -> str:
    """Human-readable reason why OpenAI is unavailable."""
    if _OPENAI_IMPORT_ERR:
        return f"OpenAI SDK import failed: {_OPENAI_IMPORT_ERR}"
    if not (os.getenv("OPENAI_API_KEY") or "").strip():
        return "OPENAI_API_KEY is not set."
    return "Unknown OpenAI issue."


# -------- Optional tiny helpers (non-breaking) --------------------------------

def get_chat_model(default: str = "gpt-4o-mini") -> str:
    """
    Resolve chat/completions model from env (OPENAI_MODEL) with a sane default.
    """
    return (os.getenv("OPENAI_MODEL") or default).strip()


def get_stt_model(default: str = "whisper-1") -> str:
    """
    Resolve speech-to-text model from env (OPENAI_STT_MODEL), e.g.:
      - whisper-1
      - gpt-4o-mini-transcribe
    """
    return (os.getenv("OPENAI_STT_MODEL") or default).strip()
