# main.py
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
import tempfile
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
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    PlainTextResponse,
    Response,
    StreamingResponse,
)
from pydantic import BaseModel, Field
from pydantic import AliasChoices, ConfigDict, field_validator  # Pydantic v2
from sse_starlette.sse import EventSourceResponse
from twilio.rest import Client as TwilioClient

# ──────────────────────────────────────────────────────────────────────────────
# App bootstrap & configuration
# ──────────────────────────────────────────────────────────────────────────────

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("trifivend.api")

ENVIRONMENT = os.getenv("ENVIRONMENT", "development").lower()
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

# Public base of THIS backend (Twilio + MCP require public HTTPS)
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8080").rstrip("/")

# Twilio config
TWILIO_ACCOUNT_SID = (os.getenv("TWILIO_ACCOUNT_SID") or "").strip()
TWILIO_AUTH_TOKEN = (os.getenv("TWILIO_AUTH_TOKEN") or "").strip()
# tolerate occasional typo TWILLO_NUMBER
TWILIO_NUMBER = (os.getenv("TWILLO_NUMBER") or os.getenv("TWILIO_NUMBER") or "").strip()

# Backchannel/latency tuning
BACKCHANNEL_DELAY_MS = float(os.getenv("BACKCHANNEL_DELAY_MS", "300"))
BACKCHANNEL_TEXT = os.getenv("BACKCHANNEL_TEXT", "One sec…")
CONTINUATION_SILENCE_SECONDS = float(os.getenv("CONTINUATION_SILENCE_SECONDS", "2.0"))
SYSTEM_PROMPT_TOKEN_LIMIT = int(os.getenv("SYSTEM_PROMPT_TOKEN_LIMIT", "300"))
GATHER_SPEECH_TIMEOUT = os.getenv("GATHER_SPEECH_TIMEOUT", "0.3")  # Twilio expects str/number

# Simple script registry (extend as needed)
SCRIPTS: Dict[str, Dict[str, str]] = {
    "default": {
        "opening_line": (
            "Hi, this is Ava from Trifivend. Are you the right person to speak with "
            "about smart vending solutions?"
        )
    }
}

# OpenAI helper (optional-safe)
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

openai_client = create_async_openai_client(api_key=os.getenv("OPENAI_API_KEY", ""))
if not is_openai_available():
    logger.warning(
        "OpenAI SDK unavailable; AI responses will error if invoked: %s",
        missing_openai_error(),
    )

# ──────────────────────────────────────────────────────────────────────────────
# External/local modules (lazy to avoid import-time crashes)
# ──────────────────────────────────────────────────────────────────────────────
try:
    from agent.listen import transcribe_audio
    from agent.speak import speak_text, stream_text_to_speech
    from app.voicebot import coldcall_lead, stream_coldcall_reply
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
    logger.warning("Deferred import of local modules due to: %s", e)
    transcribe_audio = None  # type: ignore
    speak_text = None  # type: ignore
    stream_text_to_speech = None  # type: ignore
    coldcall_lead = None  # type: ignore
    stream_coldcall_reply = None  # type: ignore
    ConversationLog = None  # type: ignore
    Lead = None  # type: ignore
    Call = None  # type: ignore
    CallEvent = None  # type: ignore
    log_conversation = None  # type: ignore
    log_lead = None  # type: ignore
    log_call = None  # type: ignore
    log_call_event = None  # type: ignore

# ──────────────────────────────────────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────────────────────────────────────
def _trim_system_prompt(prompt: str) -> str:
    if not prompt:
        return ""
    tokens = prompt.split()
    if len(tokens) <= SYSTEM_PROMPT_TOKEN_LIMIT:
        return prompt
    return " ".join(tokens[:SYSTEM_PROMPT_TOKEN_LIMIT])


def _require_local_module(name: str, obj: Any):
    if obj is None:
        raise RuntimeError(
            f"Module '{name}' is not available (deferred import failed). "
            "Check your image contents and requirements."
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
# FastAPI app & CORS
# ──────────────────────────────────────────────────────────────────────────────
app = FastAPI(title="Trifivend Backend", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if ENVIRONMENT != "production" else [FRONTEND_URL],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────────────────────────────────────
# MCP shared-secret guard (protect all /mcp/* routes)
# ──────────────────────────────────────────────────────────────────────────────
def _mcp_guard(secret: str = Header(None)) -> None:
    expected = os.getenv("MCP_SHARED_SECRET", "")
    if not expected:
        # if guard not configured, allow but warn
        logger.warning("MCP_SHARED_SECRET not set; /mcp/* endpoints are unprotected")
        return
    if secret != expected:
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
# Health
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut(
        ok=True,
        twilio_configured=bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_NUMBER),
        app_base_url=APP_BASE_URL,
    )

# ──────────────────────────────────────────────────────────────────────────────
# Audio transcription → reply → speech → log
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

        background_tasks.add_task(run_in_threadpool, speak_text, bot_reply)  # type: ignore[arg-type]
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
# Audio endpoints (stream + file)
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/audio/response.mp3")
async def serve_audio():
    path = "/tmp/response.mp3"
    if not os.path.exists(path):
        return JSONResponse({"error": "No audio available"}, status_code=404)
    return FileResponse(path, media_type="audio/mpeg")


@app.get("/audio/response-file")
async def response_file(sid: str):
    """Non-streaming per-call file so Twilio can always <Play> something."""
    path = os.path.join("/tmp", f"response-{sid}.mp3")
    if not os.path.exists(path):
        return JSONResponse({"error": "No audio available"}, status_code=404)
    return FileResponse(path, media_type="audio/mpeg")


@app.get("/audio/response-stream")
async def stream_audio_response(sid: str):
    queue = _audio_streams.get(sid)
    if queue is None:
        return JSONResponse({"error": "No active stream"}, status_code=404)

    async def iterator():
        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            yield chunk

    return StreamingResponse(iterator(), media_type="audio/mpeg")

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
        _schedule_background_coroutine(log_lead, lead, description="lead log", background_tasks=background_tasks)  # type: ignore[misc]

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

    # Persist call configuration
    _call_configs[call.sid] = {"script_id": body.script_id, "system_prompt": body.system_prompt, "turn": 0}
    await _enqueue(
        call.sid,
        {"event": "initiated", "sid": call.sid, "to": body.to, "script_id": body.script_id, "system_prompt": body.system_prompt},
    )

    return {"call_sid": call.sid, "status": getattr(call, "status", "queued")}

# ──────────────────────────────────────────────────────────────────────────────
# Twilio voice webhooks (<Gather> flow) with streaming + safe fallback
# ──────────────────────────────────────────────────────────────────────────────
@app.post("/twilio-voice")
async def twilio_voice(SpeechResult: str = Form(None), CallSid: str = Form("")):
    _require_local_module("app.voicebot.stream_coldcall_reply", stream_coldcall_reply)
    _require_local_module("agent.speak.stream_text_to_speech", stream_text_to_speech)
    _require_local_module("app.backend.supabase_logger.log_conversation", log_conversation)

    sid = (CallSid or "").strip()
    cfg = _call_configs.get(sid, {})
    script_id = cfg.get("script_id") or "default"
    system_prompt = cfg.get("system_prompt")
    opening_line = SCRIPTS.get(script_id, SCRIPTS["default"])["opening_line"]

    if SpeechResult:
        if not sid:
            raise HTTPException(status_code=400, detail="Missing CallSid for streaming response")

        _mark_user_activity(sid)
        await _stop_audio_stream(sid)

        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": _trim_system_prompt(system_prompt)})
        if script_id and script_id != "default":
            messages.append({"role": "system", "content": f"Use the {script_id} script."})
        messages.append({"role": "user", "content": SpeechResult})

        queue: asyncio.Queue[Optional[bytes]] = asyncio.Queue()
        _audio_streams[sid] = queue
        output_path = os.path.join("/tmp", f"response-{sid}.mp3")

        try:
            task = asyncio.create_task(
                _stream_reply_audio(
                    sid=sid,
                    queue=queue,
                    messages=messages,
                    user_input=SpeechResult,
                    script_id=script_id,
                    system_prompt=system_prompt,
                    output_path=output_path,
                )
            )
            _audio_stream_tasks[sid] = task

            # Preferred streaming <Play>
            play_url = f"{APP_BASE_URL}/audio/response-stream?sid={sid}"
            twiml = f"""
<Response>
  <Play>{play_url}</Play>
  <Gather input="speech" action="{APP_BASE_URL}/twilio-voice" method="POST" timeout="5" speechTimeout="{GATHER_SPEECH_TIMEOUT}" partialResultCallback="{APP_BASE_URL}/twilio-partial" partialResultCallbackMethod="POST">
    <Say>...</Say>
  </Gather>
</Response>"""

        except Exception as e:
            # Non-streaming fallback: Twilio still hears *our* audio, never its error line
            logger.exception("Streaming path failed; switching to file fallback: %s", e)
            try:
                await run_in_threadpool(speak_text, "Got it. One moment.")  # writes /tmp/response.mp3
            except Exception:
                pass
            file_url = f"{APP_BASE_URL}/audio/response-file?sid={sid}"
            twiml = f"""
<Response>
  <Play>{file_url}</Play>
  <Gather input="speech" action="{APP_BASE_URL}/twilio-voice" method="POST" timeout="5" speechTimeout="{GATHER_SPEECH_TIMEOUT}">
    <Say>Anything else?</Say>
  </Gather>
</Response>"""

    else:
        twiml = f"""
<Response>
  <Say>{opening_line}</Say>
  <Gather input="speech" action="{APP_BASE_URL}/twilio-voice" method="POST" timeout="5" speechTimeout="{GATHER_SPEECH_TIMEOUT}" partialResultCallback="{APP_BASE_URL}/twilio-partial" partialResultCallbackMethod="POST">
    <Say>I'm listening...</Say>
  </Gather>
</Response>"""

    return Response(content=twiml.strip(), media_type="application/xml")

@app.post("/twilio-partial")
async def twilio_partial(request: Request) -> Response:
    form = await request.form()
    sid = (form.get("CallSid") or "").strip()
    transcript = (
        form.get("UnstableSpeechResult") or form.get("SpeechResult") or ""
    ).strip()

    if not sid or not transcript:
        return PlainTextResponse("ok", status_code=200)

    _mark_user_activity(sid)
    await _enqueue(sid, {"event": "partial", "sid": sid, "transcript": transcript})
    return PlainTextResponse("ok", status_code=200)

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

    if call_status in {"completed", "failed", "busy", "no-answer", "canceled"}:
        await _close_stream(sid)

    return PlainTextResponse("ok", status_code=200)

# ──────────────────────────────────────────────────────────────────────────────
# Call management helpers
# ──────────────────────────────────────────────────────────────────────────────
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

# ──────────────────────────────────────────────────────────────────────────────
# SSE (per-call) with heartbeat to ride through proxies
# ──────────────────────────────────────────────────────────────────────────────
_call_configs: Dict[str, Dict[str, Optional[str]]] = {}
_event_queues: Dict[str, asyncio.Queue[str]] = {}
_audio_streams: Dict[str, asyncio.Queue[Optional[bytes]]] = {}
_audio_stream_tasks: Dict[str, asyncio.Task] = {}
_user_activity_events: Dict[str, asyncio.Event] = {}

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
    _event_queues.pop(sid, None)
    _call_configs.pop(sid, None)
    _user_activity_events.pop(sid, None)
    await _stop_audio_stream(sid)

def _mark_user_activity(sid: str) -> None:
    event = _user_activity_events.get(sid)
    if event is not None:
        event.set()

def _prepare_for_next_user_activity(sid: str) -> asyncio.Event:
    event = asyncio.Event()
    _user_activity_events[sid] = event
    return event

async def _stop_audio_stream(sid: str) -> None:
    queue = _audio_streams.pop(sid, None)
    if queue is not None:
        await queue.put(None)
    task = _audio_stream_tasks.pop(sid, None)
    if task is not None:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

async def _stream_reply_audio(
    *,
    sid: str,
    queue: asyncio.Queue[Optional[bytes]],
    messages: list[dict[str, str]],
    user_input: str,
    script_id: str,
    system_prompt: Optional[str],
    output_path: str,
) -> None:
    _require_local_module("app.voicebot.stream_coldcall_reply", stream_coldcall_reply)
    _require_local_module("agent.speak.stream_text_to_speech", stream_text_to_speech)
    _require_local_module("app.backend.supabase_logger.log_conversation", log_conversation)

    append = False
    parts: list[str] = []
    first_chunk_event = asyncio.Event()
    write_lock = asyncio.Lock()

    call_state = _call_configs.setdefault(sid, {})
    turn = int(call_state.get("turn", 0)) + 1
    call_state["turn"] = turn
    is_first_turn = turn == 1

    async def _emit_backchannel() -> None:
        nonlocal append
        try:
            await asyncio.sleep(BACKCHANNEL_DELAY_MS / 1000.0)
            if first_chunk_event.is_set():
                return
            await _enqueue(sid, {"event": "backchannel", "sid": sid, "detail": BACKCHANNEL_TEXT})
            async with write_lock:
                wrote_audio = False
                async for audio_chunk in stream_text_to_speech(  # type: ignore[misc]
                    BACKCHANNEL_TEXT, output_path=output_path, append=append
                ):
                    if first_chunk_event.is_set():
                        break
                    wrote_audio = True
                    await queue.put(audio_chunk)
                if wrote_audio:
                    append = True
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Backchannel generation failed for %s", sid, exc_info=True)

    backchannel_task = asyncio.create_task(_emit_backchannel())

    try:
        async for chunk in stream_coldcall_reply(messages, is_first_turn=is_first_turn):  # type: ignore[misc]
            text = (chunk or "").strip()
            if not text:
                continue

            parts.append(text)
            first_chunk_event.set()

            async with write_lock:
                wrote_audio = False
                async for audio_chunk in stream_text_to_speech(  # type: ignore[misc]
                    text, output_path=output_path, append=append
                ):
                    wrote_audio = True
                    await queue.put(audio_chunk)
                if wrote_audio:
                    append = True

        final_text = " ".join(parts).strip()
        if final_text:
            await _enqueue(
                sid,
                {
                    "event": "reply",
                    "sid": sid,
                    "user": user_input,
                    "bot_reply": final_text,
                    "script_id": script_id,
                    "system_prompt": system_prompt,
                },
            )
            with contextlib.suppress(Exception):
                await log_conversation(  # type: ignore[misc]
                    ConversationLog(user_input=user_input, bot_reply=final_text)  # type: ignore[misc]
                )

        next_activity_event = _prepare_for_next_user_activity(sid)

        async def _stream_continuation() -> None:
            nonlocal append
            continuation_messages = list(messages) + [{"role": "assistant", "content": final_text}]
            continuation_parts: list[str] = []

            async for chunk in stream_coldcall_reply(  # type: ignore[misc]
                continuation_messages, is_first_turn=False
            ):
                if next_activity_event.is_set():
                    return
                text = (chunk or "").strip()
                if not text:
                    continue
                continuation_parts.append(text)
                async with write_lock:
                    wrote_audio = False
                    async for audio_chunk in stream_text_to_speech(  # type: ignore[misc]
                        text, output_path=output_path, append=append
                    ):
                        if next_activity_event.is_set():
                            break
                        wrote_audio = True
                        await queue.put(audio_chunk)
                    if wrote_audio:
                        append = True

            follow_up = " ".join(continuation_parts).strip()
            if follow_up and not next_activity_event.is_set():
                await _enqueue(sid, {"event": "continuation", "sid": sid, "bot_reply": follow_up})
                with contextlib.suppress(Exception):
                    await log_conversation(  # type: ignore[misc]
                        ConversationLog(user_input="[silence continuation]", bot_reply=follow_up)  # type: ignore[misc]
                    )

        if is_first_turn and final_text and CONTINUATION_SILENCE_SECONDS > 0:
            try:
                await asyncio.wait_for(next_activity_event.wait(), timeout=CONTINUATION_SILENCE_SECONDS)
            except asyncio.TimeoutError:
                await _stream_continuation()

    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await _enqueue(sid, {"event": "error", "sid": sid, "detail": f"Streaming pipeline failed: {exc}"})
    finally:
        if not backchannel_task.done():
            backchannel_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await backchannel_task

        await queue.put(None)
        if _audio_streams.get(sid) is queue:
            _audio_streams.pop(sid, None)
        current = asyncio.current_task()
        if current is not None and _audio_stream_tasks.get(sid) is current:
            _audio_stream_tasks.pop(sid, None)

# ──────────────────────────────────────────────────────────────────────────────
# MCP SSE (protected)
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/mcp/sse", dependencies=[Depends(_mcp_guard)])
@app.get("/sse")
async def sse(
    sid: Optional[str] = None,
    lead_name: Optional[str] = None,
    phone: Optional[str] = None,
    property_type: Optional[str] = None,
    location_area: Optional[str] = None,
    callback_offer: Optional[str] = None,
):
    # If we have a real call stream, bridge it out
    if sid:
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
# Error shaping
# ──────────────────────────────────────────────────────────────────────────────
@app.exception_handler(HTTPException)
async def http_exc_handler(_: Request, exc: HTTPException):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

@app.exception_handler(Exception)
async def unhandled_exc_handler(_: Request, exc: Exception):
    logger.exception("Unhandled error")
    return JSONResponse(status_code=500, content={"detail": f"Internal error: {exc}"})

# ──────────────────────────────────────────────────────────────────────────────
# Entrypoint (local dev)
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
        reload=False,
        log_level=os.getenv("LOG_LEVEL", "info"),
    )
