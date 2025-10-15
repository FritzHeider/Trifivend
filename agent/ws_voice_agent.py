# agent/ws_voice_agent.py
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()
logger = logging.getLogger("trifivend.ws")

@router.websocket("/ws/voice")
async def ws_voice(ws: WebSocket):
    await ws.accept()
    try:
        await ws.send_text(json.dumps({"event": "hello", "detail": "voice agent online"}))
        async for msg in ws.iter_text():
            # Echo server + simple reply
            await ws.send_text(json.dumps({"event": "message", "echo": msg}))
    except WebSocketDisconnect:
        logger.info("voice WS disconnected")
    finally:
        with contextlib.suppress(Exception):
            await ws.close()
