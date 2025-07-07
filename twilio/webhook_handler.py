from fastapi import FastAPI, Request, Form
from fastapi.responses import Response
from backend.speak import speak_text
from agent.voicebot import coldcall_lead
import os

app = FastAPI()

@app.post("/twilio-voice")
async def twilio_voice(SpeechResult: str = Form(None)):
    print("☎️ Received:", SpeechResult)

    if SpeechResult:
        # Generate AI reply and synthesize voice
        gpt_reply = coldcall_lead([{"role": "user", "content": SpeechResult}])
        speak_text(gpt_reply)  # Saves to /tmp/response.mp3

        twiml = f'''
            <Response>
                <Play>https://your-app.fly.dev/audio/response.mp3</Play>
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