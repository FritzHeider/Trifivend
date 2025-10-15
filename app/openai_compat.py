# app/openai_compat.py
from __future__ import annotations

import os
import logging

logger = logging.getLogger("trifivend.openai")

try:
    from openai import AsyncOpenAI
except Exception as e:
    AsyncOpenAI = None  # type: ignore
    _import_error = e
else:
    _import_error = None


def create_async_openai_client(api_key: str | None = None):
    if AsyncOpenAI is None:
        raise RuntimeError(f"openai SDK unavailable: {_import_error}")
    key = api_key or os.getenv("OPENAI_API_KEY") or ""
    return AsyncOpenAI(api_key=key)


def is_openai_available() -> bool:
    return AsyncOpenAI is not None


def missing_openai_error() -> str:
    return str(_import_error) if _import_error else "unknown error"
