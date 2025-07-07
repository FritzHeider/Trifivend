import os
import openai
import tempfile
import sounddevice as sd
import soundfile as sf
from dotenv import load_dotenv

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

def record_audio(duration=5, samplerate=44100):
    print("🎤 Listening...")
    audio = sd.rec(int(duration * samplerate), samplerate=samplerate, channels=1)
    sd.wait()
    print("🛑 Recording finished.")
    return audio, samplerate

def transcribe_audio(audio, samplerate):
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        sf.write(tmp.name, audio, samplerate)
        audio_file = open(tmp.name, "rb")
        transcript = openai.Audio.transcribe("whisper-1", audio_file)
        return transcript["text"]

def listen():
    audio, sr = record_audio()
    return transcribe_audio(audio, sr)

if __name__ == "__main__":
    text = listen()
    print("📝 You said:", text)