import os
from fastapi import FastAPI, Form
from fastapi.responses import Response
from fastapi.concurrency import run_in_threadpool
from agent.speak import speak_text
try:
    from agent.voicebot import coldcall_lead
except ImportError:  # pragma: no cover - fallback for production
    from app.voicebot import coldcall_lead

APP_BASE_URL = os.getenv("APP_BASE_URL", "https://your-app.fly.dev")

app = FastAPI()

@app.post("/twilio-voice")
async def twilio_voice(SpeechResult: str = Form(None)):
    print("☎️ Received:", SpeechResult)

    if SpeechResult:
        # Generate AI reply and synthesize voice without blocking the event loop
        gpt_reply = await run_in_threadpool(
            coldcall_lead, [{"role": "user", "content": SpeechResult}]
        )
        await run_in_threadpool(speak_text, gpt_reply)  # Saves to /tmp/response.mp3

        play_url = f"{APP_BASE_URL}/audio/response.mp3"
        twiml = f'''
            <Response>
                <Play>{play_url}</Play>
                <Gather input="speech" action="/twilio-voice" method="POST" timeout="5" speechTimeout="auto">
                    <Say>...</Say>
                </Gather>
            </Response>
        '''
    else:
        # Initial greeting or re-entry point
        twiml = '''
            <Response>
                <Say>Hi, this is Taylor from SmartVend. I wanted to quickly ask about your vending machine setup. Are you the right person to speak with?</Say>
                <Gather input="speech" action="/twilio-voice" method="POST" timeout="5" speechTimeout="auto">
                    <Say>I'm listening...</Say>
                </Gather>
            </Response>
        '''

    return Response(content=twiml.strip(), media_type="application/xml")
