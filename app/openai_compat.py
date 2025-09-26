"""Compatibility helpers for working with the optional OpenAI SDK.

The production code relies on the :mod:`openai` package, but unit tests
should be able to run without the dependency (or when the installed version
is temporarily incompatible).  This module centralises the import logic and
provides graceful fallbacks that surface clear runtime errors only when an
API call is attempted.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional

try:  # pragma: no cover - exercised implicitly when dependency is available
    from openai import AsyncOpenAI as _AsyncOpenAI, OpenAI as _OpenAI
except Exception as exc:  # pragma: no cover - import failure path tested below
    _SDK_AVAILABLE = False
    _IMPORT_ERROR = exc
    _ERROR_MESSAGE = (
        "OpenAI SDK is not available (import error: "
        f"{exc!r}). Install a compatible `openai` package to enable AI features."
    )

    def _missing_callable(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError(_ERROR_MESSAGE)

    def create_async_openai_client(*, api_key: Optional[str] = None):
        """Return a stub that raises a clear error when used."""

        return SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=_missing_callable)
            )
        )

    def create_sync_openai_client(*, api_key: Optional[str] = None):
        """Return a stub that raises a clear error when used."""

        return SimpleNamespace(
            audio=SimpleNamespace(
                transcriptions=SimpleNamespace(create=_missing_callable)
            )
        )
else:  # pragma: no cover - behaviour verified via smoke tests
    _SDK_AVAILABLE = True
    _IMPORT_ERROR = None

    def create_async_openai_client(*, api_key: Optional[str] = None):
        return _AsyncOpenAI(api_key=api_key)

    def create_sync_openai_client(*, api_key: Optional[str] = None):
        return _OpenAI(api_key=api_key)


def is_openai_available() -> bool:
    """Return ``True`` when the OpenAI SDK imported successfully."""

    return _SDK_AVAILABLE


def missing_openai_error() -> Optional[Exception]:
    """Expose the original import error, if any, for diagnostics."""

    return _IMPORT_ERROR


__all__ = [
    "create_async_openai_client",
    "create_sync_openai_client",
    "is_openai_available",
    "missing_openai_error",
]
