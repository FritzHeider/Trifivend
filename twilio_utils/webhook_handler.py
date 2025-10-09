# twilio_utils/webhook_handler.py
# ──────────────────────────────────────────────────────────────────────────────
# Twilio Voice webhook router (production-ready, modular).
# - All URLs are absolute (Twilio requires this).
# - Never returns 500 to Twilio (graceful TwiML on any failure).
# - Optional signature verification with X-Twilio-Signature:
#     set TWILIO_VERIFY_SIGNATURE=true and TWILIO_AUTH_TOKEN in env.
# - Audio served from a predictable path (/twilio/audio/response.mp3).
# - Minimal health endpoint (/twilio/health) for Fly probes.
# - Lazy imports so app boot never crashes due to optional deps.
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import traceback
from typing import Iterable, Tuple

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response

# Lazy/guarded imports (never crash the router at import time)
try:
    from agent.speak import speak_text  # expected to write to /tmp/response.mp3
except Exception as _e:
    speak_text = None  # type: ignore[assignment]
    _speak_err = _e

try:
    from app.voicebot import coldcall_lead  # reply generator (sync)
except Exception as _e:
    coldcall_lead = None  # type: ignore[assignment]
    _lead_err = _e

# ──────────────────────────────────────────────────────────────────────────────
# Configuration helpers
# ──────────────────────────────────────────────────────────────────────────────

def _resolve_app_base_url() -> str:
    """
    Twilio **must** call a publicly reachable HTTPS URL.
    APP_BASE_URL must therefore be your public backend (e.g., https://ai-callbot.fly.dev).
    """
    default = "https://ai-callbot.fly.dev"
    raw = (os.getenv("APP_BASE_URL") or "").strip()
    return (raw or default).rstrip("/")

APP_BASE_URL = _resolve_app_base_url()
AUDIO_PATH = "/tmp/response.mp3"

# Toggle signature verification with env:
#   TWILIO_VERIFY_SIGNATURE=true
VERIFY_TWILIO_SIG = (os.getenv("TWILIO_VERIFY_SIGNATURE") or "false").lower() in {"1", "true", "yes"}
TWILIO_AUTH_TOKEN = (os.getenv("TWILIO_AUTH_TOKEN") or "").strip()

# ──────────────────────────────────────────────────────────────────────────────
# Signature verification (optional)
# Docs: https://www.twilio.com/docs/usage/security#validating-requests
# ──────────────────────────────────────────────────────────────────────────────

def _canonicalize_form(form_items: Iterable[Tuple[str, str]]) -> str:
    """
    Twilio spec: concatenate the full URL with POST params sorted by key.
    Join as name+value (no separators).
    """
    parts: list[str] = []
    for k, v in sorted(form_items, key=lambda kv: kv[0]):
        parts.append(f"{k}{v}")
    return "".join(parts)

def _verify_twilio_signature(req: Request, form_items: Iterable[Tuple[str, str]]) -> None:
    if not VERIFY_TWILIO_SIG:
        return
    if not TWILIO_AUTH_TOKEN:
        raise HTTPException(500, "TWILIO_VERIFY_SIGNATURE=true but TWILIO_AUTH_TOKEN is missing")

    # Build the signature base: full public URL (must match Twilio console URL)
    full_url = f"{APP_BASE_URL}{req.url.path}"
    base = (full_url + _canonicalize_form(form_items)).encode("utf-8")
    digest = hmac.new(TWILIO_AUTH_TOKEN.encode("utf-8"), msg=base, digestmod=hashlib.sha1).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    provided = req.headers.get("X-Twilio-Signature", "")

    # Constant-time compare
    if not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=403, detail="Forbidden (invalid Twilio signature)")

# ──────────────────────────────────────────────────────────────────────────────
# Router
# ──────────────────────────────────────────────────────────────────────────────

router = APIRouter(tags=["twilio"])

def _twiml_say_gather(prompt_text: str) -> str:
    """Say something, then <Gather> speech, POSTing back to the same public URL."""
    action_url = f"{APP_BASE_URL}/twilio-voice"
    return f"""<Response>
  <Say>{prompt_text}</Say>
  <Gather input="speech"
          action="{action_url}"
          method="POST"
          timeout="5"
          speechTimeout="0.4"
          actionOnEmptyResult="true">
    <Say>...</Say>
  </Gather>
</Response>""".strip()

@router.get("/twilio/health")
def twilio_health():
    """Deterministic health check for this router."""
    return {"ok": True, "component": "twilio_webhook", "base": APP_BASE_URL}

@router.get("/twilio/audio/response.mp3")
def serve_audio_response():
    """Serve the last synthesized response (your speak_text writes here)."""
    if not os.path.exists(AUDIO_PATH):
        return JSONResponse({"error": "No audio available"}, status_code=404)
    return FileResponse(AUDIO_PATH, media_type="audio/mpeg")

@router.post("/twilio-voice")
async def twilio_voice(request: Request, SpeechResult: str = Form(None)):
    """
    Primary Twilio Voice webhook:
      • First turn (no SpeechResult): greet + <Gather>.
      • Later turns: generate reply → synthesize → <Play> → <Gather>.
    Never returns 4xx/5xx directly to Twilio on internal errors; always returns valid TwiML.
    """
    # 1) Optional request authenticity
    try:
        form = await request.form()
        form_items = [(k, str(v)) for k, v in form.items()]
        _verify_twilio_signature(request, form_items)
    except HTTPException:
        return Response(content=_twiml_say_gather("Sorry, I can't process that request."), media_type="application/xml")
    except Exception:
        traceback.print_exc()
        return Response(content=_twiml_say_gather("Sorry, I can't process that request."), media_type="application/xml")

    # 2) First turn: greet + gather
    if not SpeechResult:
        greeting = (
            "Hi, this is Ava from TriFiVend. Quick question about your vending machine setup. "
            "Are you the right person to speak with?"
        )
        return Response(content=_twiml_say_gather(greeting), media_type="application/xml")

    # 3) Subsequent turns: generate reply + synthesize
    try:
        if coldcall_lead is None:
            raise RuntimeError(f"voicebot loader failed: {getattr(_lead_err, 'args', ['unknown'])[0]}")

        reply_text = await run_in_threadpool(
            coldcall_lead, [{"role": "user", "content": SpeechResult}]
        )

        if speak_text is None:
            raise RuntimeError(f"speak_text loader failed: {getattr(_speak_err, 'args', ['unknown'])[0]}")

        await run_in_threadpool(speak_text, reply_text)

        play_url = f"{APP_BASE_URL}/twilio/audio/response.mp3"
        action_url = f"{APP_BASE_URL}/twilio-voice"
        twiml = f"""<Response>
  <Play>{play_url}</Play>
  <Gather input="speech"
          action="{action_url}"
          method="POST"
          timeout="5"
          speechTimeout="0.4"
          actionOnEmptyResult="true">
    <Say>...</Say>
  </Gather>
</Response>""".strip()
        return Response(content=twiml, media_type="application/xml")

    except Exception:
        traceback.print_exc()
        return Response(
            content=_twiml_say_gather("Sorry, I hit a glitch. Can you say that one more time?"),
            media_type="application/xml",
        )
