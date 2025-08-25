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

# ---------------------------
# Conversation history
# ---------------------------
if "history" not in st.session_state:
    st.session_state.history = []

for item in st.session_state.history:
    st.chat_message("user", item["user"])
    st.chat_message("assistant", item["bot"])

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

# ---------------------------
# Text/Audio input -> /transcribe
# ---------------------------
text_input = st.text_input("Enter text message", key="txt_input")
uploaded_audio = st.file_uploader("Upload audio file", type=["wav", "mp3", "m4a"], key="upl_audio")

try:
    recorded_audio = st.audio_input("Record from microphone", key="mic_audio")
except Exception:
    recorded_audio = None

if st.button("Send", key="send_btn"):
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
        resp = requests.post(f"{API_BASE}/transcribe", files=files, timeout=60)
        resp.raise_for_status()
    except Exception as exc:
        st.error(f"Failed to contact backend: {exc}")
    else:
        data = resp.json()
        st.write("**Transcription:**", data.get("transcription", ""))
        st.write("**Response:**", data.get("response", ""))

        audio_url = data.get("audio_url")
        if audio_url:
            try:
                audio_resp = requests.get(f"{API_BASE}{audio_url}", timeout=60)
                if audio_resp.ok:
                    st.audio(audio_resp.content, format="audio/mp3")
            except Exception as exc:
                st.warning(f"Could not retrieve audio: {exc}")

        st.session_state.history.append(
            {
                "timestamp": datetime.now().strftime("%H:%M:%S"),
                "user": data.get("transcription", text_input or "[no input]"),
                "bot": data.get("response", ""),
            }
        )

# ---------------------------
# SSE stream from /mcp/sse
# ---------------------------
st.subheader("Stream from /mcp/sse")

lead_name = st.text_input("Lead name", "Alex", key="lead_name")
lead_phone = st.text_input("Phone number", "123-456-7890", key="lead_phone_for_sse")
property_type = st.text_input("Property type", "apartment", key="property_type")
location_area = st.text_input("Location area", "NYC", key="location_area")
callback_offer = st.text_input("Callback offer", "schedule a demo", key="callback_offer")

# SSE state
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
                f"{API_BASE}/mcp/sse", params=params, stream=True, timeout=10
            ) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("Content-Length", 0))
                progress_bar = st.progress(0) if total else None
                bytes_received = len(collected.encode())

                for raw in resp.iter_lines():
                    # Allow user to stop mid-stream
                    if not st.session_state.do_sse:
                        break
                    if not raw:
                        continue
                    decoded = raw.decode("utf-8")
                    if decoded.startswith("data: "):
                        chunk = decoded.replace("data: ", "", 1)
                        if chunk == "[END]":
                            st.session_state.do_sse = False
                            break
                        collected += chunk
                        st.session_state.sse_collected = collected
                        message_placeholder.markdown(collected)
                        bytes_received += len(chunk)
                        if progress_bar and total:
                            progress_bar.progress(min(bytes_received / max(total, 1), 1.0))
                if progress_bar:
                    progress_bar.empty()
    except requests.exceptions.RequestException as exc:
        st.warning(f"SSE connection failed: {exc}")
        if st.button("Retry", key="retry_sse"):
            st.session_state.do_sse = True
        else:
            st.session_state.do_sse = False
    else:
        # if ended normally (or by [END]) persist to history
        if collected:
            st.session_state.history.append(
                {
                    "timestamp": datetime.now().strftime("%H:%M:%S"),
                    "user": "[SSE]",
                    "bot": collected,
                }
            )
    finally:
        # reset on exit if we’re no longer streaming
        if not st.session_state.do_sse:
            st.session_state.sse_collected = ""

cols = st.columns(3)
with cols[0]:
    if st.button("Start SSE Stream", key="start_sse"):
        st.session_state.sse_params = {
            "lead_name": lead_name,
            "phone": lead_phone,
            "property_type": property_type,
            "location_area": location_area,
            "callback_offer": callback_offer,
        }
        st.session_state.sse_collected = ""
        st.session_state.do_sse = True
with cols[1]:
    if st.button("Stop SSE", key="stop_sse"):
        st.session_state.do_sse = False
with cols[2]:
    st.caption("Use **Stop SSE** to interrupt a long stream.")

if st.session_state.do_sse:
    stream_sse()

# ---------------------------
# Twilio: call lead controls
# ---------------------------
st.subheader("Call Lead via Twilio")

if "call_sid" not in st.session_state:
    st.session_state.call_sid = None
if "call_status" not in st.session_state:
    st.session_state.call_status = None

twilio_lead_phone = st.text_input("Lead phone number (Twilio)", key="lead_phone_twilio")

if st.button("Call Lead", key="twilio_call"):
    if twilio_lead_phone:
        try:
            sid, status = initiate_call(twilio_lead_phone)
        except Exception as exc:
            st.error(f"Failed to initiate call: {exc}")
        else:
            st.session_state.call_sid = sid
            st.session_state.call_status = status
            st.success(f"Call started. SID: {sid}. Status: {status}")
    else:
        st.warning("Please enter a phone number")

if st.session_state.call_sid:
    try:
        current = get_call_status(st.session_state.call_sid)
        st.info(f"Current call SID: {st.session_state.call_sid}. Status: {current}")
    except Exception as exc:
        st.warning(f"Could not fetch call status: {exc}")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Cancel Call", key="cancel_call"):
            try:
                _, status = cancel_call(st.session_state.call_sid)
                st.session_state.call_status = status
                st.success(f"Call canceled. Status: {status}")
            except Exception as exc:
                st.error(f"Failed to cancel call: {exc}")
    with col2:
        if st.button("End Call", key="end_call"):
            try:
                _, status = end_call(st.session_state.call_sid)
                st.session_state.call_status = status
                st.success(f"Call ended. Status: {status}")
            except Exception as exc:
                st.error(f"Failed to end call: {exc}")
