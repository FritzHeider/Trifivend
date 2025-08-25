# ui/streamlit_app.py
import json
import time
import requests
import streamlit as st

# ---- Config ---------------------------------------------------------------
BACKEND_URL = st.secrets.get("BACKEND_URL", "http://localhost:8080")  # e.g., https://ai-vendbot.fly.dev

st.set_page_config(page_title="Trifivend Streamlit Interface", layout="wide")
st.title("Trifivend Streamlit Interface")

# ---- Session state --------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []  # [{role: "user"|"assistant"|"system", content: str}]
if "call_sid" not in st.session_state:
    st.session_state.call_sid = None

# ---- Helpers --------------------------------------------------------------
def add_msg(role: str, content: str):
    st.session_state.messages.append({"role": role, "content": content})

def render_history():
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.write(m["content"])

def start_call(lead_phone: str, lead_name: str, property_type: str, location_area: str, callback_offer: str):
    # hits FastAPI /call (server holds Twilio creds)
    resp = requests.post(
        f"{BACKEND_URL}/call",
        json={
            "to": lead_phone,
            "lead_name": lead_name,
            "property_type": property_type,
            "location_area": location_area,
            "callback_offer": callback_offer,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["call_sid"]

def stream_events(call_sid: str):
    # simple SSE reader without extra deps
    with requests.get(f"{BACKEND_URL}/sse", params={"sid": call_sid}, stream=True, timeout=300) as r:
        r.raise_for_status()
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line.startswith("data:"):
                data = line.split("data:", 1)[1].strip()
                if data == "{}":  # heartbeat
                    continue
                evt = json.loads(data)
                yield evt

# ---- UI: lead form --------------------------------------------------------
with st.form("lead_form", clear_on_submit=False):
    col1, col2 = st.columns(2)
    with col1:
        lead_name = st.text_input("Lead name", "Alex")
        property_type = st.text_input("Property type", "apartment")
        location_area = st.text_input("Location area", "San Francisco")
    with col2:
        lead_phone = st.text_input("Lead phone (E.164)", "+14155550123")
        callback_offer = st.text_input("Callback offer", "schedule a free design session")

    submitted = st.form_submit_button("Start Call")
    if submitted:
        try:
            add_msg("system", f"Dialing {lead_phone} ({lead_name})…")
            st.session_state.call_sid = start_call(
                lead_phone, lead_name, property_type, location_area, callback_offer
            )
            add_msg("system", f"Call SID: {st.session_state.call_sid}")
        except Exception as e:
            add_msg("assistant", f"❌ Failed to start call: {e}")

# ---- Chat history (fixed API usage) --------------------------------------
render_history()

# ---- Live event stream (optional button) ----------------------------------
if st.session_state.call_sid:
    if st.button("Follow Live Call Events"):
        placeholder = st.empty()
        try:
            for evt in stream_events(st.session_state.call_sid):
                status = evt.get("status") or evt.get("event")
                with placeholder.container():
                    with st.chat_message("assistant"):
                        st.write(f"📡 **Twilio** → `{status}`")
                if status in ("completed", "failed", "busy", "no-answer", "canceled"):
                    add_msg("assistant", f"✅ Call finished with status: **{status}**")
                    break
        except Exception as e:
            add_msg("assistant", f"❌ SSE stream error: {e}")

# ---- Freeform chat box (optional) ----------------------------------------
if prompt := st.chat_input("Type a note to log with this lead…"):
    add_msg("user", prompt)
    with st.chat_message("assistant"):
        st.write("Noted. (You can wire this to Supabase logging if desired.)")