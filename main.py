from fastapi import FastAPI, UploadFile, File, BackgroundTasks, Request, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.concurrency import run_in_threadpool
from agent.listen import transcribe_audio
from app.voicebot import coldcall_lead
from agent.speak import speak_text
from app.backend.supabase_logger import (
    ConversationLog,
    log_conversation,
    Lead,
    log_lead,
)
from dotenv import load_dotenv
import tempfile, shutil, os, asyncio
from openai import AsyncOpenAI

# === 🌎 Load Environment ===
load_dotenv()
openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4")

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
            user_input = await run_in_threadpool(transcribe_audio, audio_file.read(), 44100)

        # Get GPT response
        bot_reply = await run_in_threadpool(
            coldcall_lead, [{"role": "user", "content": user_input}]
        )

        # Background tasks
        async def speak_async(text: str) -> None:
            await run_in_threadpool(speak_text, text)

        async def log_async(entry: ConversationLog) -> None:
            await run_in_threadpool(log_conversation, entry)

        background_tasks.add_task(speak_async, bot_reply)
        background_tasks.add_task(
            log_async,
            ConversationLog(user_input=user_input, bot_reply=bot_reply),
        )

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
    phone: str,
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

    lead = Lead(
        name=lead_name,
        phone=phone,
        property_type=property_type,
        location_area=location_area,
        callback_offer=callback_offer,
    )

    await log_lead(lead)

    log_entry = ConversationLog(
        user_input=(
            f"SSE Request from {client_ip} | lead: {lead_name}, property: "
            f"{property_type}, area: {location_area}"
        ),
        bot_reply="[SSE stream initiated]",
    )
    background_tasks.add_task(log_conversation, log_entry)

    async def event_stream():
        yield "data: Connecting Ava...\n\n"

        queue: asyncio.Queue[str] = asyncio.Queue()
        stop_event = asyncio.Event()

        async def heartbeat() -> None:
            while not stop_event.is_set():
                await asyncio.sleep(25)
                if stop_event.is_set():
                    break
                await queue.put("data: [ping]\\n\\n")

        transcript: list[str] = []

        async def openai_stream() -> None:
            try:
                response = await openai_client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": prompt_filled},
                        {
                            "role": "user",
                            "content": f"Hi {lead_name}, this is Ava calling from Trifivend.",
                        },
                    ],
                    stream=True,
                )

                async for chunk in response:
                    if chunk.choices and len(chunk.choices) > 0:
                            delta = chunk.choices[0].delta.content
                            if delta:
                                transcript.append(delta)
                                await queue.put(f"data: {delta}\\n\\n")
            except Exception as e:
                await queue.put(f"data: [Error] {str(e)}\\n\\n")
            finally:
                stop_event.set()
                await queue.put("data: [END]\\n\\n")
                await log_conversation(
                    ConversationLog(
                        user_input=f"Lead {lead_name} conversation",
                        bot_reply="".join(transcript),
                    )
                )

        tasks = [asyncio.create_task(heartbeat()), asyncio.create_task(openai_stream())]

        try:
            while True:
                message = await queue.get()
                yield message
                if message == "data: [END]\\n\\n":
                    break
        finally:
            for t in tasks:
                t.cancel()

    return StreamingResponse(
        event_stream(), media_type="text/event-stream", background=background_tasks
    )
