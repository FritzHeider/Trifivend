# agent/listen.py
from __future__ import annotations

import io
import logging
import os
from typing import Optional

logger = logging.getLogger("trifivend.listen")

# Optional OpenAI Whisper via SDK
try:
    from app.openai_compat import create_async_openai_client, is_openai_available
except Exception as e:
    create_async_openai_client = None  # type: ignore
    is_openai_available = lambda: False  # type: ignore
    logger.warning("OpenAI compat missing in listen: %s", e)


def transcribe_audio(audio_bytes: bytes, sample_rate_hz: int) -> str:
    """
    Blocking helper used via run_in_threadpool from FastAPI endpoints.
    Uses OpenAI Whisper if available; otherwise returns a placeholder transcript.
    """
    if is_openai_available and is_openai_available():
        try:
            client = create_async_openai_client(api_key=os.getenv("OPENAI_API_KEY", ""))
            # Use the sync upload convenience even from a thread
            # The compat client exposes .audio.transcriptions or chat multimodal depending on version.
            # Keep it simple: fallback "transcribed" if unsupported.
            try:
                # Newer SDKs:
                import tempfile
                with tempfile.NamedTemporaryFile(delete=True, suffix=".wav") as tmp:
                    tmp.write(audio_bytes)
                    tmp.flush()
                    # Whisper-1 style
                    resp = client.audio.transcriptions.create(  # type: ignore[attr-defined]
                        model=os.getenv("OPENAI_WHISPER_MODEL", "whisper-1"),
                        file=open(tmp.name, "rb"),
                    )
                text = getattr(resp, "text", None) or ""
                return text.strip() or "(no speech detected)"
            except Exception:
                logger.exception("Whisper transcription path failed; falling back")
        except Exception:
            logger.exception("Failed to create OpenAI client in transcribe")
    # Fallback
    return "(transcription unavailable; STT not configured)"
