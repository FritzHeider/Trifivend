"""Speech-to-text helpers using OpenAI Whisper."""

import os
import tempfile
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


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
