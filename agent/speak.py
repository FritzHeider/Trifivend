"""Utility for converting text to speech using ElevenLabs (sync + async) with presets and per-locale routing."""

from __future__ import annotations

import os
import json
import time
import logging
from collections.abc import AsyncGenerator
from typing import Optional, Tuple, Dict, Any

import aiofiles
import httpx

logger = logging.getLogger(__name__)

# Default known-good voice (Rachel)
_DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"

# Shared async client for low-latency streaming
_SHARED_TTS_CLIENT: httpx.AsyncClient | None = None


# ----------------------------- Presets ---------------------------------------
_PRESETS: Dict[str, Dict[str, Any]] = {
    "outbound_call": {"stability": 0.25, "similarity_boost": 0.85, "style": 0.0, "use_speaker_boost": True},
    "empathetic":    {"stability": 0.70, "similarity_boost": 0.70, "style": 0.35, "use_speaker_boost": True},
    "assertive":     {"stability": 0.30, "similarity_boost": 0.90, "style": 0.15, "use_speaker_boost": True},
    "natural":       {"stability": 0.50, "similarity_boost": 0.75, "style": 0.10, "use_speaker_boost": True},
}


def _resolve_preset_settings(
    preset_name: Optional[str],
    *,
    stability: Optional[float],
    similarity_boost: Optional[float],
    style: Optional[float],
    use_speaker_boost: Optional[bool],
) -> Dict[str, Any]:
    """
    Merge settings from (lowest precedence → highest):
      1) preset (ELEVENLABS_PRESET or provided name)
      2) ELEVENLABS_SETTINGS_JSON (JSON string)
      3) explicit function args (stability, similarity_boost, style, use_speaker_boost)
    """
    settings: Dict[str, Any] = {"stability": 0.4, "similarity_boost": 0.7, "style": 0.0, "use_speaker_boost": True}

    # 1) Preset
    name = (preset_name or os.getenv("ELEVENLABS_PRESET") or "natural").strip()
    if name in _PRESETS:
        settings.update(_PRESETS[name])
    else:
        if preset_name or os.getenv("ELEVENLABS_PRESET"):
            logger.warning("Unknown ELEVENLABS_PRESET '%s' – falling back to defaults.", name)

    # 2) JSON overrides (env)
    raw_json = os.getenv("ELEVENLABS_SETTINGS_JSON", "").strip()
    if raw_json:
        try:
            env_overrides = json.loads(raw_json)
            if isinstance(env_overrides, dict):
                settings.update({k: v for k, v in env_overrides.items() if v is not None})
            else:
                logger.warning("ELEVENLABS_SETTINGS_JSON must be an object; ignoring.")
        except Exception as e:
            logger.warning("Invalid ELEVENLABS_SETTINGS_JSON (%s); ignoring.", e)

    # 3) Explicit args
    if stability is not None:
        settings["stability"] = float(stability)
    if similarity_boost is not None:
        settings["similarity_boost"] = float(similarity_boost)
    if style is not None:
        settings["style"] = float(style)
    if use_speaker_boost is not None:
        settings["use_speaker_boost"] = bool(use_speaker_boost)

    return {
        "stability": float(settings["stability"]),
        "similarity_boost": float(settings["similarity_boost"]),
        "style": float(settings["style"]),
        "use_speaker_boost": bool(settings["use_speaker_boost"]),
    }


# ----------------------------- Locale routing --------------------------------
def _parse_voice_map(raw: str | None) -> Dict[str, str]:
    """
    ELEVENLABS_VOICE_MAP format:
      {
        "en-US": "21m00Tcm4TlvDq8ikWAM",
        "en-GB": "pNInz6obpgDQGcFmaJgB",
        "es-ES": "TxGEqnHWrfWFTfGW9XjX",
        "fr-FR": "bIHbv24MWmeRgasZH58o"
      }
    Keys are BCP-47 locales. Values MUST be ElevenLabs voice IDs (not names).
    """
    if not raw:
        return {}
    try:
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            logger.warning("ELEVENLABS_VOICE_MAP must be a JSON object; ignoring.")
            return {}
        # Normalize keys to lowercase
        return {str(k).lower(): str(v) for k, v in obj.items() if v}
    except Exception as e:
        logger.warning("Invalid ELEVENLABS_VOICE_MAP (%s); ignoring.", e)
        return {}


def _pick_voice_id(
    explicit_voice_id: Optional[str],
    env_voice_id: Optional[str],
    locale_str: Optional[str],
    voice_map: Dict[str, str],
) -> str:
    """
    Priority:
      1) explicit voice_id argument
      2) ELEVENLABS_VOICE_ID env (or legacy ELEVEN_VOICE_ID)
      3) ELEVENLABS_LOCALE (and ELEVENLABS_VOICE_MAP / default fallbacks)
      4) built-in default (_DEFAULT_VOICE_ID)
    Locale fallback logic tries full match (e.g., 'en-us'), then base language ('en').
    """
    # 1) explicit arg
    if explicit_voice_id:
        return explicit_voice_id.strip()

    # 2) env voice id
    if env_voice_id:
        return env_voice_id.strip()

    # 3) locale routing
    loc = (locale_str or os.getenv("ELEVENLABS_LOCALE") or "").strip().lower()
    if loc:
        # full match (en-us)
        if loc in voice_map:
            return voice_map[loc]
        # base language (en)
        base = loc.split("-", 1)[0]
        if base in voice_map:
            return voice_map[base]

    # 4) default
    return _DEFAULT_VOICE_ID


def _resolve_eleven_config(
    *,
    voice_id: Optional[str],
    api_key: Optional[str],
    locale: Optional[str],
) -> Tuple[str, str]:
    """
    Resolve API key and final voice id using overrides, envs, and locale map.
    """
    key = (
        (api_key or "").strip()
        or (os.getenv("ELEVENLABS_API_KEY") or "").strip()
        or (os.getenv("ELEVEN_API_KEY") or "").strip()
    )
    if not key:
        raise RuntimeError("ElevenLabs API key not configured. Set ELEVENLABS_API_KEY (preferred).")

    env_voice = (
        (os.getenv("ELEVENLABS_VOICE_ID") or "").strip()
        or (os.getenv("ELEVEN_VOICE_ID") or "").strip()
        or None
    )
    voice_map = _parse_voice_map(os.getenv("ELEVENLABS_VOICE_MAP"))

    final_voice = _pick_voice_id(voice_id, env_voice, locale, voice_map)
    return key, final_voice


def _get_async_client() -> httpx.AsyncClient:
    """Return a shared httpx.AsyncClient configured for low-latency streaming."""
    global _SHARED_TTS_CLIENT
    if _SHARED_TTS_CLIENT is None:
        _SHARED_TTS_CLIENT = httpx.AsyncClient(
            timeout=httpx.Timeout(60.0),
            http2=True,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            headers={"Connection": "keep-alive"},
        )
    return _SHARED_TTS_CLIENT


# ----------------------------- Public API ------------------------------------
def speak_text(
    text: str,
    *,
    output_path: str = "/tmp/response.mp3",
    timeout: float = 15.0,
    voice_id: Optional[str] = None,
    api_key: Optional[str] = None,
    locale: Optional[str] = None,
    # Preset + per-call overrides
    preset: Optional[str] = None,
    stability: Optional[float] = None,
    similarity_boost: Optional[float] = None,
    style: Optional[float] = None,
    use_speaker_boost: Optional[bool] = None,
) -> str:
    """
    Blocking TTS → saves MP3 to output_path.
    Locale routing:
      - Pass `locale="en-US"` (or set ELEVENLABS_LOCALE) to auto-pick a voice via ELEVENLABS_VOICE_MAP.
      - Explicit `voice_id` and ELEVENLABS_VOICE_ID override locale routing.
    """
    key, vid = _resolve_eleven_config(voice_id=voice_id, api_key=api_key, locale=locale)
    voice_settings = _resolve_preset_settings(
        preset,
        stability=stability,
        similarity_boost=similarity_boost,
        style=style,
        use_speaker_boost=use_speaker_boost,
    )

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{vid}"
    headers = {"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"}
    payload = {"text": text, "voice_settings": voice_settings}

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    try:
        with httpx.Client(timeout=timeout, http2=True) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            with open(output_path, "wb") as f:
                f.write(resp.content)
    except httpx.HTTPStatusError as e:
        raise RuntimeError(_shape_http_error("ElevenLabs TTS failed", e)) from e
    except Exception as e:
        raise RuntimeError(f"ElevenLabs TTS failed: {e}") from e

    return output_path


async def stream_text_to_speech(
    text: str,
    *,
    output_path: str = "/tmp/response.mp3",
    voice_id: Optional[str] = None,
    api_key: Optional[str] = None,
    locale: Optional[str] = None,
    # Preset + per-call overrides
    preset: Optional[str] = None,
    stability: Optional[float] = None,
    similarity_boost: Optional[float] = None,
    style: Optional[float] = None,
    use_speaker_boost: Optional[bool] = None,
    append: bool = False,
    client: Optional[httpx.AsyncClient] = None,
    prebuffer_ms: float = 150.0,
) -> AsyncGenerator[bytes, None]:
    """
    Async streaming TTS → yields chunks while persisting to disk.
    Locale routing works the same as `speak_text`.
    """
    key, vid = _resolve_eleven_config(voice_id=voice_id, api_key=api_key, locale=locale)
    voice_settings = _resolve_preset_settings(
        preset,
        stability=stability,
        similarity_boost=similarity_boost,
        style=style,
        use_speaker_boost=use_speaker_boost,
    )

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{vid}/stream"
    headers = {"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"}
    payload = {"text": text, "voice_settings": voice_settings}

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    client = client or _get_async_client()
    mode = "ab" if append else "wb"

    try:
        async with client.stream("POST", url, headers=headers, json=payload) as resp:
            resp.raise_for_status()
            async with aiofiles.open(output_path, mode) as file_obj:
                first_emit = False
                buffered: list[bytes] = []
                buffered_size = 0
                start_time: Optional[float] = None

                async for chunk in resp.aiter_bytes():
                    if not chunk:
                        continue

                    # Persist immediately
                    await file_obj.write(chunk)

                    # Prebuffer first ~150ms to reduce underruns on Twilio <Play>
                    if not first_emit:
                        buffered.append(chunk)
                        buffered_size += len(chunk)
                        start_time = start_time or time.perf_counter()
                        elapsed = time.perf_counter() - start_time
                        if elapsed >= prebuffer_ms / 1000.0 or buffered_size >= 12_000:
                            for b in buffered:
                                yield b
                            buffered.clear()
                            buffered_size = 0
                            first_emit = True
                    else:
                        yield chunk

                if not first_emit:
                    for b in buffered:
                        yield b

    except httpx.HTTPStatusError as e:
        raise RuntimeError(_shape_http_error("ElevenLabs streaming TTS failed", e)) from e
    except Exception as e:
        raise RuntimeError(f"ElevenLabs streaming TTS failed: {e}") from e


def _shape_http_error(prefix: str, e: httpx.HTTPStatusError) -> str:
    try:
        detail = e.response.json()
    except Exception:
        detail = e.response.text
    return f"{prefix}: {e.response.status_code} {e.request.method} {e.request.url}. Detail: {detail}"
