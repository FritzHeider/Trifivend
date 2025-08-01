"""Speech-to-text helpers using OpenAI Whisper."""

import openai


def transcribe_audio(audio_bytes: bytes, sample_rate: int) -> str:
    """Return the transcription text for the given audio."""
    try:
        return openai.Audio.transcribe("whisper-1", audio_bytes)["text"]
    except Exception as e:
        raise RuntimeError(f"Transcription failed: {str(e)}") from e
