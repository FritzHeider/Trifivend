# agent/ws_voice_agent.py
# ──────────────────────────────────────────────────────────────────────────────
# Production-grade voice agent WebSocket:
# - /voice/ws upgrades to WebSocket and streams turn-by-turn dialogue.
# - Client sends JSON frames: {"type":"user_text","text":"..."} (simple baseline)
# - Server replies with {"type":"bot_text","text":"..."} and {"type":"done"}.
# - TTS is optional: when enabled, writes /tmp/response.mp3 (served elsewhere).
# - Clean cancellation on disconnect; no orphan tasks.
# - Uses your existing coldcall_lead / speak_text implementations.
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.websockets import WebSocketState

# Lazy imports (don’t crash the module on boot)
try:
    from app.voicebot import coldcall_lead
except Exception as _e:
    coldcall_lead = None
    _lead_err = _e

try:
    from agent.speak import speak_text
except Exception as _e:
    speak_text = None
    _speak_err = _e

logger = logging.getLogger(__name__)
router = APIRouter(tags=["voice-agent"])

APP_BASE_URL = (os.getenv("APP_BASE_URL") or "https://ai-callbot.fly.dev").rstrip("/")
ENABLE_TTS = (os.getenv("WS_TTS", "false").lower() in {"1", "true", "yes"})
TTS_OUTPUT = os.getenv("WS_TTS_OUTPUT", "/tmp/response.mp3")

class _Conn:
    def __init__(self, ws: WebSocket, session_id: str):
        self.ws = ws
        self.session_id = session_id
        self.alive = True
        self._send_lock = asyncio.Lock()

    async def send_json(self, payload: dict):
        if self.ws.application_state != WebSocketState.CONNECTED:
            return
        async with self._send_lock:
            await self.ws.send_text(json.dumps(payload))

    async def close(self, code: int = 1000, reason: str = "bye"):
        self.alive = False
        if self.ws.application_state == WebSocketState.CONNECTED:
            await self.ws.close(code=code, reason=reason)

async def _bot_turn(user_text: str) -> str:
    if coldcall_lead is None:
        raise RuntimeError(f"voicebot not available: {getattr(_lead_err, 'args', ['unknown'])[0]}")
    # coldcall_lead is synchronous in many setups; run in thread to avoid blocking
    return await asyncio.to_thread(coldcall_lead, [{"role": "user", "content": user_text}])

async def _maybe_tts(text: str) -> Optional[str]:
    if not ENABLE_TTS:
        return None
    if speak_text is None:
        raise RuntimeError(f"speech not available: {getattr(_speak_err, 'args', ['unknown'])[0]}")
    # run blocking TTS in a thread; return path for client to /Play or fetch
    path = await asyncio.to_thread(speak_text, text, TTS_OUTPUT)
    return path

@router.websocket("/voice/ws")
async def voice_ws(ws: WebSocket):
    """Minimal, robust WebSocket voice/chat loop."""
    # Handshake
    await ws.accept()
    session_id = os.urandom(6).hex()
    conn = _Conn(ws, session_id)
    logger.info("ws[%s] connected", session_id)

    consumer_task = None
    try:
        async def consumer() -> None:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except Exception:
                    await conn.send_json({"type": "error", "detail": "invalid json"})
                    continue

                mtype = msg.get("type")
                if mtype == "ping":
                    await conn.send_json({"type": "pong"})
                    continue

                if mtype == "user_text":
                    user_text = (msg.get("text") or "").strip()
                    if not user_text:
                        await conn.send_json({"type": "error", "detail": "empty text"})
                        continue

                    try:
                        bot_reply = await _bot_turn(user_text)
                    except Exception as e:
                        logger.exception("ws[%s] bot turn failed", session_id)
                        await conn.send_json({"type": "error", "detail": f"bot_error: {e}"})
                        continue

                    await conn.send_json({"type": "bot_text", "text": bot_reply})

                    try:
                        path = await _maybe_tts(bot_reply)
                        if path:
                            # The path is served elsewhere; we only notify the client
                            await conn.send_json({
                                "type": "bot_audio",
                                "url": f"{APP_BASE_URL}/twilio/audio/response.mp3"
                            })
                    except Exception as e:
                        logger.warning("ws[%s] tts failed: %s", session_id, e)

                    await conn.send_json({"type": "done"})
                    continue

                await conn.send_json({"type": "error", "detail": f"unknown type: {mtype}"})

        consumer_task = asyncio.create_task(consumer())

        # Keep-alive pings
        while conn.alive and consumer_task and not consumer_task.done():
            try:
                await asyncio.wait_for(consumer_task, timeout=20.0)
            except asyncio.TimeoutError:
                # Send periodic server-side ping; client should pong or ignore
                await conn.send_json({"type": "ping"})
                continue

    except WebSocketDisconnect:
        logger.info("ws[%s] disconnected", session_id)
    except Exception:
        logger.exception("ws[%s] fatal error", session_id)
    finally:
        if consumer_task and not consumer_task.done():
            consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await consumer_task
        await conn.close()
        logger.info("ws[%s] closed", session_id)
