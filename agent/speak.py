"""Utility for converting text to speech using ElevenLabs."""

from __future__ import annotations

import os
from collections.abc import AsyncGenerator
from typing import Optional

import aiofiles
import httpx
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


async def stream_text_to_speech(
    text: str,
    *,
    output_path: str = "/tmp/response.mp3",
    voice_id: Optional[str] = None,
    api_key: Optional[str] = None,
    stability: float = 0.4,
    similarity_boost: float = 0.7,
    append: bool = False,
    client: Optional[httpx.AsyncClient] = None,
) -> AsyncGenerator[bytes, None]:
    """Stream ElevenLabs audio while persisting it to disk.

    Parameters
    ----------
    text:
        Text to synthesise.
    output_path:
        Target file for the resulting MP3 chunks.
    voice_id / api_key:
        Optional overrides for environment configuration.
    append:
        When ``True`` the audio is appended to ``output_path`` instead of
        overwriting it (useful for multi-request pipelines).
    client:
        Optional shared ``httpx.AsyncClient``.
    """

    resolved_voice = voice_id or os.getenv("ELEVEN_VOICE_ID", "Rachel")
    resolved_key = api_key or os.getenv("ELEVEN_API_KEY")

    if not resolved_key:
        raise RuntimeError("ELEVEN_API_KEY is not configured")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{resolved_voice}/stream"
    headers = {
        "xi-api-key": resolved_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": text,
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity_boost,
        },
    }

    dirname = os.path.dirname(output_path)
    if dirname:
        os.makedirs(dirname, exist_ok=True)

    owns_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))
        owns_client = True

    mode = "ab" if append else "wb"
    try:
        async with client.stream("POST", url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            async with aiofiles.open(output_path, mode) as file_obj:
                async for chunk in resp.aiter_bytes():
                    if not chunk:
                        continue
                    await file_obj.write(chunk)
                    yield chunk
    except Exception as e:  # pragma: no cover - network errors surface upstream
        raise RuntimeError(f"ElevenLabs streaming TTS failed: {str(e)}") from e
    finally:
        if owns_client:
            await client.aclose()
