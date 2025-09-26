"""Speech-to-text helpers using OpenAI Whisper."""

import logging
import os
import tempfile

from app.openai_compat import (
    create_sync_openai_client,
    is_openai_available,
    missing_openai_error,
)

logger = logging.getLogger(__name__)
client = create_sync_openai_client(api_key=os.getenv("OPENAI_API_KEY"))
if not is_openai_available():  # pragma: no cover - exercised in dependency-free tests
    logger.warning(
        "OpenAI SDK unavailable; transcription requests will raise until installed: %s",
        missing_openai_error(),
    )


def transcribe_audio(audio_bytes: bytes, sample_rate: int) -> str:
    """Return the transcription text for the given audio."""
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name
        try:
            with open(tmp_path, "rb") as f:
                transcription = client.audio.transcriptions.create(
                    model="whisper-1", file=f
                )
                return transcription.text
        finally:
            os.remove(tmp_path)
    except Exception as e:
        raise RuntimeError(f"Transcription failed: {str(e)}") from e
