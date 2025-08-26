# main.py
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import tempfile
from typing import Dict, Optional

from dotenv import load_dotenv
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
)
from pydantic import BaseModel, Field, validator
from sse_starlette.sse import EventSourceResponse
from twilio.rest import Client as TwilioClient

# ---- your modules ----------------------------------------------------------
from agent.listen import transcribe_audio
from app.voicebot import coldcall_lead
from agent.speak import speak_text
from app.backend.supabase_logger import ConversationLog, Lead, log_conversation, log_lead

# ----------------------------------------------------------------------------
# Env / Config
# ----------------------------------------------------------------------------
load_dotenv()

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

# Public base of THIS backend (Twilio needs absolute URLs)
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8080").rstrip("/")

# Twilio
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
TWILIO_NUMBER = os.getenv("TWILIO_NUMBER", "").strip()

def twilio_client() -> TwilioClient:
    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_NUMBER):
        raise HTTPException(
            status_code=500,
            detail="Twilio not configured. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_NUMBER.",
        )
    return TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# ----------------------------------------------------------------------------
# App + CORS
# ----------------------------------------------------------------------------
app = FastAPI(title="Trifivend Backend", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if ENVIRONMENT != "production" else [FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------------------------------------------------------------------
# Models / Validation
# ----------------------------------------------------------------------------
E164_RE = re.compile(r"^\+\d{8,15}$")
class CallRequest(BaseModel):
    # Accept both "to" (preferred) and legacy "phone"
    to: str = Field(..., alias="phone", description="E.164 number, e.g. +14155550123")
    lead_name: Optional[str] = None
    property_type: Optional[str] = None
    location_area: Optional[str] = None
    callback_offer: Optional[str] = None

    class Config:
        # This line makes Pydantic accept either "to" OR "phone" in the body
        allow_population_by_field_name = True
        allow_population_by_alias = True   # <--- add this

    @validator("to")
    def _valid_e164(cls, v: str) -> str:
        vv = v.strip()
        if not E164_RE.match(vv):
            raise ValueError("Invalid phone format. Use E.164 like +14155550123")
        return vv
# class CallRequest(BaseModel):
#     # Accept both "to" (preferred) and legacy "phone"
#     to: str = Field(..., alias="phone", description="E.164, e.g. +14155550123")
#     lead_name: str
#     property_type: str
#     location_area: str
#     callback_offer: str
# 
#     class Config:
#         allow_population_by_field_name = True  # lets clients send "to"
# 
#     @validator("to")
#     def _e164(cls, v: str) -> str:
#         v = v.strip()
#         if not E164_RE.match(v):
#             raise ValueError("Invalid phone format. Use E.164 like +14155550123.")
#         return v
# class CallRequest(BaseModel):
#     """
#     Body accepted by POST /call.
#     Accepts both "to" (preferred) and legacy "phone" as alias.
#     """
#     to: str = Field(..., alias="phone", description="E.164 number, e.g. +14155550123")
#     lead_name: Optional[str] = None
#     property_type: Optional[str] = None
#     location_area: Optional[str] = None
#     callback_offer: Optional[str] = None
# 
    class Config:
        allow_population_by_field_name = True  # allow clients to send "to"

    @validator("to")
    def _valid_e164(cls, v: str) -> str:
        vv = (v or "").strip()
        if not E164_RE.match(vv):
            raise ValueError("Invalid phone format. Use E.164 like +14155550123")
        return vv

class HealthOut(BaseModel):
    ok: bool
    twilio_configured: bool
    app_base_url: str

# ----------------------------------------------------------------------------
# Health
# ----------------------------------------------------------------------------
@app.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut(
        ok=True,
        twilio_configured=bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_NUMBER),
        app_base_url=APP_BASE_URL,
    )

# ----------------------------------------------------------------------------
# Transcribe -> reply -> speak -> log
# ----------------------------------------------------------------------------
@app.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    if not file.filename.lower().endswith((".wav", ".mp3", ".m4a")):
        raise HTTPException(status_code=400, detail="Unsupported audio format (.wav/.mp3/.m4a only)")

    with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        with open(tmp_path, "rb") as f:
            user_input = await run_in_threadpool(transcribe_audio, f.read(), 44100)

        bot_reply = await run_in_threadpool(
            coldcall_lead, [{"role": "user", "content": user_input}]
        )

        # schedule TTS + logging off the request thread
        background_tasks.add_task(run_in_threadpool, speak_text, bot_reply)
        background_tasks.add_task(
            run_in_threadpool,
            log_conversation,
            ConversationLog(user_input=user_input, bot_reply=bot_reply),
        )

        return {
            "transcription": user_input,
            "response": bot_reply,
            "audio_url": "/audio/response.mp3",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")
    finally:
        try:
            os.remove(tmp_path)
        except Exception:
            pass

@app.get("/audio/response.mp3")
async def serve_audio():
    path = "/tmp/response.mp3"
    if not os.path.exists(path):
        return JSONResponse({"error": "No audio available"}, status_code=404)
    return FileResponse(path, media_type="audio/mpeg")

# ----------------------------------------------------------------------------
# Outbound call (JSON body)  <<< THIS FIXES YOUR 422s
# ----------------------------------------------------------------------------
@app.post("/call")
async def call_lead(body: CallRequest, client: TwilioClient = Depends(twilio_client)):
    voice_url = f"{APP_BASE_URL}/twilio-voice"  # absolute URL for Twilio
    status_cb = f"{APP_BASE_URL}/status"

    try:
        call = await run_in_threadpool(
            client.calls.create,
            to=body.to,
            from_=TWILIO_NUMBER,
            url=voice_url,
            method="POST",
            status_callback=status_cb,
            status_callback_method="POST",
            status_callback_event=["initiated", "ringing", "answered", "completed"],
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Twilio error creating call: {e}")

    # best-effort lead logging (non-blocking)
    try:
        await run_in_threadpool(
            log_lead,
            Lead(
                name=body.lead_name or "",
                phone=body.to,
                property_type=body.property_type or "",
                location_area=body.location_area or "",
                callback_offer=body.callback_offer or "",
            ),
        )
    except Exception:
        pass

    # seed SSE stream
    await _enqueue(call.sid, {"event": "initiated", "sid": call.sid, "to": body.to})

    return {"call_sid": call.sid, "status": getattr(call, "status", "queued")}

# ----------------------------------------------------------------------------
# Twilio <Gather> voice webhook (absolute URLs)
# ----------------------------------------------------------------------------
@app.post("/twilio-voice")
async def twilio_voice(SpeechResult: str = Form(None)):
    if SpeechResult:
        reply = await run_in_threadpool(
            coldcall_lead, [{"role": "user", "content": SpeechResult}]
        )
        await run_in_threadpool(speak_text, reply)
        play_url = f"{APP_BASE_URL}/audio/response.mp3"
        twiml = f"""
<Response>
  <Play>{play_url}</Play>
  <Gather input="speech" action="{APP_BASE_URL}/twilio-voice" method="POST" timeout="5" speechTimeout="auto">
    <Say>...</Say>
  </Gather>
</Response>"""
    else:
        twiml = f"""
<Response>
  <Say>Hi, this is Ava from Trifivend. Are you the right person to speak with about smart vending solutions?</Say>
  <Gather input="speech" action="{APP_BASE_URL}/twilio-voice" method="POST" timeout="5" speechTimeout="auto">
    <Say>I'm listening...</Say>
  </Gather>
</Response>"""
    return Response(content=twiml.strip(), media_type="application/xml")

# ----------------------------------------------------------------------------
# Twilio status callback (form-encoded)
# ----------------------------------------------------------------------------
@app.post("/status")
async def status_webhook(request: Request):
    form = await request.form()
    sid = (form.get("CallSid") or "").strip()
    call_status = (form.get("CallStatus") or "").strip()

    if not sid:
        return PlainTextResponse("missing CallSid", status_code=200)

    await _enqueue(sid, {"event": "status", "sid": sid, "status": call_status})

    # non-blocking log
    try:
        await run_in_threadpool(
            log_conversation,
            ConversationLog(
                user_input=f"[Twilio status] {sid}",
                bot_reply=call_status or "(none)",
            ),
        )
    except Exception:
        pass

    if call_status in {"completed", "failed", "busy", "no-answer", "canceled"}:
        await _close_stream(sid)

    return PlainTextResponse("ok", status_code=200)

# ----------------------------------------------------------------------------
# Call management helpers
# ----------------------------------------------------------------------------
@app.get("/call/{sid}")
async def call_status(sid: str, client: TwilioClient = Depends(twilio_client)):
    call = await run_in_threadpool(client.calls(sid).fetch)
    return {"sid": call.sid, "status": call.status}

@app.post("/call/{sid}/cancel")
async def call_cancel(sid: str, client: TwilioClient = Depends(twilio_client)):
    call = await run_in_threadpool(client.calls(sid).update, status="canceled")
    return {"sid": call.sid, "status": call.status}

@app.post("/call/{sid}/end")
async def call_end(sid: str, client: TwilioClient = Depends(twilio_client)):
    call = await run_in_threadpool(client.calls(sid).update, status="completed")
    return {"sid": call.sid, "status": call.status}

# ----------------------------------------------------------------------------
# SSE (per-call) with heartbeat to survive proxies
# ----------------------------------------------------------------------------
_event_queues: Dict[str, asyncio.Queue[str]] = {}

async def _enqueue(sid: str, payload: dict) -> None:
    q = _event_queues.get(sid)
    if q is None:
        q = asyncio.Queue()
        _event_queues[sid] = q
    await q.put(json.dumps(payload))

async def _close_stream(sid: str) -> None:
    q = _event_queues.get(sid)
    if q:
        await q.put("[DONE]")

@app.get("/sse")
@app.get("/mcp/sse")
async def sse(sid: str):
    q = _event_queues.setdefault(sid, asyncio.Queue())

    async def gen():
        async def heartbeat():
            while True:
                await asyncio.sleep(20)
                yield {"event": "ping", "data": "{}"}

        hb = heartbeat()
        while True:
            msg_task = asyncio.create_task(q.get())
            hb_task = asyncio.create_task(hb.__anext__())
            done, _ = await asyncio.wait({msg_task, hb_task}, return_when=asyncio.FIRST_COMPLETED)

            if msg_task in done:
                msg = msg_task.result()
                if msg == "[DONE]":
                    yield {"event": "done", "data": "{}"}
                    break
                yield {"event": "message", "data": msg}
            else:
                yield hb_task.result()

    return EventSourceResponse(gen())

# ----------------------------------------------------------------------------
# Error shaping
# ----------------------------------------------------------------------------
@app.exception_handler(HTTPException)
async def http_exc_handler(_: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

@app.exception_handler(Exception)
async def unhandled_exc_handler(_: Request, exc: Exception):
    return JSONResponse(status_code=500, content={"detail": f"Internal error: {exc}"})

# ----------------------------------------------------------------------------
# Entrypoint (local dev)
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8080")), reload=False)