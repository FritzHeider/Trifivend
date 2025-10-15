"""Minimal Twilio webhook handler used in tests and local dev."""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from importlib import import_module

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import PlainTextResponse, Response
from twilio.twiml.voice_response import VoiceResponse, Gather

logger = logging.getLogger("trifivend.twilio")
router = APIRouter()

APP_BASE_URL = os.getenv("APP_BASE_URL", "https://your-app.fly.dev").rstrip("/")
AUDIO_ENDPOINT = "/audio/response.mp3"


def _resolve_coldcall():
    try:
        module = import_module("app.voicebot")
        return getattr(module, "coldcall_lead", None)
    except Exception as exc:  # pragma: no cover
        logger.warning("voicebot unavailable in webhook: %s", exc)
        return None


def _resolve_speak():
    try:
        module = import_module("agent.speak")
        return getattr(module, "speak_text", None)
    except Exception as exc:  # pragma: no cover
        logger.warning("speak_text unavailable: %s", exc)
        return None


def speak_text(message: str) -> Optional[str]:
    synth = _resolve_speak()
    if synth is None:
        logger.warning("speak_text not configured; skipping synthesis")
        return None
    return synth(message)


@router.post("/twilio-voice")
async def twilio_voice(request: Request) -> Response:
    form = await request.form()
    speech = (form.get("SpeechResult") or "").strip()

    response = VoiceResponse()

    if not speech:
        gather = Gather(
            input="speech",
            speech_timeout=os.getenv("GATHER_SPEECH_TIMEOUT", "0.3"),
            action="/twilio-voice",
            method="POST",
        )
        gather.say(
            "Hello! This is Ava from Trifivend. Quick question for you.",
            language=os.getenv("TTS_LANG", "en-US"),
            voice=os.getenv("TTS_VOICE", "polly.Matthew"),
        )
        response.append(gather)
        response.say(
            "Sorry, I didn't catch that. Let's try again.",
            language=os.getenv("TTS_LANG", "en-US"),
            voice=os.getenv("TTS_VOICE", "polly.Matthew"),
        )
        response.redirect("/twilio-voice", method="POST")
        return PlainTextResponse(str(response), media_type="application/xml")

    coldcall = _resolve_coldcall()

    if coldcall is None:
        response.say("Our service is temporarily unavailable. Please try again later.")
        return PlainTextResponse(str(response), media_type="application/xml")

    try:
        reply = await asyncio.to_thread(coldcall, [{"role": "user", "content": speech}])
    except Exception as exc:  # pragma: no cover - network path
        logger.exception("voicebot failure: %s", exc)
        response.say("I hit a snag processing that. Could we try again?")
        return PlainTextResponse(str(response), media_type="application/xml")

    speak_text(reply)

    playback_url = f"{APP_BASE_URL}{AUDIO_ENDPOINT}"
    response.play(playback_url)
    gather = Gather(
        input="speech",
        speech_timeout=os.getenv("GATHER_SPEECH_TIMEOUT", "0.3"),
        action="/twilio-voice",
        method="POST",
    )
    response.append(gather)
    return PlainTextResponse(str(response), media_type="application/xml")


app = FastAPI()
app.include_router(router)
