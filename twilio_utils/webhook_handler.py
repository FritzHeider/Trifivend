import os, traceback
from fastapi import FastAPI, Form
from fastapi.responses import Response
from fastapi.concurrency import run_in_threadpool
from agent.speak import speak_text

try:
    from app.voicebot import coldcall_lead
except ImportError:  # pragma: no cover
    from app.voicebot import coldcall_lead


def _resolve_app_base_url() -> str:
    default_base = "https://ai-callbot.fly.dev"
    raw = os.getenv("APP_BASE_URL", "").strip()
    return (raw or default_base).rstrip("/")

APP_BASE_URL = _resolve_app_base_url()
app = FastAPI()

def _twiml_say_gather(prompt_text: str) -> str:
    # Always use ABSOLUTE URLs for Twilio
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
    </Response>"""

@app.post("/twilio-voice")
async def twilio_voice(SpeechResult: str = Form(None)):
    try:
        print("☎️ Received:", SpeechResult)

        # First turn (no speech yet): open with greeting + gather
        if not SpeechResult:
            return Response(
                content=_twiml_say_gather(
                    "Hi, this is Ava from TriFiVend. Quick question about your vending machine setup. "
                    "Are you the right person to speak with?"
                ),
                media_type="application/xml",
            )

        # We got user speech — generate reply and synthesize audio
        # IMPORTANT: keep this wrapped so Twilio always gets TwiML even if things fail.
        gpt_reply = await run_in_threadpool(
            coldcall_lead, [{"role": "user", "content": SpeechResult}]
        )

        # Synthesize to a predictable path your app serves (e.g., /audio/response.mp3)
        await run_in_threadpool(speak_text, gpt_reply)

        play_url = f"{APP_BASE_URL}/audio/response.mp3"  # ensure this route serves 200 with audio/*
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
        </Response>"""
        return Response(content=twiml, media_type="application/xml")

    except Exception as e:
        # Never 500 back to Twilio — recover with a spoken apology and continue the flow.
        print("❌ ERROR in /twilio-voice:", e)
        traceback.print_exc()
        return Response(
            content=_twiml_say_gather(
                "Sorry, I hit a glitch. Can you say that one more time?"
            ),
            media_type="application/xml",
        )
