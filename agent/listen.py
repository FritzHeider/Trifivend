import openai

def transcribe_audio(audio_bytes: bytes, sample_rate: int) -> str:
    try:
        return openai.Audio.transcribe("whisper-1", audio_bytes)["text"]
    except Exception as e:
        raise RuntimeError(f"Transcription failed: {str(e)}")
