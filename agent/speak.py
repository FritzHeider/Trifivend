import os
import requests

ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY")
VOICE_ID = os.getenv("ELEVEN_VOICE_ID", "Rachel")  # or use your custom voice ID

def speak_text(text: str) -> bytes:
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE_ID}"

    headers = {
        "xi-api-key": ELEVEN_API_KEY,
        "Content-Type": "application/json"
    }

    payload = {
        "text": text,
        "model_id": "eleven_monolingual_v1",
        "voice_settings": {
            "stability": 0.4,
            "similarity_boost": 0.75
        }
    }

    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()

    # Save response to a predictable file for Twilio to fetch
    mp3_path = "/tmp/response.mp3"
    with open(mp3_path, "wb") as f:
        f.write(response.content)

    return response.content  # Optional: return raw bytes if needed