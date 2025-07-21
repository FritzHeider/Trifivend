import io
import openai
import os
from pydub import AudioSegment
from tempfile import NamedTemporaryFile

openai.api_key = os.getenv("OPENAI_API_KEY")

def transcribe_audio(audio_bytes: bytes, sample_rate: int = 44100) -> str:
    # Convert raw bytes to a WAV file that Whisper can read
    audio = AudioSegment.from_file(io.BytesIO(audio_bytes))

    with NamedTemporaryFile(delete=False, suffix=".wav") as tmpfile:
        audio.export(tmpfile.name, format="wav")
        tmpfile_path = tmpfile.name

    with open(tmpfile_path, "rb") as f:
        transcript = openai.Audio.transcribe("whisper-1", f)

    return transcript["text"]