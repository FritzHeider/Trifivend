import os
import requests

def speak_text(text: str):
    voice_id = os.getenv("ELEVEN_VOICE_ID", "Rachel")
    eleven_key = os.getenv("ELEVEN_API_KEY")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": eleven_key,
        "Content-Type": "application/json"
    }
    data = {
        "text": text,
        "voice_settings": {
            "stability": 0.4,
            "similarity_boost": 0.7
        }
    }

    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"ElevenLabs TTS failed: {str(e)}")

    with open("/tmp/response.mp3", "wb") as f:
        f.write(response.content)