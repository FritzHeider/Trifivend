# app/openai_compat.py
from __future__ import annotations

import os
import logging

logger = logging.getLogger("trifivend.openai")

try:
    from openai import AsyncOpenAI
except Exception as e:
    AsyncOpenAI = None  # type: ignore[assignment]
    _import_error = e
else:
    _import_error = None


def create_async_openai_client(api_key: str | None = None):
    """Return an AsyncOpenAI client when the SDK is installed.

    The application should degrade gracefully when the dependency is missing,
    so we simply return ``None`` instead of raising at import time.  Callers are
    expected to feature-detect with :func:`is_openai_available`.
    """

    if AsyncOpenAI is None:
        logger.warning("OpenAI SDK unavailable; returning None client")
        return None

    key = api_key or os.getenv("OPENAI_API_KEY") or ""
    return AsyncOpenAI(api_key=key)


def is_openai_available() -> bool:
    return AsyncOpenAI is not None


def missing_openai_error() -> str:
    return str(_import_error) if _import_error else "unknown error"
