# main.py
# ──────────────────────────────────────────────────────────────────────────────
# Trifivend FastAPI backend:
# - Twilio webhooks live in twilio_utils/webhook_handler.py (authoritative)
# - Optional WS voice agent in agent/ws_voice_agent.py
# - /call kicks off outbound calls (Twilio client)
# - /transcribe -> STT -> reply -> TTS (non-call path)
# - SSE for live dashboards
# - Health is shallow & deterministic
# Production notes:
#   • Run with: uvicorn main:app --host :: --port 8080
#   • Fly Machines internal_port must match 8080
#   • APP_BASE_URL must be public (Twilio)
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
import tempfile
from collections.abc import AsyncGenerator
from typing import Any, Awaitable, Callable, Dict, Optional

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
)
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator
from sse_starlette.sse import EventSourceResponse
from twilio.rest import Client as TwilioClient

# ──────────────────────────────────────────────────────────────────────────────
# Bootstrap & config
# ──────────────────────────────────────────────────────────────────────────────

load_dotenv()

LOG_LEVEL_NAME = (os.getenv("LOG_LEVEL") or "INFO").upper()
LOG_LEVEL = getattr(logging, LOG_LEVEL_NAME, logging.INFO)
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("trifivend.api")

ENVIRONMENT = (os.getenv("ENVIRONMENT") or "development").lower()
FRONTEND_URL = (os.getenv("FRONTEND_URL") or "http://localhost:3000").strip()
APP_BASE_URL = (os.getenv("APP_BASE_URL") or "https://ai-callbot.fly.dev").rstrip("/")  # Twilio needs public HTTPS

# Twilio config
TWILIO_ACCOUNT_SID = (os.getenv("TWILIO_ACCOUNT_SID") or "").strip()
TWILIO_AUTH_TOKEN = (os.getenv("TWILIO_AUTH_TOKEN") or "").strip()
TWILIO_NUMBER = (os.getenv("TWILIO_NUMBER") or os.getenv("TWILLO_NUMBER") or "").strip()  # tolerate typo

# Voice flow tuning
GATHER_SPEECH_TIMEOUT = os.getenv("GATHER_SPEECH_TIMEOUT", "0.3")
SYSTEM_PROMPT_TOKEN_LIMIT = int(os.getenv("SYSTEM_PROMPT_TOKEN_LIMIT", "300"))

# Optional OpenAI compatibility layer (lazy, never crash boot)
try:
    from app.openai_compat import (
        create_async_openai_client,
        is_openai_available,
        missing_openai_error,
    )
except Exception as e:  # pragma: no cover
    logger.warning("OpenAI compatibility layer not importable: %s", e)
    create_async_openai_client = lambda **_: None  # type: ignore
    is_openai_available = lambda: False  # type: ignore
    missing_openai_error = lambda: str(e)  # type: ignore

openai_client = create_async_openai_client(api_key=os.getenv("OPENAI_API_KEY", ""))  # may be None
if not is_openai_available():
    logger.warning("OpenAI SDK unavailable; AI responses will error if invoked: %s", missing_openai_error())

# ──────────────────────────────────────────────────────────────────────────────
# External/local modules (lazy to avoid import-time crashes)
# ──────────────────────────────────────────────────────────────────────────────
try:
    from agent.listen import transcribe_audio
    from agent.speak import speak_text
    from app.voicebot import coldcall_lead
    from app.backend.supabase_logger import (
        ConversationLog,
        Lead,
        Call,
        CallEvent,
        log_conversation,
        log_lead,
        log_call,
        log_call_event,
    )
except Exception as e:
    logger.warning("Deferred import of local modules: %s", e)
    transcribe_audio = None  # type: ignore
    speak_text = None  # type: ignore
    coldcall_lead = None  # type: ignore
    ConversationLog = None  # type: ignore
    Lead = None  # type: ignore
    Call = None  # type: ignore
    CallEvent = None  # type: ignore
    log_conversation = None  # type: ignore
    log_lead = None  # type: ignore
    log_call = None  # type: ignore
    log_call_event = None  # type: ignore

# Optional TTS chunker (signed URLs); safe if missing
try:
    from tts_chunker import tts_chunks_to_signed_urls  # returns List[str] of signed MP3 URLs
except Exception as e:
    tts_chunks_to_signed_urls = None  # type: ignore
    logger.warning("tts_chunker not importable: %s", e)

# ──────────────────────────────────────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────────────────────────────────────

def _trim_system_prompt(prompt: str) -> str:
    if not prompt:
        return ""
    tokens = prompt.split()
    return " ".join(tokens[:SYSTEM_PROMPT_TOKEN_LIMIT]) if len(tokens) > SYSTEM_PROMPT_TOKEN_LIMIT else prompt


def _require_local_module(name: str, obj: Any):
    if obj is None:
        raise HTTPException(
            status_code=500,
            detail=f"Module '{name}' is not available (deferred import failed). Check image contents and requirements.",
        )


def _schedule_background_coroutine(
    coro_func: Callable[..., Awaitable[Any]],
    *args: Any,
    description: str,
    background_tasks: BackgroundTasks | None = None,
    **kwargs: Any,
) -> None:
    async def runner() -> None:
        try:
            await coro_func(*args, **kwargs)
        except Exception:
            logger.exception("Background task '%s' failed", description)

    try:
        asyncio.create_task(runner())
    except RuntimeError:
        if background_tasks is not None:
            background_tasks.add_task(runner)  # type: ignore[arg-type]
        else:
            logger.error("Unable to schedule '%s': no running event loop", description)


def twilio_client() -> TwilioClient:
    if not (TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_NUMBER):
        raise HTTPException(
            status_code=500,
            detail="Twilio not configured. Set TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_NUMBER.",
        )
    return TwilioClient(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# ──────────────────────────────────────────────────────────────────────────────
# App & middleware
# ──────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="Trifivend Backend", version="1.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if ENVIRONMENT != "production" else [FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Twilio voice router (authoritative /twilio-voice lives there)
try:
    from twilio_utils.webhook_handler import router as twilio_router
    app.include_router(twilio_router)
    logger.info("Mounted Twilio webhook router")
except Exception as e:
    logger.warning("Twilio router not mounted: %s", e)

# WS voice agent router (optional)
try:
    from agent.ws_voice_agent import router as ws_router
    app.include_router(ws_router)
    logger.info("Mounted WS voice agent router")
except Exception as e:
    logger.warning("WS router not mounted: %s", e)

# ──────────────────────────────────────────────────────────────────────────────
# MCP shared-secret guard (protect /mcp/* routes)
# ──────────────────────────────────────────────────────────────────────────────

def _mcp_guard(mcp_secret: str = Header(None, alias="MCP-Secret")) -> None:
    expected = os.getenv("MCP_SHARED_SECRET", "")
    if not expected:
        logger.warning("MCP_SHARED_SECRET not set; /mcp/* endpoints are unprotected")
        return
    if mcp_secret != expected:
        raise HTTPException(status_code=403, detail="Forbidden")

# ──────────────────────────────────────────────────────────────────────────────
# Models (Pydantic v2)
# ──────────────────────────────────────────────────────────────────────────────

E164_RE = re.compile(r"^\+\d{8,15}$")


class CallRequest(BaseModel):
    """Body accepted by POST /call. Accepts both 'to' and legacy 'phone'."""
    to: str = Field(
        ...,
        validation_alias=AliasChoices("to", "phone"),
        serialization_alias="to",
        description="E.164, e.g. +14155550123",
    )
    lead_name: str
    property_type: str
    location_area: str
    callback_offer: str
    script_id: Optional[str] = None
    system_prompt: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True)

    @field_validator("to")
    @classmethod
    def _valid_e164(cls, v: str) -> str:
        vv = (v or "").strip()
        if not E164_RE.match(vv):
            raise ValueError("Invalid phone format. Use E.164 like +14155550123")
        return vv

    @field_validator("system_prompt")
    @classmethod
    def _limit_prompt(cls, v: Optional[str]) -> Optional[str]:
        return _trim_system_prompt(v) if v else v


class HealthOut(BaseModel):
    ok: bool
    twilio_configured: bool
    app_base_url: str

# ──────────────────────────────────────────────────────────────────────────────
# Health & root
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut(
        ok=True,
        twilio_configured=bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_NUMBER),
        app_base_url=APP_BASE_URL,
    )


@app.get("/")
def root():
    return {"service": "ai-callbot", "health": "/health", "docs": "/docs"}

# ──────────────────────────────────────────────────────────────────────────────
# Audio transcription → reply → speech → log (non-call path)
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/transcribe")
async def transcribe(
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    _require_local_module("agent.listen.transcribe_audio", transcribe_audio)
    _require_local_module("app.voicebot.coldcall_lead", coldcall_lead)
    _require_local_module("agent.speak.speak_text", speak_text)
    _require_local_module("app.backend.supabase_logger.log_conversation", log_conversation)

    filename = (file.filename or "").lower()
    if not filename.endswith((".wav", ".mp3", ".m4a")):
        raise HTTPException(status_code=400, detail="Unsupported audio format (.wav/.mp3/.m4a only)")

    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1] or ".wav") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name

    try:
        with open(tmp_path, "rb") as f:
            user_input = await run_in_threadpool(transcribe_audio, f.read(), 44100)  # type: ignore[misc]

        bot_reply = await run_in_threadpool(
            coldcall_lead, [{"role": "user", "content": user_input}]  # type: ignore[misc]
        )

        # Non-blocking TTS to /tmp/response.mp3 (legacy dev path)
        background_tasks.add_task(run_in_threadpool, speak_text, bot_reply)  # type: ignore[arg-type]

        # Log convo (best-effort)
        _schedule_background_coroutine(
            log_conversation,  # type: ignore[misc]
            ConversationLog(user_input=user_input, bot_reply=bot_reply),  # type: ignore[misc]
            description="conversation log",
            background_tasks=background_tasks,
        )

        return {"transcription": user_input, "response": bot_reply, "audio_url": "/audio/response.mp3"}
    except Exception as e:
        logger.exception("Transcription pipeline failed")
        raise HTTPException(status_code=500, detail=f"Transcription failed: {e}")
    finally:
        with contextlib.suppress(Exception):
            os.remove(tmp_path)

# ──────────────────────────────────────────────────────────────────────────────
# Audio endpoint (serves the last synthesized response)
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/audio/response.mp3")
async def serve_audio():
    path = "/tmp/response.mp3"
    if not os.path.exists(path):
        return JSONResponse({"error": "No audio available"}, status_code=404)
    return FileResponse(path, media_type="audio/mpeg")

# ──────────────────────────────────────────────────────────────────────────────
# Outbound call API
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/call")
async def call_lead(
    body: CallRequest,
    background_tasks: BackgroundTasks,
    client: TwilioClient = Depends(twilio_client),
):
    _require_local_module("app.backend.supabase_logger.log_lead", log_lead)
    _require_local_module("app.backend.supabase_logger.log_call", log_call)

    voice_url = f"{APP_BASE_URL}/twilio-voice"
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
        logger.exception("Twilio call create failed")
        raise HTTPException(status_code=502, detail=f"Twilio error creating call: {e}")

    # Best-effort lead logging
    try:
        lead = Lead(
            name=body.lead_name or "",
            phone=body.to,
            property_type=body.property_type or "",
            location_area=body.location_area or "",
            callback_offer=body.callback_offer or "",
        )
    except Exception:
        pass
    else:
        _schedule_background_coroutine(
            log_lead, lead, description="lead log", background_tasks=background_tasks  # type: ignore[misc]
        )

    # Log the call row immediately
    try:
        _schedule_background_coroutine(  # type: ignore[misc]
            log_call,
            Call(  # type: ignore[misc]
                lead_id=None,
                call_sid=call.sid,
                from_number=TWILIO_NUMBER,
                to_number=body.to,
                status=getattr(call, "status", "queued"),
            ),
            description="call log",
            background_tasks=background_tasks,
        )
    except Exception:
        pass

    # Persist call configuration for later turns
    _call_configs[call.sid] = {"script_id": body.script_id, "system_prompt": body.system_prompt, "turn": 0}
    await _enqueue(call.sid, {"event": "initiated", "sid": call.sid, "to": body.to})

    return {"call_sid": call.sid, "status": getattr(call, "status", "queued")}

# ──────────────────────────────────────────────────────────────────────────────
# Twilio status callback
# ──────────────────────────────────────────────────────────────────────────────

@app.post("/status")
async def status_webhook(request: Request, background_tasks: BackgroundTasks):
    _require_local_module("app.backend.supabase_logger.log_call_event", log_call_event)
    _require_local_module("app.backend.supabase_logger.log_conversation", log_conversation)

    form = await request.form()
    sid = (form.get("CallSid") or "").strip()
    call_status = (form.get("CallStatus") or "").strip()

    if not sid:
        return PlainTextResponse("missing CallSid", status_code=200)

    cfg = _call_configs.get(sid, {})
    await _enqueue(
        sid,
        {"event": "status", "sid": sid, "status": call_status, "script_id": cfg.get("script_id"), "system_prompt": cfg.get("system_prompt")},
    )

    # Log raw status + payload (non-blocking)
    try:
        payload = dict(form)
    except Exception:
        payload = {}
    _schedule_background_coroutine(
        log_call_event,  # type: ignore[misc]
        CallEvent(call_sid=sid, event=call_status or "(unknown)", payload=payload),  # type: ignore[misc]
        description="call event",
        background_tasks=background_tasks,
    )
    _schedule_background_coroutine(
        log_conversation,  # type: ignore[misc]
        ConversationLog(user_input="[status update]", bot_reply=call_status or "(unknown)", meta={"call_sid": sid, "payload": payload}),
        description="status log",
        background_tasks=background_tasks,
    )

    # If ended, clear volatile state
    if call_status in {"completed", "failed", "busy", "no-answer", "canceled"}:
        _event_queues.pop(sid, None)
        _call_configs.pop(sid, None)

    return PlainTextResponse("ok", status_code=200)

# ──────────────────────────────────────────────────────────────────────────────
# SSE (per-call) for dashboards
# ──────────────────────────────────────────────────────────────────────────────

_call_configs: Dict[str, Dict[str, Optional[str]]] = {}
_event_queues: Dict[str, asyncio.Queue[str]] = {}


async def _sse_event_stream(
    queue: asyncio.Queue[str],
    *,
    heartbeat_interval: float = 20.0,
) -> AsyncGenerator[Dict[str, str], None]:
    """
    Robust SSE generator:
      - emits {"event":"ping","data":"{}"} every heartbeat_interval
      - drains messages from the queue
      - emits {"event":"done"} when "[DONE]" is seen
      - cleans up any pending queue get on exit
    """
    queue_task: asyncio.Task[str] | None = None
    try:
        while True:
            if queue_task is None:
                queue_task = asyncio.create_task(queue.get())

            try:
                message = await asyncio.wait_for(asyncio.shield(queue_task), timeout=heartbeat_interval)
            except asyncio.TimeoutError:
                yield {"event": "ping", "data": "{}"}
                continue

            queue_task = None
            if message == "[DONE]":
                yield {"event": "done", "data": "{}"}
                break

            yield {"event": "message", "data": message}
    finally:
        if queue_task is not None:
            queue_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await queue_task


async def _enqueue(sid: str, payload: dict) -> None:
    q = _event_queues.get(sid)
    if q is None:
        q = asyncio.Queue()
        _event_queues[sid] = q
    await q.put(json.dumps(payload))


@app.get("/mcp/sse", dependencies=[Depends(_mcp_guard)])
@app.get("/sse")
async def sse(sid: Optional[str] = None):
    # If we have a real call stream, bridge it out
    if sid:
        q = _event_queues.setdefault(sid, asyncio.Queue())
        return EventSourceResponse(_sse_event_stream(q))

    # Otherwise, demo OpenAI streamed completion if available
    if openai_client:
        async def gen_openai():
            try:
                response = await openai_client.chat.completions.create(
                    model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                    messages=[{"role": "user", "content": "hello"}],
                    stream=True,
                )
                async for chunk in response:
                    delta = getattr(chunk.choices[0].delta, "content", None)
                    if delta:
                        yield {"event": "message", "data": delta}
            except Exception as e:
                yield {"event": "error", "data": json.dumps({"detail": str(e)})}

        return EventSourceResponse(gen_openai())

    return EventSourceResponse(lambda: ({"event": "done", "data": "{}"} for _ in []))

# ──────────────────────────────────────────────────────────────────────────────
# Error shaping & startup
# ──────────────────────────────────────────────────────────────────────────────

from fastapi.responses import JSONResponse as _JSONResponse  # alias to avoid confusion


@app.exception_handler(HTTPException)
async def http_exc_handler(_: Request, exc: HTTPException):
    return _JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.exception_handler(Exception)
async def unhandled_exc_handler(_: Request, exc: Exception):
    logger.exception("Unhandled error")
    return _JSONResponse(status_code=500, content={"detail": f"Internal error: {exc}"})


@app.on_event("startup")
async def _startup_log():
    # Light, non-blocking startup summary
    logger.info(
        "Startup: env=%s port=%s cors_origin=%s twilio_configured=%s openai_key=%s",
        ENVIRONMENT,
        os.getenv("PORT", "8080"),
        FRONTEND_URL if ENVIRONMENT == "production" else "*",
        bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_NUMBER),
        "yes" if os.getenv("OPENAI_API_KEY") else "no",
    )

# ──────────────────────────────────────────────────────────────────────────────
# Local dev entrypoint (match Fly: dual-stack)
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="::",  # dual-stack like production (Fly uses IPv6-first)
        port=int(os.getenv("PORT", "8080")),
        reload=False,
        log_level=os.getenv("LOG_LEVEL", "info"),
    )
