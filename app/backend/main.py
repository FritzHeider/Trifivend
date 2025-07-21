from fastapi import FastAPI, UploadFile, File, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from agent.listen import transcribe_audio
from app.voicebot import coldcall_lead
from agent.speak import speak_text
from app.backend.supabase_logger import log_conversation
import tempfile, shutil, os

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify your domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/transcribe")
async def transcribe(file: UploadFile = File(...), background_tasks: BackgroundTasks = BackgroundTasks()):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    with open(tmp_path, "rb") as audio_file:
        user_input = transcribe_audio(audio_file.read(), 44100)

    bot_reply = coldcall_lead([{"role": "user", "content": user_input}])

    # 🔥 Synthesize and log in the background
    background_tasks.add_task(speak_text, bot_reply)
    background_tasks.add_task(log_conversation, user_input, bot_reply)

    return {"transcription": user_input, "response": bot_reply}

@app.get("/audio/response.mp3")
async def serve_audio():
    file_path = "/tmp/response.mp3"
    if not os.path.exists(file_path):
        return {"error": "No audio available"}
    return FileResponse(file_path, media_type="audio/mpeg")