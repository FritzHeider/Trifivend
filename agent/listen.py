# agent/listen.py
from __future__ import annotations

import logging
import os
import tempfile
from types import SimpleNamespace
from typing import Optional

logger = logging.getLogger("trifivend.listen")

# Optional OpenAI Whisper via SDK
try:
    from app.openai_compat import (
        create_async_openai_client,
        is_openai_available,
        missing_openai_error,
    )
except Exception as e:
    create_async_openai_client = None  # type: ignore
    is_openai_available = lambda: False  # type: ignore
    missing_openai_error = lambda: str(e)  # type: ignore
    logger.warning("OpenAI compat missing in listen: %s", e)


def _placeholder_client() -> SimpleNamespace:
    return SimpleNamespace(
        audio=SimpleNamespace(
            transcriptions=SimpleNamespace(create=None),
        )
    )


client = _placeholder_client()

if create_async_openai_client and callable(is_openai_available) and is_openai_available():
    try:
        maybe_client = create_async_openai_client(os.getenv("OPENAI_API_KEY", ""))
        if maybe_client is not None:
            client = maybe_client  # type: ignore[assignment]
    except Exception as exc:  # pragma: no cover - best effort
        logger.warning("OpenAI client initialization failed: %s", exc)


def _get_transcriber():
    audio = getattr(client, "audio", None)
    transcriptions = getattr(audio, "transcriptions", None)
    return getattr(transcriptions, "create", None)


def transcribe_audio(audio_bytes: bytes, sample_rate: Optional[int] = None) -> str:
    """
    Blocking helper used via run_in_threadpool from FastAPI endpoints.
    Uses OpenAI Whisper if available; otherwise returns a placeholder transcript.
    """
    transcriber = _get_transcriber()

    if callable(transcriber):
        try:
            with tempfile.NamedTemporaryFile(delete=True, suffix=".wav") as tmp:
                tmp.write(audio_bytes)
                tmp.flush()
                with open(tmp.name, "rb") as handle:
                    response = transcriber(
                        model=os.getenv("OPENAI_WHISPER_MODEL", "whisper-1"),
                        file=handle,
                    )
            text = getattr(response, "text", None)
            if text:
                return text.strip() or "(no speech detected)"
        except Exception as exc:
            logger.exception("OpenAI transcription failed: %s", exc)
            raise RuntimeError(f"Transcription failed: {missing_openai_error()}") from exc

    logger.info("OpenAI Whisper unavailable; returning placeholder transcript")
    return "(transcription unavailable; STT not configured)"
