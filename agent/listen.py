# agent/listen.py
"""Speech-to-text helpers using OpenAI STT (Whisper or GPT-4o transcribe), safe & lazy."""

from __future__ import annotations

import logging
import os
import tempfile
from typing import Optional

from app.openai_compat import (
    create_sync_openai_client,
    is_openai_available,
    missing_openai_error,
    get_stt_model,  # resolves OPENAI_STT_MODEL with a sane default
)

logger = logging.getLogger(__name__)

# Lazily created client cache (no import-time side effects)
_client = None


def _get_client():
    """Create/reuse a sync OpenAI client. Never raises at import time."""
    global _client
    if _client is not None:
        return _client

    if not is_openai_available():
        msg = missing_openai_error()
        logger.warning("OpenAI unavailable; transcription will fail: %s", msg)
        raise RuntimeError(f"OpenAI not available: {msg}")

    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    client = create_sync_openai_client(api_key=api_key)
    if client is None:
        raise RuntimeError("Failed to instantiate OpenAI client (see logs).")

    _client = client
    return _client


def _suffix_for_bytes(default_suffix: str = ".wav") -> str:
    """
    Cheap best-effort file suffix. We default to .wav since Twilio typically sends PCM/WAV,
    but ElevenLabs/TTS returns MP3 – upstream callers can override if they know better.
    """
    # You can get fancy here (magic numbers), but it's not necessary for OpenAI STT.
    return default_suffix


def transcribe_audio(
    audio_bytes: bytes,
    sample_rate: int,  # kept for backward compat; OpenAI API doesn't require it
    *,
    model: Optional[str] = None,          # e.g. "whisper-1" or "gpt-4o-mini-transcribe"
    language: Optional[str] = None,       # BCP-47 like "en" | "en-US" (Whisper supports "language")
    prompt: Optional[str] = None,         # optional biasing prompt
    temperature: Optional[float] = None,  # some STT models accept it; ignored otherwise
    response_format: Optional[str] = None # "json" | "text" (varies by model; "text" is typical)
) -> str:
    """
    Return the transcription text for the given audio bytes.

    Model selection:
      - If `model` arg is provided, use that.
      - Else read from env OPENAI_STT_MODEL (via get_stt_model()), default "whisper-1".
      - Examples: "whisper-1", "gpt-4o-mini-transcribe".

    Raises:
      RuntimeError on configuration or API errors.
    """
    client = _get_client()
    chosen_model = (model or get_stt_model("whisper-1")).strip()

    # Write audio to a temp file for the SDK (required by current API)
    suffix = _suffix_for_bytes(".wav")
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        # Build kwargs only with fields the SDK/model is likely to accept.
        # The OpenAI v1 Python SDK will ignore unknown extras for STT endpoints.
        kwargs = {"model": chosen_model}

        # Whisper accepts "language" (ISO-639-1 like "en"); GPT-4o-* transcribe can ignore it.
        if language:
            kwargs["language"] = language

        # Optional hints some engines accept (safe to pass; ignored otherwise).
        if prompt:
            kwargs["prompt"] = prompt
        if temperature is not None:
            kwargs["temperature"] = float(temperature)
        if response_format:
            kwargs["response_format"] = response_format

        with open(tmp_path, "rb") as f:
            # Unified STT path in OpenAI Python SDK (v1.x)
            resp = client.audio.transcriptions.create(file=f, **kwargs)

        # Common shape for Whisper: resp.text
        # Some models may return object-like responses; be defensive:
        text = getattr(resp, "text", None)
        if not text:
            # Try a few likely places; if none, stringify:
            text = getattr(resp, "content", None) or getattr(resp, "output", None) or str(resp)
        return text

    except Exception as e:
        raise RuntimeError(f"Transcription failed ({chosen_model}): {e}") from e
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass
