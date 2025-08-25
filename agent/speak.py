"""Utility for converting text to speech using ElevenLabs."""

import os
import requests


def speak_text(
    text: str,
    output_path: str = "/tmp/response.mp3",
    timeout: float = 10.0,
) -> str:
    """Convert ``text`` to speech and save it to ``output_path``.

    Parameters
    ----------
    text:
        The text to convert to speech.
    output_path:
        Where the resulting MP3 should be written. Defaults to ``/tmp/response.mp3``.
    timeout:
        Number of seconds to wait for the ElevenLabs API response. Defaults to 10 seconds.

    Returns
    -------
    str
        The path to the generated audio file.
    """

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
        response = requests.post(url, headers=headers, json=data, timeout=timeout)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"ElevenLabs TTS failed: {str(e)}") from e

    with open(output_path, "wb") as f:
        f.write(response.content)

    return output_path
