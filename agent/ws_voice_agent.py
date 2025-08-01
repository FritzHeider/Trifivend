import os
import openai
import json
import httpx
from fastapi import WebSocket, WebSocketDisconnect

openai_model = os.getenv("OPENAI_MODEL", "gpt-4")

voice_id = os.getenv("ELEVEN_VOICE_ID", "Rachel")
eleven_key = os.getenv("ELEVEN_API_KEY")

async def gpt_to_tts_stream(websocket: WebSocket, system_prompt: str, user_message: str):
    await websocket.accept()
    buffer = ""

    async with httpx.AsyncClient(timeout=60.0) as client:
        async def stream_tts(text):
            tts_url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
            headers = {
                "xi-api-key": eleven_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg"
            }
            payload = {
                "text": text,
                "voice_settings": {"stability": 0.4, "similarity_boost": 0.7}
            }
            try:
                resp = await client.post(tts_url, headers=headers, json=payload)
                async for chunk in resp.aiter_bytes():
                    await websocket.send_bytes(chunk)
            except Exception as e:
                await websocket.send_text(f"[ERROR] TTS failed: {str(e)}")

    try:
        response = openai.ChatCompletion.create(
            model=openai_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message}
            ],
            stream=True
        )

        for chunk in response:
            delta = chunk["choices"][0].get("delta", {}).get("content")
            if delta:
                buffer += delta
                if "." in buffer or len(buffer) > 300:
                    sentence, buffer = buffer.strip(), ""
                    await stream_tts(sentence)

        if buffer:
            await stream_tts(buffer)

    except Exception as e:
        await websocket.send_text(f"[ERROR] GPT failed: {str(e)}")
    finally:
        await websocket.close()
