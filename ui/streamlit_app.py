# ui/streamlit_app.py
import json
import os
import time
import asyncio
import requests
import streamlit as st
from app.backend.supabase_logger import LeadScript, log_script, get_script

# ---- Config ---------------------------------------------------------------
BACKEND_URL = st.secrets.get("BACKEND_URL", "http://localhost:8080")  # e.g., https://ai-vendbot.fly.dev

st.set_page_config(page_title="Trifivend Streamlit Interface", layout="wide")
st.title("Trifivend Streamlit Interface")

# ---- Session state --------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []  # [{role: "user"|"assistant"|"system", content: str}]
if "call_sid" not in st.session_state:
    st.session_state.call_sid = None
 default_fields = {
    "lead_name": "Alex",
    "property_type": "apartment",
    "location_area": "San Francisco",
    "lead_phone": "+14155550123",
    "callback_offer": "schedule a free design session",
    "system_prompt": "",
}
for k, v in default_fields.items():
    st.session_state.setdefault(k, v)
if "scripts" not in st.session_state:
    st.session_state.scripts = []
if "loaded_phone" not in st.session_state:
    st.session_state.loaded_phone = None

# ---- Helpers --------------------------------------------------------------
def add_msg(role: str, content: str):
    st.session_state.messages.append({"role": role, "content": content})

def render_history():
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.write(m["content"])

def fetch_call_scripts():
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_ANON_KEY")
    if not supabase_url or not supabase_key:
        return []
    try:
        r = requests.get(
            f"{supabase_url}/rest/v1/call_scripts",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
            },
            params={"select": "id,name"},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"Supabase script fetch error: {e}")
        return []


def fetch_lead_by_phone(phone: str):
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_ANON_KEY")
    if not supabase_url or not supabase_key:
        return None
    try:
        r = requests.get(
            f"{supabase_url}/rest/v1/leads",
            headers={
                "apikey": supabase_key,
                "Authorization": f"Bearer {supabase_key}",
            },
            params={
                "select": "name,property_type,location_area,callback_offer",
                "phone": f"eq.{phone}",
            },
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        return data[0] if data else None
    except Exception as e:
        print(f"Supabase lead fetch error: {e}")
        return None


def lookup_lead():
    lead = fetch_lead_by_phone(st.session_state.lead_phone)
    if lead:
        st.session_state.lead_name = lead.get("name", st.session_state.lead_name)
        st.session_state.property_type = lead.get(
            "property_type", st.session_state.property_type
        )
        st.session_state.location_area = lead.get(
            "location_area", st.session_state.location_area
        )
        st.session_state.callback_offer = lead.get(
            "callback_offer", st.session_state.callback_offer
        )


def start_call(
    lead_phone: str,
    lead_name: str,
    property_type: str,
    location_area: str,
    callback_offer: str,
    script_id: str | None,
    system_prompt: str | None,
):
    # hits FastAPI /call (server holds Twilio creds)
    resp = requests.post(
        f"{BACKEND_URL}/call",
        json={
            "to": lead_phone,
            "lead_name": lead_name,
            "property_type": property_type,
            "location_area": location_area,
            "callback_offer": callback_offer,
            "script_id": script_id,
            "system_prompt": system_prompt,
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
if not st.session_state.scripts:
    st.session_state.scripts = fetch_call_scripts()
script_map = {s.get("name", s.get("id")): s.get("id") for s in st.session_state.scripts}

with st.form("lead_form", clear_on_submit=False):
    col1, col2 = st.columns(2)
    with col1:
        lead_name = st.text_input("Lead name", key="lead_name")
        property_type = st.text_input("Property type", key="property_type")
        location_area = st.text_input("Location area", key="location_area")
    with col2:
        lead_phone = st.text_input(
            "Lead phone (E.164)", key="lead_phone", on_change=lookup_lead
        )
        callback_offer = st.text_input("Callback offer", key="callback_offer")
        if script_map:
            script_label = st.selectbox(
                "Call script", list(script_map.keys()), key="script_label"
            )
            script_id = script_map.get(script_label)
        else:
            script_id = st.text_input("Call script ID", key="script_id")
        system_prompt = st.text_area("Custom system prompt", key="system_prompt")

    if lead_phone != st.session_state.loaded_phone:
        try:
            existing = asyncio.run(get_script(lead_phone))
            st.session_state.script_text = (
                existing.script_text if existing else ""
            )
        except Exception:
            st.session_state.script_text = ""
        st.session_state.loaded_phone = lead_phone

    script_text = st.text_area("Call script", key="script_text")

    col_save, col_call = st.columns(2)
    with col_save:
        save_script = st.form_submit_button("Save Script")
    with col_call:
        submitted = st.form_submit_button("Start Call")

    if save_script:
        asyncio.run(
            log_script(
                LeadScript(
                    lead_phone=lead_phone,
                    script_id="default",
                    script_text=script_text,
                )
            )
        )
        add_msg("assistant", "💾 Script saved.")

    if submitted:
        try:
            add_msg("system", f"Dialing {lead_phone} ({lead_name})…")
            st.session_state.call_sid = start_call(
                lead_phone,
                lead_name,
                property_type,
                location_area,
                callback_offer,
                script_id,
                system_prompt,
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