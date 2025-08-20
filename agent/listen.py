"""Speech-to-text helpers using OpenAI Whisper."""

import openai
import os
import tempfile


def transcribe_audio(audio_bytes: bytes, sample_rate: int) -> str:
    """Return the transcription text for the given audio."""
    try:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name
        try:
            with open(tmp_path, "rb") as f:
                return openai.Audio.transcribe("whisper-1", f)["text"]
        finally:
            os.remove(tmp_path)
    except Exception as e:
        raise RuntimeError(f"Transcription failed: {str(e)}") from e
