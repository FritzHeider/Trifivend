# agent/speak.py
from __future__ import annotations

import logging
import os

logger = logging.getLogger("trifivend.speak")

ELEVEN_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")

def speak_text(text: str) -> None:
    """
    Blocking helper that synthesizes to /tmp/response.mp3 for dev paths.
    In prod, prefer chunked signed URLs via tts_chunker (handled upstream).
    If ElevenLabs is configured, try a quick synth; otherwise write a tiny silent MP3 placeholder.
    """
    out_path = "/tmp/response.mp3"

    if ELEVEN_API_KEY:
        try:
            import requests
            voice_id = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")  # Rachel default
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
            payload = {
                "text": text[:1000],
                "model_id": os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2"),
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.7},
            }
            headers = {
                "xi-api-key": ELEVEN_API_KEY,
                "accept": "audio/mpeg",
                "content-type": "application/json",
            }
            r = requests.post(url, json=payload, headers=headers, timeout=30)
            r.raise_for_status()
            with open(out_path, "wb") as f:
                f.write(r.content)
            return
        except Exception:
            logger.exception("ElevenLabs synthesis failed; writing placeholder mp3")

    # Fallback: emit a tiny silent MP3 (1 frame) so clients don’t 404
    try:
        # 1-second of silence MP3 frame (pre-encoded). This is a tiny constant byte-string.
        SILENT_MP3 = (
            b"\x49\x44\x33\x03\x00\x00\x00\x00\x00\x21\x54\x41\x4c\x42\x00\x00\x00\x0f\x00\x00"
            b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xfb\x90\x64\x00\x0f\xff\xfc\x21\x84"
        )
        with open(out_path, "wb") as f:
            f.write(SILENT_MP3)
    except Exception:
        logger.exception("Failed to write placeholder MP3")