# agent/speak.py
"""Text-to-speech via ElevenLabs (sync + async), with CLI-safe env parsing.
Env supports:
  ELEVENLABS_API_KEY (preferred) or ELEVEN_API_KEY
  ELEVENLABS_VOICE_ID   – explicit voice id (overrides routing)
  ELEVENLABS_LOCALE     – e.g., en-US
  ELEVENLABS_VOICE_MAP  – JSON OR flat: en-US:ID,en-GB:ID,en:ID
  ELEVENLABS_PRESET     – one of {'outbound_call','empathetic','assertive','natural'}
  ELEVENLABS_SETTINGS_JSON – JSON OR ELEVENLABS_SETTINGS flat: stability=0.2,similarity_boost=0.9
"""

from __future__ import annotations

import os
import json
import time
import logging
from collections.abc import AsyncGenerator
from typing import Optional, Tuple, Dict, Any

import aiofiles
import httpx
import requests

logger = logging.getLogger(__name__)

_DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"
_SHARED_TTS_CLIENT: httpx.AsyncClient | None = None

_PRESETS: Dict[str, Dict[str, Any]] = {
    "outbound_call": {"stability": 0.25, "similarity_boost": 0.85, "style": 0.0, "use_speaker_boost": True},
    "empathetic":    {"stability": 0.70, "similarity_boost": 0.70, "style": 0.35, "use_speaker_boost": True},
    "assertive":     {"stability": 0.30, "similarity_boost": 0.90, "style": 0.15, "use_speaker_boost": True},
    "natural":       {"stability": 0.50, "similarity_boost": 0.75, "style": 0.10, "use_speaker_boost": True},
}

def _parse_flat_map(raw: str | None, item_sep: str = ",", kv_sep: str = ":") -> Dict[str, str]:
    if not raw:
        return {}
    out: Dict[str, str] = {}
    for part in raw.split(item_sep):
        part = part.strip()
        if not part or kv_sep not in part:
            continue
        k, v = part.split(kv_sep, 1)
        k = k.strip().lower()
        v = v.strip()
        if k and v:
            out[k] = v
    return out

def _merged_settings_from_env() -> Dict[str, Any]:
    # JSON first, else flat ELEVENLABS_SETTINGS as "k=v,k=v"
    raw_json = (os.getenv("ELEVENLABS_SETTINGS_JSON") or "").strip()
    flat = (os.getenv("ELEVENLABS_SETTINGS") or "").strip()
    merged: Dict[str, Any] = {}
    if raw_json:
        try:
            obj = json.loads(raw_json)
            if isinstance(obj, dict):
                merged.update({k: v for k, v in obj.items() if v is not None})
            else:
                logger.warning("ELEVENLABS_SETTINGS_JSON must be an object; ignoring.")
        except Exception as e:
            logger.warning("Invalid ELEVENLABS_SETTINGS_JSON (%s); ignoring.", e)
    if flat and not raw_json:
        merged.update(_parse_flat_map(flat, item_sep=",", kv_sep="="))
    return merged

def _resolve_preset_settings(
    preset_name: Optional[str],
    *,
    stability: Optional[float],
    similarity_boost: Optional[float],
    style: Optional[float],
    use_speaker_boost: Optional[bool],
) -> Dict[str, Any]:
    """
    Merge settings from (lowest → highest):
      1) preset (ELEVENLABS_PRESET or provided name)
      2) env overrides (JSON or flat ELEVENLABS_SETTINGS)
      3) explicit function args
    """
    settings: Dict[str, Any] = {"stability": 0.4, "similarity_boost": 0.7, "style": 0.0, "use_speaker_boost": True}

    # 1) Preset
    name = (preset_name or os.getenv("ELEVENLABS_PRESET") or "natural").strip()
    if name in _PRESETS:
        settings.update(_PRESETS[name])
    elif preset_name or os.getenv("ELEVENLABS_PRESET"):
        logger.warning("Unknown ELEVENLABS_PRESET '%s' – using defaults.", name)

    # 2) Env overrides (either JSON or flat)
    env_overrides = _merged_settings_from_env()
    if env_overrides:
        for k, v in env_overrides.items():
            if v is not None:
                settings[k] = v

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

def _parse_voice_map(raw_json: str | None, flat_map: str | None) -> Dict[str, str]:
    """
    Accepts either JSON (ELEVENLABS_VOICE_MAP) or a flat CSV map
    ELEVENLABS_VOICE_FLAT like: "en-US:ID,en-GB:ID,en:ID".
    """
    # Prefer JSON if present/valid, else fall back to flat
    if raw_json:
        try:
            obj = json.loads(raw_json)
            if isinstance(obj, dict):
                return {str(k).lower(): str(v) for k, v in obj.items() if v}
            logger.warning("ELEVENLABS_VOICE_MAP must be an object; ignoring.")
        except Exception as e:
            logger.warning("Invalid ELEVENLABS_VOICE_MAP (%s); falling back to flat.", e)
    return _parse_flat_map(flat_map, item_sep=",", kv_sep=":")

def _pick_voice_id(
    explicit_voice_id: Optional[str],
    env_voice_id: Optional[str],
    locale_str: Optional[str],
    voice_map: Dict[str, str],
) -> str:
    """explicit > env voice id > locale map > default."""
    if explicit_voice_id:
        return explicit_voice_id.strip()
    if env_voice_id:
        return env_voice_id.strip()
    loc = (locale_str or os.getenv("ELEVENLABS_LOCALE") or "").strip().lower()
    if loc:
        if loc in voice_map:
            return voice_map[loc]
        base = loc.split("-", 1)[0]
        if base in voice_map:
            return voice_map[base]
    return _DEFAULT_VOICE_ID

def _resolve_eleven_config(
    *,
    voice_id: Optional[str],
    api_key: Optional[str],
    locale: Optional[str],
) -> Tuple[str, str]:
    """Resolve API key and final voice id using overrides, envs, and locale map."""
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
    voice_map = _parse_voice_map(
        os.getenv("ELEVENLABS_VOICE_MAP"),
        os.getenv("ELEVENLABS_VOICE_FLAT"),
    )
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

# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def speak_text(
    text: str,
    output_path: str | None = None,
    *,
    timeout: float = 10.0,
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
    """Blocking TTS → saves MP3 to output_path (default /tmp/response.mp3)."""
    key, vid = _resolve_eleven_config(voice_id=voice_id, api_key=api_key, locale=locale)
    voice_settings = _resolve_preset_settings(
        preset,
        stability=stability,
        similarity_boost=similarity_boost,
        style=style,
        use_speaker_boost=use_speaker_boost,
    )

    target_path = output_path or "/tmp/response.mp3"
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{vid}"
    headers = {"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"}
    payload = {"text": text, "voice_settings": voice_settings}

    os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        with open(target_path, "wb") as f:
            f.write(resp.content)
    except requests.HTTPError as e:
        raise RuntimeError(_shape_http_error("ElevenLabs TTS failed", e)) from e
    except requests.RequestException as e:
        raise RuntimeError(f"ElevenLabs TTS failed: {e}") from e

    return target_path

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
    """Async streaming TTS → yields chunks while persisting to disk."""
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
                start_time: float | None = None

                async for chunk in resp.aiter_bytes():
                    if not chunk:
                        continue

                    await file_obj.write(chunk)

                    # Prebuffer a minimal amount to reduce underruns on <Play>
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

def _shape_http_error(prefix: str, e: Exception) -> str:
    response = getattr(e, "response", None)
    request = getattr(e, "request", None)

    status = getattr(response, "status_code", "?")
    method = getattr(request, "method", "?")
    url_obj = getattr(request, "url", None)
    url = str(url_obj) if url_obj is not None else "?"

    try:
        detail = response.json() if response is not None else ""
    except Exception:
        detail = getattr(response, "text", "")
    return f"{prefix}: {status} {method} {url}. Detail: {detail}"
# agent/speak.py
"""Text-to-speech via ElevenLabs (sync + async), with CLI-safe env parsing.
Env supports:
  ELEVENLABS_API_KEY (preferred) or ELEVEN_API_KEY
  ELEVENLABS_VOICE_ID   – explicit voice id (overrides routing)
  ELEVENLABS_LOCALE     – e.g., en-US
  ELEVENLABS_VOICE_MAP  – JSON OR flat: en-US:ID,en-GB:ID,en:ID
  ELEVENLABS_PRESET     – one of {'outbound_call','empathetic','assertive','natural'}
  ELEVENLABS_SETTINGS_JSON – JSON OR ELEVENLABS_SETTINGS flat: stability=0.2,similarity_boost=0.9
"""

from __future__ import annotations

import os
import json
import time
import logging
from collections.abc import AsyncGenerator
from typing import Optional, Tuple, Dict, Any

import aiofiles
import httpx
import requests

logger = logging.getLogger(__name__)

_DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"
_SHARED_TTS_CLIENT: httpx.AsyncClient | None = None

_PRESETS: Dict[str, Dict[str, Any]] = {
    "outbound_call": {"stability": 0.25, "similarity_boost": 0.85, "style": 0.0, "use_speaker_boost": True},
    "empathetic":    {"stability": 0.70, "similarity_boost": 0.70, "style": 0.35, "use_speaker_boost": True},
    "assertive":     {"stability": 0.30, "similarity_boost": 0.90, "style": 0.15, "use_speaker_boost": True},
    "natural":       {"stability": 0.50, "similarity_boost": 0.75, "style": 0.10, "use_speaker_boost": True},
}

def _parse_flat_map(raw: str | None, item_sep: str = ",", kv_sep: str = ":") -> Dict[str, str]:
    if not raw:
        return {}
    out: Dict[str, str] = {}
    for part in raw.split(item_sep):
        part = part.strip()
        if not part or kv_sep not in part:
            continue
        k, v = part.split(kv_sep, 1)
        k = k.strip().lower()
        v = v.strip()
        if k and v:
            out[k] = v
    return out

def _merged_settings_from_env() -> Dict[str, Any]:
    # JSON first, else flat ELEVENLABS_SETTINGS as "k=v,k=v"
    raw_json = (os.getenv("ELEVENLABS_SETTINGS_JSON") or "").strip()
    flat = (os.getenv("ELEVENLABS_SETTINGS") or "").strip()
    merged: Dict[str, Any] = {}
    if raw_json:
        try:
            obj = json.loads(raw_json)
            if isinstance(obj, dict):
                merged.update({k: v for k, v in obj.items() if v is not None})
            else:
                logger.warning("ELEVENLABS_SETTINGS_JSON must be an object; ignoring.")
        except Exception as e:
            logger.warning("Invalid ELEVENLABS_SETTINGS_JSON (%s); ignoring.", e)
    if flat and not raw_json:
        merged.update(_parse_flat_map(flat, item_sep=",", kv_sep="="))
    return merged

def _resolve_preset_settings(
    preset_name: Optional[str],
    *,
    stability: Optional[float],
    similarity_boost: Optional[float],
    style: Optional[float],
    use_speaker_boost: Optional[bool],
) -> Dict[str, Any]:
    """
    Merge settings from (lowest → highest):
      1) preset (ELEVENLABS_PRESET or provided name)
      2) env overrides (JSON or flat ELEVENLABS_SETTINGS)
      3) explicit function args
    """
    settings: Dict[str, Any] = {"stability": 0.4, "similarity_boost": 0.7, "style": 0.0, "use_speaker_boost": True}

    # 1) Preset
    name = (preset_name or os.getenv("ELEVENLABS_PRESET") or "natural").strip()
    if name in _PRESETS:
        settings.update(_PRESETS[name])
    elif preset_name or os.getenv("ELEVENLABS_PRESET"):
        logger.warning("Unknown ELEVENLABS_PRESET '%s' – using defaults.", name)

    # 2) Env overrides (either JSON or flat)
    env_overrides = _merged_settings_from_env()
    if env_overrides:
        for k, v in env_overrides.items():
            if v is not None:
                settings[k] = v

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

def _parse_voice_map(raw_json: str | None, flat_map: str | None) -> Dict[str, str]:
    """
    Accepts either JSON (ELEVENLABS_VOICE_MAP) or a flat CSV map
    ELEVENLABS_VOICE_FLAT like: "en-US:ID,en-GB:ID,en:ID".
    """
    # Prefer JSON if present/valid, else fall back to flat
    if raw_json:
        try:
            obj = json.loads(raw_json)
            if isinstance(obj, dict):
                return {str(k).lower(): str(v) for k, v in obj.items() if v}
            logger.warning("ELEVENLABS_VOICE_MAP must be an object; ignoring.")
        except Exception as e:
            logger.warning("Invalid ELEVENLABS_VOICE_MAP (%s); falling back to flat.", e)
    return _parse_flat_map(flat_map, item_sep=",", kv_sep=":")

def _pick_voice_id(
    explicit_voice_id: Optional[str],
    env_voice_id: Optional[str],
    locale_str: Optional[str],
    voice_map: Dict[str, str],
) -> str:
    """explicit > env voice id > locale map > default."""
    if explicit_voice_id:
        return explicit_voice_id.strip()
    if env_voice_id:
        return env_voice_id.strip()
    loc = (locale_str or os.getenv("ELEVENLABS_LOCALE") or "").strip().lower()
    if loc:
        if loc in voice_map:
            return voice_map[loc]
        base = loc.split("-", 1)[0]
        if base in voice_map:
            return voice_map[base]
    return _DEFAULT_VOICE_ID

def _resolve_eleven_config(
    *,
    voice_id: Optional[str],
    api_key: Optional[str],
    locale: Optional[str],
) -> Tuple[str, str]:
    """Resolve API key and final voice id using overrides, envs, and locale map."""
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
    voice_map = _parse_voice_map(
        os.getenv("ELEVENLABS_VOICE_MAP"),
        os.getenv("ELEVENLABS_VOICE_FLAT"),
    )
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

# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def speak_text(
    text: str,
    output_path: str | None = None,
    *,
    timeout: float = 10.0,
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
    """Blocking TTS → saves MP3 to output_path (default /tmp/response.mp3)."""
    key, vid = _resolve_eleven_config(voice_id=voice_id, api_key=api_key, locale=locale)
    voice_settings = _resolve_preset_settings(
        preset,
        stability=stability,
        similarity_boost=similarity_boost,
        style=style,
        use_speaker_boost=use_speaker_boost,
    )

    target_path = output_path or "/tmp/response.mp3"
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{vid}"
    headers = {"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"}
    payload = {"text": text, "voice_settings": voice_settings}

    os.makedirs(os.path.dirname(target_path) or ".", exist_ok=True)

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        with open(target_path, "wb") as f:
            f.write(resp.content)
    except requests.HTTPError as e:
        raise RuntimeError(_shape_http_error("ElevenLabs TTS failed", e)) from e
    except requests.RequestException as e:
        raise RuntimeError(f"ElevenLabs TTS failed: {e}") from e

    return target_path

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
    """Async streaming TTS → yields chunks while persisting to disk."""
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
                start_time: float | None = None

                async for chunk in resp.aiter_bytes():
                    if not chunk:
                        continue

                    await file_obj.write(chunk)

                    # Prebuffer a minimal amount to reduce underruns on <Play>
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

def _shape_http_error(prefix: str, e: Exception) -> str:
    response = getattr(e, "response", None)
    request = getattr(e, "request", None)

    status = getattr(response, "status_code", "?")
    method = getattr(request, "method", "?")
    url_obj = getattr(request, "url", None)
    url = str(url_obj) if url_obj is not None else "?"

    try:
        detail = response.json() if response is not None else ""
    except Exception:
        detail = getattr(response, "text", "")
    return f"{prefix}: {status} {method} {url}. Detail: {detail}"
