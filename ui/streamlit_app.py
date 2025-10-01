# ### SCAFFOLDING
# Trifivend Streamlit Interface
# Expected layout:
#   <repo_root>/
#     ├─ app/backend/supabase_logger.py   (LeadScript, log_script, get_script)
#     └─ ui/streamlit_app.py              (this file)
# Env / Secrets:
#   - BACKEND_URL (e.g., https://ai-callbot.fly.dev or http://ai-callbot.internal:8080)
#   - SUPABASE_URL
#   - SUPABASE_ANON_KEY
# Run:
#   PYTHONPATH=. streamlit run ui/streamlit_app.py
# Notes:
#   - Auto-fixes sys.path so local imports work without setting PYTHONPATH.
#   - /call payload is shaped using BACKEND_URL/openapi.json when available.
#   - Diagnostics expander shows OpenAPI reachability and /call schema.

from __future__ import annotations

# ---- Stdlib -----------------------------------------------------------------
import asyncio
import json
import os
import sys
import re
from pathlib import Path
from typing import Generator, Optional
from urllib.parse import urljoin

# ---- Third-party ------------------------------------------------------------
import requests
import streamlit as st

# ---- Local imports (robust: auto-add repo root to sys.path if needed) -------
try:
    from app.backend.supabase_logger import LeadScript, log_script, get_script
except ModuleNotFoundError:
    repo_root = Path(__file__).resolve().parents[1]  # <repo_root>
    sys.path.insert(0, str(repo_root))
    from app.backend.supabase_logger import LeadScript, log_script, get_script


# ---- Config -----------------------------------------------------------------
def _backend_url() -> str:
    env = os.getenv("BACKEND_URL")
    if env:
        return env.rstrip("/")
    try:
        return st.secrets.get("BACKEND_URL", "http://localhost:8080").rstrip("/")
    except FileNotFoundError:
        return "http://localhost:8080"

BACKEND_URL = _backend_url()
st.set_page_config(page_title="Trifivend Streamlit Interface", layout="wide")
st.title("Trifivend Streamlit Interface")
# ---- Diagnostics ------------------------------------------------------------
with st.expander("🔎 Diagnostics", expanded=False):
    st.write("**BACKEND_URL**:", BACKEND_URL)
    try:
        j = requests.get(urljoin(BACKEND_URL + "/", "openapi.json"), timeout=10)
        st.write("OpenAPI:", "✅ reachable" if j.ok else f"❌ {j.status_code}")
        if j.ok:
            doc = j.json()
            call_schema = (
                doc.get("paths", {})
                   .get("/call", {})
                   .get("post", {})
                   .get("requestBody", {})
                   .get("content", {})
                   .get("application/json", {})
                   .get("schema", {})
            )
            st.code(json.dumps(call_schema, indent=2)[:1500], language="json")
    except Exception as e:
        st.write("OpenAPI: ❌ error", str(e))


# ---- Utilities ---------------------------------------------------------------

def _safe_async_run(coro):
    """Run an async coroutine safely from Streamlit (which is sync)."""
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def add_msg(role: str, content: str) -> None:
    st.session_state.messages.append({"role": role, "content": content})


def render_history() -> None:
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.write(m["content"])


@st.cache_data(ttl=30, show_spinner=False)
def _supabase_get_json(url: str, apikey: str, params: dict) -> list[dict]:
    """Tiny cached GET helper for Supabase REST endpoints."""
    r = requests.get(
        url,
        headers={
            "apikey": apikey,
            "Authorization": f"Bearer {apikey}",
        },
        params=params,
        timeout=10,
    )
    r.raise_for_status()
    return r.json()


def fetch_call_scripts() -> list[dict]:
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_ANON_KEY")
    if not supabase_url or not supabase_key:
        return []
    try:
        return _supabase_get_json(
            f"{supabase_url}/rest/v1/call_scripts",
            supabase_key,
            {"select": "id,name"},
        )
    except Exception as e:
        print(f"Supabase script fetch error: {e}")
        return []


def fetch_lead_by_phone(phone: str) -> Optional[dict]:
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_ANON_KEY")
    if not supabase_url or not supabase_key:
        return None
    try:
        data = _supabase_get_json(
            f"{supabase_url}/rest/v1/leads",
            supabase_key,
            {
                "select": "name,property_type,location_area,callback_offer",
                "phone": f"eq.{phone}",
                "limit": 1,
            },
        )
        return data[0] if data else None
    except Exception as e:
        print(f"Supabase lead fetch error: {e}")
        return None


def lookup_lead() -> None:
    lead = fetch_lead_by_phone(st.session_state.lead_phone)
    if not lead:
        return
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


# ---------------- OpenAPI-aware payload builder ---------------- #

def _get_openapi() -> dict | None:
    """Fetch the OpenAPI schema from the backend (once per session)."""
    cache_key = "_openapi_schema"
    if cache_key in st.session_state:
        return st.session_state[cache_key]
    try:
        resp = requests.get(urljoin(BACKEND_URL + "/", "openapi.json"), timeout=10)
        if resp.ok:
            st.session_state[cache_key] = resp.json()
            return st.session_state[cache_key]
    except Exception as e:
        print(f"OpenAPI fetch failed: {e}")
    return None


def _shape_call_payload(
    *,
    openapi: dict | None,
    local: dict,
) -> dict:
    """
    Use OpenAPI (if available) to map UI fields -> backend schema.
    Falls back to alias heuristics if schema isn't reachable.
    """
    candidates = {
        "lead_phone": local.get("lead_phone"),
        "lead_name": local.get("lead_name"),
        "property_type": local.get("property_type"),
        "location_area": local.get("location_area"),
        "callback_offer": local.get("callback_offer"),
        "script_id": local.get("script_id"),
        "system_prompt": local.get("system_prompt"),
        "script_text": local.get("script_text"),
    }

    alias_map = {
        "to": ["lead_phone"],
        "phone_number": ["lead_phone", "to"],
        "phoneNumber": ["lead_phone", "to"],

        "lead_name": ["lead_name", "name", "leadName"],
        "name": ["lead_name", "leadName"],
        "leadName": ["lead_name", "name"],

        "property_type": ["property_type", "propertyType"],
        "propertyType": ["property_type"],

        "location_area": ["location_area", "location", "locationArea"],
        "location": ["location_area", "locationArea"],
        "locationArea": ["location_area", "location"],

        "callback_offer": ["callback_offer", "offer", "callbackOffer"],
        "offer": ["callback_offer", "callbackOffer"],
        "callbackOffer": ["callback_offer", "offer"],

        "script_id": ["script_id", "scriptId"],
        "scriptId": ["script_id"],

        "system_prompt": ["system_prompt", "systemPrompt"],
        "systemPrompt": ["system_prompt"],

        "script_text": ["script_text", "script", "scriptText"],
        "scriptText": ["script_text", "script"],
    }

    expected_fields: list[str] = []
    required_fields: set[str] = set()
    if openapi:
        try:
            call_op = openapi["paths"]["/call"]["post"]
            rb = call_op.get("requestBody", {})
            content = rb.get("content", {}).get("application/json", {})
            schema = content.get("schema", {})

            def deref(obj):
                if "$ref" in obj:
                    ref = obj["$ref"]  # e.g. "#/components/schemas/CallRequest"
                    m = re.match(r"#/components/schemas/(?P<name>.+)", ref or "")
                    if m:
                        return openapi["components"]["schemas"][m["name"]]
                return obj

            schema = deref(schema)
            props = schema.get("properties", {})
            expected_fields = list(props.keys())
            required_fields = set(schema.get("required", []))
        except Exception as e:
            print(f"OpenAPI parse error: {e}")
            expected_fields = []

    payload: dict = {}

    if expected_fields:
        # Shape payload to expected fields exactly.
        for field in expected_fields:
            sources = alias_map.get(field, []) + [field]
            val = None
            for s in sources:
                if s in candidates and candidates[s] not in (None, "", []):
                    val = candidates[s]
                    break
            if val is None and field in required_fields:
                # For required fields, fall back to sending empty strings instead
                # of omitting them entirely. The backend accepts empty strings but
                # rejects missing required keys, so this matches the non-OpenAPI
                # payload behaviour where we always included these fields.
                for s in sources:
                    if s in candidates and candidates[s] is not None:
                        val = candidates[s]
                        break
                if val is None:
                    val = ""
            if val is not None:
                payload[field] = val
    else:
        # No OpenAPI—send a sane superset covering snake_case & camelCase.
        payload = {
            "to": candidates["lead_phone"],
            "phone_number": candidates["lead_phone"],
            "phoneNumber": candidates["lead_phone"],

            "lead_name": candidates["lead_name"],
            "name": candidates["lead_name"],
            "leadName": candidates["lead_name"],

            "property_type": candidates["property_type"],
            "propertyType": candidates["property_type"],

            "location_area": candidates["location_area"],
            "location": candidates["location_area"],
            "locationArea": candidates["location_area"],

            "callback_offer": candidates["callback_offer"],
            "offer": candidates["callback_offer"],
            "callbackOffer": candidates["callback_offer"],

            "script_id": candidates["script_id"],
            "scriptId": candidates["script_id"],

            "script_text": candidates["script_text"],
            "scriptText": candidates["script_text"],

            "system_prompt": candidates["system_prompt"],
            "systemPrompt": candidates["system_prompt"],
        }
        payload = {k: v for k, v in payload.items() if v not in (None, "", [])}

    return payload


def start_call(
    *,
    lead_phone: str,
    lead_name: str,
    property_type: str,
    location_area: str,
    callback_offer: str,
    script_id: Optional[str],
    system_prompt: Optional[str],
) -> str:
    """POST /call to the FastAPI backend. Returns Twilio Call SID."""
    openapi = _get_openapi()
    payload = _shape_call_payload(
        openapi=openapi,
        local={
            "lead_phone": lead_phone,
            "lead_name": lead_name,
            "property_type": property_type,
            "location_area": location_area,
            "callback_offer": callback_offer,
            "script_id": script_id,
            "system_prompt": system_prompt,
            "script_text": st.session_state.get("script_text", ""),
        },
    )

    resp = requests.post(
        urljoin(BACKEND_URL + "/", "call"),
        json=payload,
        timeout=30,
    )

    if not resp.ok:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        raise RuntimeError(
            f"{resp.status_code} error from /call\n"
            f"Payload sent:\n{json.dumps(payload, indent=2)}\n\n"
            f"Response:\n{detail}"
        )

    data = resp.json()
    call_sid = data.get("call_sid") or data.get("sid") or data.get("callSid")
    if not call_sid:
        raise RuntimeError(f"Backend response missing call_sid: {data}")
    return call_sid


def stream_events(call_sid: str) -> Generator[dict, None, None]:
    """Simple SSE event generator (no extra deps). Yields dict events."""
    with requests.get(
        urljoin(BACKEND_URL + "/", "sse"),
        params={"sid": call_sid},
        stream=True,
        timeout=300,
    ) as r:
        r.raise_for_status()
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            if not line.startswith("data:"):
                continue
            payload = line.split("data:", 1)[1].strip()
            if payload == "{}":  # heartbeat
                continue
            try:
                yield json.loads(payload)
            except json.JSONDecodeError:
                print(f"SSE decode error on line: {payload!r}")


# ---- Session State ----------------------------------------------------------
if "messages" not in st.session_state:
    st.session_state.messages = []
if "call_sid" not in st.session_state:
    st.session_state.call_sid = None

default_fields = {
    "lead_name": "Fritz",
    "property_type": "apartment buildings",
    "location_area": "San Francisco",
    "lead_phone": "+14154249575",  # E.164
    "callback_offer": "schedule a free design session",
    "system_prompt": "",
}
for k, v in default_fields.items():
    st.session_state.setdefault(k, v)

if "scripts" not in st.session_state:
    st.session_state.scripts = []
if "loaded_phone" not in st.session_state:
    st.session_state.loaded_phone = None
if "script_text" not in st.session_state:
    st.session_state.script_text = ""


# ---- Initial Data Fetch -----------------------------------------------------
if not st.session_state.scripts:
    st.session_state.scripts = fetch_call_scripts()

script_map = {s.get("name", s.get("id")): s.get("id") for s in st.session_state.scripts}


# ---- Lead Form --------------------------------------------------------------
with st.form("lead_form", clear_on_submit=False):
    col1, col2 = st.columns(2)

    with col1:
        lead_name = st.text_input("Lead name", key="lead_name")
        property_type = st.text_input("Property type", key="property_type")
        location_area = st.text_input("Location area", key="location_area")

    with col2:
        # No on_change callbacks inside forms (Streamlit rule)
        lead_phone = st.text_input("Lead phone (E.164)", key="lead_phone")
        callback_offer = st.text_input("Callback offer", key="callback_offer")

        if script_map:
            script_label = st.selectbox(
                "Call script", list(script_map.keys()), key="script_label"
            )
            script_id = script_map.get(script_label)
        else:
            script_id = st.text_input("Call script ID", key="script_id")

        system_prompt = st.text_area("Custom system prompt", key="system_prompt")

    # Script text area
    script_text = st.text_area("Call script", key="script_text", height=220)

    # Buttons (multiple submit buttons are allowed inside a form)
    col_lookup, col_save, col_call = st.columns(3)
    with col_lookup:
        lookup_pressed = st.form_submit_button("🔎 Lookup Lead")
    with col_save:
        save_script = st.form_submit_button("💾 Save Script")
    with col_call:
        submitted = st.form_submit_button("📞 Start Call")

    # Handle which submit happened
    if lookup_pressed:
        lookup_lead()
        add_msg("assistant", "🔎 Lead details loaded (if found).")

    if save_script:
        try:
            _safe_async_run(
                log_script(
                    LeadScript(
                        lead_phone=lead_phone,
                        script_id=(script_id or "default"),
                        script_text=script_text,
                    )
                )
            )
            add_msg("assistant", "💾 Script saved.")
        except Exception as e:
            add_msg("assistant", f"❌ Failed to save script: {e}")

    if submitted:
        try:
            add_msg("system", f"Dialing {lead_phone} ({lead_name})…")
            st.session_state.call_sid = start_call(
                lead_phone=lead_phone,
                lead_name=lead_name,
                property_type=property_type,
                location_area=location_area,
                callback_offer=callback_offer,
                script_id=script_id,
                system_prompt=system_prompt,
            )
            add_msg("system", f"Call SID: {st.session_state.call_sid}")
        except Exception as e:
            add_msg("assistant", f"❌ Failed to start call: {e}")


# ---- Chat History -----------------------------------------------------------
render_history()


# ---- Live Event Stream ------------------------------------------------------
if st.session_state.call_sid:
    if st.button("📡 Follow Live Call Events"):
        placeholder = st.empty()
        try:
            for evt in stream_events(st.session_state.call_sid):
                status = evt.get("status") or evt.get("event") or "event"
                with placeholder.container():
                    with st.chat_message("assistant"):
                        st.write(f"📡 **Twilio** → `{status}`")
                if status in {"completed", "failed", "busy", "no-answer", "canceled"}:
                    add_msg("assistant", f"✅ Call finished with status: **{status}**")
                    break
        except Exception as e:
            add_msg("assistant", f"❌ SSE stream error: {e}")


# ---- Freeform Note Box ------------------------------------------------------
if prompt := st.chat_input("Type a note to log with this lead…"):
    add_msg("user", prompt)
    with st.chat_message("assistant"):
        st.write("Noted. (You can wire this to Supabase logging if desired.)")
