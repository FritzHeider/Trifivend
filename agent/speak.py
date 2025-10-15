"""Speech synthesis helpers."""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger("trifivend.speak")

_DEFAULT_OUTPUT = Path("/tmp/response.mp3")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def speak_text(text: str, output_path: Optional[str] = None, *, timeout: float = 10.0) -> str:
    """Synthesize ``text`` using ElevenLabs and return the written file path.

    The helper mirrors the behaviour used by the FastAPI endpoints while also
    being test-friendly:

    * API credentials come from ``ELEVEN_API_KEY`` / ``ELEVEN_VOICE_ID``.
    * ``output_path`` defaults to ``/tmp/response.mp3`` to keep existing
      integrations working.
    * Network errors raise ``RuntimeError`` so callers can handle fallbacks.
    """

    api_key = _env("ELEVEN_API_KEY")
    voice_id = _env("ELEVEN_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
    target = Path(output_path) if output_path else _DEFAULT_OUTPUT

    if not api_key:
        raise RuntimeError("ElevenLabs TTS failed: ELEVEN_API_KEY not configured")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    payload = {
        "text": text,
        "model_id": _env("ELEVEN_MODEL", "eleven_multilingual_v2"),
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.7},
    }
    headers = {
        "xi-api-key": api_key,
        "accept": "audio/mpeg",
        "content-type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=timeout)
        response.raise_for_status()
    except requests.RequestException as exc:  # pragma: no cover - network path
        logger.exception("ElevenLabs synthesis request failed")
        raise RuntimeError("ElevenLabs TTS failed") from exc

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(response.content)
    return str(target)
