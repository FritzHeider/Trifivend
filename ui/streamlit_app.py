from datetime import datetime

import requests
import streamlit as st

from twilio.outbound_call import (
    cancel_call,
    end_call,
    get_call_status,
    initiate_call,
)

API_BASE = "http://localhost:8080"

st.set_page_config(page_title="Trifivend Chat")
st.title("Trifivend Streamlit Interface")

# Initialize conversation history
if "history" not in st.session_state:
    st.session_state.history = []

# Render conversation history on main page
for item in st.session_state.history:
    st.chat_message("user", item["user"])
    st.chat_message("assistant", item["bot"])

# Conversation controls
clear_col, download_col = st.columns(2)
with clear_col:
    if st.button("Clear History"):
        st.session_state.history = []
        st.experimental_rerun()
with download_col:
    transcript = "\n\n".join(
        f"{item['timestamp']}\nYou: {item['user']}\nAva: {item['bot']}"
        for item in st.session_state.history
    )
    st.download_button(
        "Download Transcript",
        transcript,
        file_name="transcript.txt",
        mime="text/plain",
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
lead_phone = st.text_input("Phone number", "123-456-7890", key="phone")
property_type = st.text_input("Property type", "apartment", key="ptype")
location_area = st.text_input("Location area", "NYC", key="loc")
callback_offer = st.text_input("Callback offer", "schedule a demo", key="offer")

if st.button("Start SSE Stream"):
    placeholder = st.empty()
    collected = ""
    params = {
        "lead_name": lead_name,
        "phone": lead_phone,
        "property_type": property_type,
        "location_area": location_area,
        "callback_offer": callback_offer,
    }
    try:
        with requests.get(
            f"{API_BASE}/mcp/sse", params=params, stream=True
        ) as resp:
            for line in resp.iter_lines():
                if line:
                    decoded = line.decode("utf-8")
                    if decoded.startswith("data: "):
                        chunk = decoded.replace("data: ", "")
                        if chunk == "[END]":
                            break
                        collected += chunk
                        placeholder.markdown(collected)
    except Exception as exc:
        st.error(f"SSE connection failed: {exc}")
    else:
        st.session_state.history.append(
            {
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "user": "[SSE]",
                "bot": collected,
            }
        )


st.subheader("Call Lead via Twilio")
if "call_sid" not in st.session_state:
    st.session_state.call_sid = None
if "call_status" not in st.session_state:
    st.session_state.call_status = None

lead_phone = st.text_input("Lead phone number", key="lead_phone")

if st.button("Call Lead"):
    if lead_phone:
        try:
            sid, status = initiate_call(lead_phone)
        except Exception as exc:
            st.error(f"Failed to initiate call: {exc}")
        else:
            st.session_state.call_sid = sid
            st.session_state.call_status = status
            st.success(f"Call started. SID: {sid}. Status: {status}")
    else:
        st.warning("Please enter a phone number")

if st.session_state.call_sid:
    current = get_call_status(st.session_state.call_sid)
    st.info(
        f"Current call SID: {st.session_state.call_sid}. Status: {current}"
    )
    col1, col2 = st.columns(2)
    if col1.button("Cancel Call"):
        try:
            _, status = cancel_call(st.session_state.call_sid)
            st.session_state.call_status = status
            st.success(f"Call canceled. Status: {status}")
        except Exception as exc:
            st.error(f"Failed to cancel call: {exc}")
    if col2.button("End Call"):
        try:
            _, status = end_call(st.session_state.call_sid)
            st.session_state.call_status = status
            st.success(f"Call ended. Status: {status}")
        except Exception as exc:
            st.error(f"Failed to end call: {exc}")
