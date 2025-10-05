# twilio_utils/webhook_handler.py
# ──────────────────────────────────────────────────────────────────────────────
# Production-grade Twilio Voice webhook router (modular; mount into main app)
# - Absolute URLs via APP_BASE_URL (required by Twilio)
# - Never returns 500 to Twilio (graceful TwiML fallbacks)
# - Optional X-Twilio-Signature verification (disabled by default; enable for prod)
# - Audio served from a predictable path (/twilio/audio/response.mp3)
# - Minimal health endpoint for Fly probes (/twilio/health)
# - Safe imports & lazy execution to avoid container boot failures
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import traceback
from typing import Dict, Iterable, Tuple

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response

# Lazy/guarded imports of your app logic so this router never hard-crashes at import time
try:
    from agent.speak import speak_text  # expected to write to /tmp/response.mp3
except Exception as _e:
    speak_text = None  # type: ignore[assignment]
    _speak_err = _e

try:
    from app.voicebot import coldcall_lead  # your reply generator (sync)
except Exception as _e:
    coldcall_lead = None  # type: ignore[assignment]
    _lead_err = _e


# ──────────────────────────────────────────────────────────────────────────────
# Configuration helpers
# ──────────────────────────────────────────────────────────────────────────────

def _resolve_app_base_url() -> str:
    """
    Twilio requires absolute HTTPS URLs for webhooks and media.
    APP_BASE_URL should be set to your public backend URL, e.g. https://ai-callbot.fly.dev
    """
    default = "https://ai-callbot.fly.dev"
    raw = (os.getenv("APP_BASE_URL") or "").strip()
    return (raw or default).rstrip("/")


APP_BASE_URL = _resolve_app_base_url()
AUDIO_PATH = "/tmp/response.mp3"

# Set to True after you’ve confirmed TWILIO_AUTH_TOKEN is configured in your env.
ENABLE_TWILIO_SIG_CHECK = False
TWILIO_AUTH_TOKEN = (os.getenv("TWILIO_AUTH_TOKEN") or "").strip()


# ──────────────────────────────────────────────────────────────────────────────
# Twilio signature verification (optional)
# Docs: https://www.twilio.com/docs/usage/security#validating-requests
# ──────────────────────────────────────────────────────────────────────────────

def _canonicalize_form(form_items: Iterable[Tuple[str, str]]) -> str:
    """
    Twilio's spec: concatenate the full URL with the POST params ordered by key.
    Here we join name/value pairs with no separators as per spec.
    """
    # Sort by parameter name (byte-order)
    parts: list[str] = []
    for k, v in sorted(form_items, key=lambda kv: kv[0]):
        parts.append(f"{k}{v}")
    return "".join(parts)


def _verify_twilio_signature(req: Request, form_items: Iterable[Tuple[str, str]]) -> None:
    if not ENABLE_TWILIO_SIG_CHECK:
        return
    if not TWILIO_AUTH_TOKEN:
        raise HTTPException(500, "Twilio signature check enabled but TWILIO_AUTH_TOKEN is missing")

    # Build the signature base: URL + sorted params
    full_url = f"{APP_BASE_URL}{req.url.path}"
    base = (full_url + _canonicalize_form(form_items)).encode("utf-8")

    digest = hmac.new(TWILIO_AUTH_TOKEN.encode("utf-8"), msg=base, digestmod=hashlib.sha1).digest()
    expected = base64.b64encode(digest).decode("utf-8")
    provided = req.headers.get("X-Twilio-Signature", "")

    # Constant-time comparison
    if not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=403, detail="Forbidden (invalid Twilio signature)")


# ──────────────────────────────────────────────────────────────────────────────
# Router (mount under /twilio or at root; see usage in main.py at bottom)
# ──────────────────────────────────────────────────────────────────────────────
router = APIRouter(tags=["twilio"])

def _twiml_say_gather(prompt_text: str) -> str:
    """
    Common TwiML block: say something, then immediately gather speech and POST back here.
    We keep everything absolute to avoid any ambiguity on Twilio’s side.
    """
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
    """
    Lightweight, deterministic health check for this router.
    (Separate from the app’s global /health if you want module-level probes.)
    """
    return {"ok": True, "component": "twilio_webhook", "base": APP_BASE_URL}


@router.get("/twilio/audio/response.mp3")
def serve_audio_response():
    """
    Serve the last synthesized response (your speak_text implementation should write here).
    """
    if not os.path.exists(AUDIO_PATH):
        return JSONResponse({"error": "No audio available"}, status_code=404)
    # Twilio fetches with audio/mpeg
    return FileResponse(AUDIO_PATH, media_type="audio/mpeg")


@router.post("/twilio-voice")
async def twilio_voice(request: Request, SpeechResult: str = Form(None)):
    """
    The primary Twilio Voice webhook:
      - First turn (no SpeechResult): greet + <Gather>.
      - Subsequent turns: generate reply → synthesize → <Play> → <Gather>.
    This handler never returns 4xx/5xx to Twilio; on failure it emits a
    friendly TwiML apology and continues the conversation.
    """
    # 1) Optional: verify Twilio request authenticity
    try:
        # For signature we need full form items (not raw body) as per spec
        form = await request.form()
        form_items: Iterable[Tuple[str, str]] = [(k, str(v)) for k, v in form.items()]
        _verify_twilio_signature(request, form_items)
    except HTTPException:
        # Return a TwiML apology (don’t 403/500 Twilio)
        return Response(content=_twiml_say_gather("Sorry, I can't process that request."), media_type="application/xml")
    except Exception:
        # Any parsing hiccup: still respond with TwiML (don’t crash the call)
        traceback.print_exc()
        return Response(content=_twiml_say_gather("Sorry, I can't process that request."), media_type="application/xml")

    # 2) First turn: greet + gather (keeps TTFB tiny)
    if not SpeechResult:
        greeting = (
            "Hi, this is Ava from TriFiVend. Quick question about your vending machine setup. "
            "Are you the right person to speak with?"
        )
        return Response(content=_twiml_say_gather(greeting), media_type="application/xml")

    # 3) Subsequent turns: generate reply and synthesize audio
    try:
        if coldcall_lead is None:
            raise RuntimeError(f"voicebot loader failed: {getattr(_lead_err, 'args', ['unknown'])[0]}")

        reply_text = await run_in_threadpool(
            coldcall_lead, [{"role": "user", "content": SpeechResult}]
        )

        # Synthesize speech into a well-known path this router serves
        if speak_text is None:
            raise RuntimeError(f"speak_text loader failed: {getattr(_speak_err, 'args', ['unknown'])[0]}")

        await run_in_threadpool(speak_text, reply_text)

        # Build TwiML that <Play>s our synthesized file, then <Gather> again
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

    except Exception as e:
        # Never let exceptions bubble to Twilio: apologize and keep the flow alive.
        traceback.print_exc()
        return Response(
            content=_twiml_say_gather("Sorry, I hit a glitch. Can you say that one more time?"),
            media_type="application/xml",
        )
