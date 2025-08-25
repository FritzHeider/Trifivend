from datetime import datetime

import requests
import streamlit as st

API_BASE = "http://localhost:8080"

st.set_page_config(page_title="Trifivend Chat")
st.title("Trifivend Streamlit Interface")

# Initialize conversation history
if "history" not in st.session_state:
    st.session_state.history = []

# Sidebar history
st.sidebar.title("Conversation History")
for item in st.session_state.history:
    st.sidebar.markdown(
        f"**{item['timestamp']}**\n\nYou: {item['user']}\n\nAva: {item['bot']}\n---"
    )

# Input controls
text_input = st.text_input("Enter text message")
uploaded_audio = st.file_uploader(
    "Upload audio file", type=["wav", "mp3", "m4a"]
)
try:
    recorded_audio = st.audio_input("Record from microphone")
except Exception:
    recorded_audio = None

if st.button("Send"):
    if recorded_audio is not None:
        file_bytes = recorded_audio.getvalue()
        filename = "recorded.wav"
        mime = recorded_audio.type or "audio/wav"
    elif uploaded_audio is not None:
        file_bytes = uploaded_audio.read()
        filename = uploaded_audio.name
        mime = uploaded_audio.type or "audio/wav"
    elif text_input:
        file_bytes = text_input.encode("utf-8")
        filename = "input.txt"
        mime = "text/plain"
    else:
        st.warning("Please provide text or audio input")
        st.stop()

    files = {"file": (filename, file_bytes, mime)}
    try:
        resp = requests.post(f"{API_BASE}/transcribe", files=files)
        resp.raise_for_status()
    except Exception as exc:
        st.error(f"Failed to contact backend: {exc}")
    else:
        data = resp.json()
        st.write("**Transcription:**", data.get("transcription", ""))
        st.write("**Response:**", data.get("response", ""))
        audio_url = data.get("audio_url")
        if audio_url:
            audio_resp = requests.get(f"{API_BASE}{audio_url}")
            if audio_resp.ok:
                st.audio(audio_resp.content, format="audio/mp3")
        st.session_state.history.append(
            {
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "user": data.get("transcription", ""),
                "bot": data.get("response", ""),
            }
        )

st.subheader("Stream from /mcp/sse")
lead_name = st.text_input("Lead name", "Alex", key="lead")
property_type = st.text_input("Property type", "apartment", key="ptype")
location_area = st.text_input("Location area", "NYC", key="loc")
callback_offer = st.text_input("Callback offer", "schedule a demo", key="offer")

# Session state for streaming
if "do_sse" not in st.session_state:
    st.session_state.do_sse = False
if "sse_collected" not in st.session_state:
    st.session_state.sse_collected = ""
if "sse_params" not in st.session_state:
    st.session_state.sse_params = {}


def stream_sse():
    params = st.session_state.sse_params
    collected = st.session_state.sse_collected
    chat = st.chat_message("assistant")
    message_placeholder = chat.empty()
    if collected:
        message_placeholder.markdown(collected)
    try:
        with st.spinner("Connecting…"):
            with requests.get(
                f"{API_BASE}/mcp/sse", params=params, stream=True
            ) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                progress_bar = st.progress(0) if total else None
                bytes_received = len(collected.encode())
                for line in resp.iter_lines():
                    if line:
                        decoded = line.decode("utf-8")
                        if decoded.startswith("data: "):
                            chunk = decoded.replace("data: ", "")
                            if chunk == "[END]":
                                st.session_state.do_sse = False
                                break
                            collected += chunk
                            st.session_state.sse_collected = collected
                            message_placeholder.markdown(collected)
                            bytes_received += len(chunk)
                            if progress_bar and total:
                                progress_bar.progress(
                                    min(bytes_received / total, 1.0)
                                )
                if progress_bar:
                    progress_bar.empty()
    except requests.exceptions.RequestException as exc:
        st.warning(f"SSE connection failed: {exc}")
        if st.button("Retry"):
            st.session_state.do_sse = True
        else:
            st.session_state.do_sse = False
    else:
        st.session_state.history.append(
            {
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "user": "[SSE]",
                "bot": collected,
            }
        )
        st.session_state.sse_collected = ""
        st.session_state.do_sse = False


if st.button("Start SSE Stream"):
    st.session_state.sse_params = {
        "lead_name": lead_name,
        "property_type": property_type,
        "location_area": location_area,
        "callback_offer": callback_offer,
    }
    st.session_state.sse_collected = ""
    st.session_state.do_sse = True

if st.session_state.do_sse:
    stream_sse()
