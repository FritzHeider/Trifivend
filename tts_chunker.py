# tts_chunker.py
# Chunked TTS → Supabase signed URLs for Twilio <Play>
from __future__ import annotations

import os
import re
import time
import uuid
import json
import tempfile
import logging
from typing import List, Optional, Dict, Any

import requests
from supabase import create_client, Client

# ──────────────────────────────────────────────────────────────────────────────
# Config (env)
# ──────────────────────────────────────────────────────────────────────────────
LOG = logging.getLogger("tts_chunker")
if not LOG.handlers:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(),
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")  # SERVICE ROLE KEY (server-side only)
SUPABASE_BUCKET: str = os.getenv("SUPABASE_BUCKET", "call-audio")

ELEVEN_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")
ELEVEN_VOICE_ID_DEFAULT: str = os.getenv("ELEVENLABS_VOICE_ID", "Rachel")  # set yours
ELEVEN_MODEL_ID: str = os.getenv("ELEVENLABS_MODEL_ID", "eleven_monolingual_v1")
ELEVEN_OUTPUT_FORMAT: str = os.getenv("ELEVENLABS_AUDIO_FORMAT", "mp3_32")  # tiny + fast

# Requests tunables
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "15"))       # seconds
HTTP_RETRIES = int(os.getenv("HTTP_RETRIES", "3"))
RETRY_BACKOFF = float(os.getenv("RETRY_BACKOFF", "0.8"))    # seconds
CHUNK_MAX_CHARS = int(os.getenv("TTS_CHUNK_MAX_CHARS", "280"))

# Validate critical env early (don’t crash imports; log loudly instead)
if not SUPABASE_URL or not SUPABASE_KEY:
    LOG.warning("Supabase env not set (SUPABASE_URL / SUPABASE_KEY). Signed URLs will fail.")
if not ELEVEN_API_KEY:
    LOG.warning("ELEVENLABS_API_KEY not set. TTS will fail.")


# ──────────────────────────────────────────────────────────────────────────────
# Supabase client
# ──────────────────────────────────────────────────────────────────────────────
_supabase: Optional[Client] = None
def _sb() -> Client:
    global _supabase
    if _supabase is None:
        _supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _supabase


# ──────────────────────────────────────────────────────────────────────────────
# Text splitting (sentence-aware, size-capped)
# ──────────────────────────────────────────────────────────────────────────────
_SENT_SPLIT = re.compile(r'(?<=[.!?])\s+')

def split_text_for_tts(text: str, max_chars: int = CHUNK_MAX_CHARS) -> List[str]:
    """
    Split `text` into chunks <= max_chars, preferring sentence boundaries.
    Falls back to hard-wrap if a single sentence exceeds max_chars.
    """
    text = (text or "").strip()
    if not text:
        return []

    sents = [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]
    out: List[str] = []
    buf = ""

    def flush():
        nonlocal buf
        if buf:
            out.append(buf.strip())
            buf = ""

    for s in sents:
        if len(s) > max_chars:
            # Split a long sentence hard
            if buf: flush()
            start = 0
            while start < len(s):
                out.append(s[start:start+max_chars].strip())
                start += max_chars
            continue

        if not buf:
            buf = s
        elif len(buf) + 1 + len(s) <= max_chars:
            buf += " " + s
        else:
            flush()
            buf = s

    flush()
    return out


# ──────────────────────────────────────────────────────────────────────────────
# ElevenLabs TTS
# ──────────────────────────────────────────────────────────────────────────────
def elevenlabs_tts_to_bytes(
    text: str,
    voice_id: Optional[str] = None,
    model_id: Optional[str] = None,
    output_format: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> bytes:
    """
    Synthesize speech via ElevenLabs REST API and return MP3 bytes.
    Uses low bitrate by default (mp3_32) for ultra-fast fetch.
    Retries transient failures.
    """
    if not ELEVEN_API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY missing")

    voice_id = voice_id or ELEVEN_VOICE_ID_DEFAULT
    model_id = model_id or ELEVEN_MODEL_ID
    output_format = output_format or ELEVEN_OUTPUT_FORMAT

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": ELEVEN_API_KEY,
        "Accept": "audio/mpeg",
        "Content-Type": "application/json",
    }

    body: Dict[str, Any] = {
        "text": text,
        "model_id": model_id,
        # Voice settings are optional; keep them conservative to reduce artifacts
        "voice_settings": {
            "stability": 0.5,
            "similarity_boost": 0.8,
            "style": 0.0,
            "use_speaker_boost": True,
        },
        # Keep files small to avoid 413s and speed up Twilio fetches
        "output_format": output_format,  # e.g., "mp3_32"
    }
    if extra:
        body.update(extra)

    last_err = None
    for attempt in range(1, HTTP_RETRIES + 1):
        try:
            resp = requests.post(url, headers=headers, data=json.dumps(body), timeout=HTTP_TIMEOUT)
            # 200 with MP3 bytes expected; otherwise raise
            if resp.status_code == 200 and resp.content and resp.headers.get("Content-Type", "").startswith("audio/"):
                return resp.content
            # Some errors come with JSON
            try:
                detail = resp.json()
            except Exception:
                detail = resp.text[:300]
            raise RuntimeError(f"ElevenLabs TTS HTTP {resp.status_code}: {detail}")
        except Exception as e:
            last_err = e
            if attempt < HTTP_RETRIES:
                backoff = RETRY_BACKOFF * attempt
                LOG.warning("ElevenLabs TTS attempt %d/%d failed (%s). Retrying in %.1fs",
                            attempt, HTTP_RETRIES, e, backoff)
                time.sleep(backoff)
            else:
                break
    raise RuntimeError(f"ElevenLabs TTS failed after {HTTP_RETRIES} attempts: {last_err}")


def elevenlabs_tts_to_file(
    text: str,
    out_path: str,
    voice_id: Optional[str] = None,
    model_id: Optional[str] = None,
    output_format: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> str:
    """Write MP3 to `out_path` and return the path."""
    audio = elevenlabs_tts_to_bytes(text, voice_id, model_id, output_format, extra)
    with open(out_path, "wb") as f:
        f.write(audio)
    try:
        size = os.path.getsize(out_path)
        LOG.info("[TTS] wrote %s bytes → %s", size, out_path)
    except Exception:
        LOG.info("[TTS] wrote file → %s", out_path)
    return out_path


# ──────────────────────────────────────────────────────────────────────────────
# Supabase upload + signed URL
# ──────────────────────────────────────────────────────────────────────────────
def upload_audio_to_supabase(file_path: str, call_sid: str) -> str:
    """
    Upload local MP3 to Supabase Storage and return a signed CDN URL.
    Requires SUPABASE_URL + SUPABASE_KEY (service role).
    """
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("Supabase env missing (SUPABASE_URL, SUPABASE_KEY)")

    filename = f"{int(time.time())}_{uuid.uuid4().hex}.mp3"
    storage_path = f"calls/{call_sid or 'no_sid'}/{filename}"

    with open(file_path, "rb") as f:
        res = _sb().storage.from_(SUPABASE_BUCKET).upload(
            storage_path,
            f,
            {"content-type": "audio/mpeg", "upsert": True},
        )

    # supabase-py returns a dict on error or None on success; normalize both
    if isinstance(res, dict) and res.get("error"):
        raise RuntimeError(f"Supabase upload error: {res['error']}")

    signed = _sb().storage.from_(SUPABASE_BUCKET).create_signed_url(storage_path, 3600)  # 1h
    url = signed.get("signedURL") or signed.get("signed_url")
    if not url:
        raise RuntimeError(f"Supabase signed URL missing for {storage_path}")
    LOG.info("[CDN] %s", url)
    return url


# ──────────────────────────────────────────────────────────────────────────────
# Public API: text → chunked MP3s → signed URLs
# ──────────────────────────────────────────────────────────────────────────────
def tts_chunks_to_signed_urls(
    text: str,
    call_sid: str,
    voice_id: Optional[str] = None,
    max_chars: int = CHUNK_MAX_CHARS,
) -> List[str]:
    """
    Split `text` into small chunks, synth each to MP3 with ElevenLabs,
    upload to Supabase, and return a list of signed URLs (in order).

    Designed to keep each file tiny so Twilio <Play> fetches are instant and
    you never hit Storage 413 limits.
    """
    text = (text or "").strip()
    if not text:
        return []

    chunks = split_text_for_tts(text, max_chars=max_chars)
    urls: List[str] = []

    for idx, chunk in enumerate(chunks, 1):
        # Use NamedTemporaryFile(delete=False) so we can reopen on Windows/containers
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            LOG.info("[TTS] chunk %d/%d (len=%d chars)", idx, len(chunks), len(chunk))
            elevenlabs_tts_to_file(
                chunk,
                tmp_path,
                voice_id=voice_id or ELEVEN_VOICE_ID_DEFAULT,
                model_id=ELEVEN_MODEL_ID,
                output_format=ELEVEN_OUTPUT_FORMAT,
            )
            url = upload_audio_to_supabase(tmp_path, call_sid)
            urls.append(url)
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    return urls


# ──────────────────────────────────────────────────────────────────────────────
# Quick self-test (optional)
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    demo = (
        "Great to meet you. We deploy smart vending machines with zero upfront cost. "
        "If you’re the right contact, I can book a five-minute demo to show the numbers."
    )
    sid = "CA_demo"
    try:
        out_urls = tts_chunks_to_signed_urls(demo, sid)
        print(json.dumps({"count": len(out_urls), "urls": out_urls}, indent=2))
    except Exception as e:
        LOG.exception("Self-test failed: %s", e)
        raise
