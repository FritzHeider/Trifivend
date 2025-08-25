import os
from fastapi import FastAPI, Form, Request
from fastapi.responses import Response
from fastapi.concurrency import run_in_threadpool
from agent.speak import speak_text
try:
    from agent.voicebot import coldcall_lead
except ImportError:  # pragma: no cover - fallback for production
    from app.voicebot import coldcall_lead

from app.backend.supabase_logger import fetch_lead_script

APP_BASE_URL = os.getenv("APP_BASE_URL", "https://your-app.fly.dev")

app = FastAPI()


DEFAULT_SCRIPT = (
    "Hi, this is Ava from Trifivend. I wanted to quickly ask about your vending machine setup."
    " Are you the right person to speak with?"
)
DEFAULT_PROMPT = "You are Ava, an AI agent for Trifivend."


@app.post("/twilio-voice")
async def twilio_voice(request: Request, SpeechResult: str = Form(None)):
    lead_name = request.query_params.get("lead_name", "lead")
    script = await fetch_lead_script(lead_name) or None

    call_script = script.call_script if script else DEFAULT_SCRIPT
    system_prompt = script.system_prompt if script else DEFAULT_PROMPT

    print("☎️ Received:", SpeechResult)

    if SpeechResult:
        gpt_reply = await run_in_threadpool(
            coldcall_lead,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": SpeechResult},
            ],
        )
        await run_in_threadpool(speak_text, gpt_reply)

        play_url = f"{APP_BASE_URL}/audio/response.mp3"
        twiml = f'''
            <Response>
                <Play>{play_url}</Play>
                <Gather input="speech" action="/twilio-voice?lead_name={lead_name}" method="POST" timeout="5" speechTimeout="auto">
                    <Say>...</Say>
                </Gather>
            </Response>
        '''
    else:
        twiml = f'''
            <Response>
                <Say>{call_script}</Say>
                <Gather input="speech" action="/twilio-voice?lead_name={lead_name}" method="POST" timeout="5" speechTimeout="auto">
                    <Say>I'm listening...</Say>
                </Gather>
            </Response>
        '''

    return Response(content=twiml.strip(), media_type="application/xml")
