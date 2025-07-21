from fastapi import FastAPI, UploadFile, File, BackgroundTasks, Request, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from agent.listen import transcribe_audio
from app.voicebot import coldcall_lead
from agent.speak import speak_text
from app.backend.supabase_logger import log_conversation
from dotenv import load_dotenv
import tempfile, shutil, os, openai, asyncio

# Load environment
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

# Initialize app
app = FastAPI()

# CORS config
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Update this in prod
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === 🔊 Transcribe Endpoint ===
@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...), background_tasks: BackgroundTasks = BackgroundTasks()):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    with open(tmp_path, "rb") as audio_file:
        user_input = transcribe_audio(audio_file.read(), 44100)

    bot_reply = coldcall_lead([{"role": "user", "content": user_input}])

    background_tasks.add_task(speak_text, bot_reply)
    background_tasks.add_task(log_conversation, user_input, bot_reply)

    return {"transcription": user_input, "response": bot_reply}

# === 🔊 Serve MP3 Response ===
@app.get("/audio/response.mp3")
async def serve_audio():
    file_path = "/tmp/response.mp3"
    if not os.path.exists(file_path):
        return {"error": "No audio available"}
    return FileResponse(file_path, media_type="audio/mpeg")

# === 🔁 MCP SSE Endpoint for ElevenLabs ===
SYSTEM_PROMPT = """
You are a professional AI voice agent named Ava. You are calling on behalf of Trifivend to introduce a luxury AI vending machine solution to {{lead_name}}, a property manager of a {{property_type}} in {{location_area}}.

Use a confident, friendly, and concise tone throughout the call.

Your goals:
- Clearly communicate Trifivend’s value: premium, AI-powered vending machines that elevate property amenities.
- Emphasize zero cost and zero maintenance to the property manager.
- Overcome objections calmly and confidently.
- Offer the {{callback_offer}} as an incentive if the lead is uncertain or requests a follow-up.

Stay natural and conversational. The objective is to engage interest and move the lead toward a next step (callback, demo, or approval).
"""

@app.get("/mcp/sse")
async def stream_response(
    request: Request,
    lead_name: str,
    property_type: str,
    location_area: str,
    callback_offer: str,
    x_forwarded_for: str = Header(default="")
):
    prompt_filled = SYSTEM_PROMPT.replace("{{lead_name}}", lead_name)\
                                 .replace("{{property_type}}", property_type)\
                                 .replace("{{location_area}}", location_area)\
                                 .replace("{{callback_offer}}", callback_offer)

    client_ip = x_forwarded_for or request.client.host
    background_tasks = BackgroundTasks()
    background_tasks.add_task(
        log_conversation,
        f"SSE Request from {client_ip} | lead: {lead_name}, property: {property_type}, area: {location_area}",
        "[SSE stream initiated]"
    )

    async def event_stream():
        yield "data: Connecting Ava...\n\n"

        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": prompt_filled},
                {"role": "user", "content": f"Hi {lead_name}, this is Ava calling from Trifivend."}
            ],
            stream=True
        )

        for chunk in response:
            if "choices" in chunk and len(chunk["choices"]) > 0:
                delta = chunk["choices"][0]["delta"].get("content")
                if delta:
                    yield f"data: {delta}\n\n"
        yield "data: [END]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")