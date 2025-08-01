from fastapi import FastAPI, UploadFile, File, BackgroundTasks, Request, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from agent.listen import transcribe_audio
from app.voicebot import coldcall_lead
from agent.speak import speak_text
from app.backend.supabase_logger import log_conversation
from dotenv import load_dotenv
import tempfile, shutil, os, openai, asyncio

# === 🌎 Load Environment ===
load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

# === 🚀 Initialize FastAPI App ===
app = FastAPI()

# === 🔐 CORS Configuration ===
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if ENVIRONMENT != "production" else [FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# === 🔊 Transcribe Endpoint ===
@app.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    # Validate audio file type
    if not file.filename.endswith((".wav", ".mp3", ".m4a")):
        raise HTTPException(status_code=400, detail="Unsupported audio format")

    # Save audio file temporarily
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        # Transcribe audio
        with open(tmp_path, "rb") as audio_file:
            user_input = transcribe_audio(audio_file.read(), 44100)

        # Get GPT response
        bot_reply = coldcall_lead([{"role": "user", "content": user_input}])

        # Background tasks
        background_tasks.add_task(speak_text, bot_reply)
        background_tasks.add_task(log_conversation, user_input, bot_reply)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {str(e)}")

    finally:
        os.remove(tmp_path)

    return {
        "transcription": user_input,
        "response": bot_reply,
        "audio_url": "/audio/response.mp3"
    }

# === 🔉 Serve Generated MP3 Audio ===
@app.get("/audio/response.mp3")
async def serve_audio():
    file_path = "/tmp/response.mp3"
    if not os.path.exists(file_path):
        return {"error": "No audio available"}
    return FileResponse(file_path, media_type="audio/mpeg")

# === 🔁 MCP SSE Endpoint for ElevenLabs GPT Call Script ===
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

        try:
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
                    delta = chunk["choices"][0].get("delta", {}).get("content")
                    if delta:
                        yield f"data: {delta}\n\n"
        except Exception as e:
            yield f"data: [Error] {str(e)}\n\n"

        yield "data: [END]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
