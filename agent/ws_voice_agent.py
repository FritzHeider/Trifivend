import asyncio
import contextlib
import os
from fastapi import WebSocket

from app.voicebot import stream_coldcall_reply
from agent.speak import stream_text_to_speech

BACKCHANNEL_DELAY_MS = float(os.getenv("BACKCHANNEL_DELAY_MS", "300"))
BACKCHANNEL_TEXT = os.getenv("BACKCHANNEL_TEXT", "One sec…")


async def gpt_to_tts_stream(
    websocket: WebSocket, system_prompt: str, user_message: str
) -> None:
    await websocket.accept()

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_message})

    append = False
    first_chunk_event = asyncio.Event()

    async def _emit_backchannel() -> None:
        nonlocal append
        await asyncio.sleep(BACKCHANNEL_DELAY_MS / 1000.0)
        if first_chunk_event.is_set():
            return
        await websocket.send_text("…")
        wrote_audio = False
        async for chunk in stream_text_to_speech(
            BACKCHANNEL_TEXT,
            output_path="/tmp/ws-response.mp3",
            append=append,
        ):
            if first_chunk_event.is_set():
                break
            wrote_audio = True
            await websocket.send_bytes(chunk)
        if wrote_audio:
            append = True

    backchannel_task = asyncio.create_task(_emit_backchannel())

    try:
        async for chunk in stream_coldcall_reply(messages):
            text = chunk.strip()
            if not text:
                continue

            first_chunk_event.set()

            async for audio_chunk in stream_text_to_speech(
                text,
                output_path="/tmp/ws-response.mp3",
                append=append,
            ):
                append = True
                await websocket.send_bytes(audio_chunk)

            await websocket.send_text(text)

    except Exception as exc:
        await websocket.send_text(f"[ERROR] {exc}")
    finally:
        if not backchannel_task.done():
            backchannel_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await backchannel_task
        await websocket.close()
