# twilio_utils/webhook_handler.py
from __future__ import annotations

import os
import logging
from typing import Optional, List

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse, Response
from twilio.twiml.voice_response import VoiceResponse, Gather

logger = logging.getLogger("trifivend.twilio")
router = APIRouter()

# Lazy imports to avoid boot crashes if optional deps are missing
try:
    from app.voicebot import coldcall_lead
except Exception as e:
    coldcall_lead = None  # type: ignore
    logger.warning("voicebot unavailable in webhook: %s", e)

# Environment knobs
GATHER_SPEECH_TIMEOUT = float(os.getenv("GATHER_SPEECH_TIMEOUT", "0.3"))
LANG = os.getenv("TTS_LANG", "en-US")
VOICE = os.getenv("TTS_VOICE", "polly.Matthew")  # Twilio `<Say voice="">` options; ignored if using <Play>


@router.post("/twilio-voice")
async def twilio_voice(request: Request) -> Response:
    """
    Primary Twilio webhook.
    - First hit has no SpeechResult -> prompt user.
    - Subsequent hits include SpeechResult -> call LLM -> respond.
    """
    form = await request.form()
    speech: str = (form.get("SpeechResult") or "").strip()
    call_sid: str = (form.get("CallSid") or "").strip()

    resp = VoiceResponse()

    if not speech:
        # Initial prompt
        g = Gather(
            input="speech",
            speech_timeout=str(GATHER_SPEECH_TIMEOUT),
            action="/twilio-voice",  # POST back here
            method="POST",
        )
        g.say("Hello! This is Ava from TriFiVend. Quick question for you.", language=LANG, voice=VOICE)
        resp.append(g)
        # Fallback if no input
        resp.say("Sorry, I didn't catch that. Let's try again.", language=LANG, voice=VOICE)
        resp.redirect("/twilio-voice", method="POST")
        return PlainTextResponse(str(resp), media_type="application/xml")

    if coldcall_lead is None:
        resp.say("Our service is temporarily unavailable. Please try again later.", language=LANG, voice=VOICE)
        return PlainTextResponse(str(resp), media_type="application/xml")

    # Build minimal chat history; Twilio calls are terse
    try:
        reply: str = await request.app.state.loop.run_in_executor(  # type: ignore[attr-defined]
            None, lambda: coldcall_lead([{"role": "user", "content": speech}])
        )
    except Exception as e:
        logger.exception("voicebot failure: %s", e)
        resp.say("I hit a snag processing that. Could we try again?", language=LANG, voice=VOICE)
        return PlainTextResponse(str(resp), media_type="application/xml")

    # Say the reply and re-gather
    g = Gather(
        input="speech",
        speech_timeout=str(GATHER_SPEECH_TIMEOUT),
        action="/twilio-voice",
        method="POST",
    )
    g.say(reply, language=LANG, voice=VOICE)
    resp.append(g)
    return PlainTextResponse(str(resp), media_type="application/xml")
