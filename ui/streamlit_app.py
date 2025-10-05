# ui/streamlit_app.py
# ──────────────────────────────────────────────────────────────────────────────
# Trifivend Streamlit Interface (full file)
# - Works with Fly Machines (private IPv6 mesh) or public backend URL
# - Shapes /call payload from OpenAPI when available, with safe fallbacks
# - Validates E.164 phone input
# - Supabase-backed script lookup + save (optional)
# - SSE live event follower with auto-reconnect
# - Diagnostics panel for OpenAPI + /health
#
# Env / Secrets:
#   BACKEND_URL           (e.g., http://ai-callbot.internal:8080 or https://ai-callbot.fly.dev)
#   SUPABASE_URL          (optional)
#   SUPABASE_ANON_KEY     (optional)
#
# Run:
#   PYTHONPATH=. streamlit run ui/streamlit_app.py
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

# ---- Stdlib -----------------------------------------------------------------
import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Generator, Iterable, Optional, Tuple
from urllib.parse import urljoin

# ---- Third-party ------------------------------------------------------------
import requests
import streamlit as st

# ---- Local imports (robust path injection) ----------------------------------
try:
    from app.backend.supabase_logger import LeadScript, log_script, get_script
except ModuleNotFoundError:
    repo_root = Path(__file__).resolve().parents[1]  # <repo_root>
    sys.path.insert(0, str(repo_root))
    from app.backend.supabase_logger import LeadScript, log_script, get_script

# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────

def _get_secret(key: str, default: str = "") -> str:
    val = os.getenv(key)
    if val:
        return val
    try:
        v = st.secrets.get(key)
        if v:
            return str(v)
    except Exception:
        pass
    return default

def _backend_url() -> str:
    # Prefer env; fallback to Streamlit secrets; finally localhost (dev)
    url = _get_secret("BACKEND_URL", "http://localhost:8080").strip()
    return url.rstrip("/")

BACKEND_URL = _backend_url()

# Tunables
REQ_TIMEOUT = float(_get_secret("REQ_TIMEOUT", "15"))
SSE_TIMEOUT = int(float(_get_secret("SSE_TIMEOUT", "300")))  # seconds
OPENAPI_TTL = int(float(_get_secret("OPENAPI_TTL", "60")))   # seconds

# E.164 validator
E164_RE = re.compile(r"^\+\d{8,15}$")

# Streamlit page config
st.set_page_config(page_title="Trifivend", layout="wide")
st.title("Trifivend — Lead Dialer UI")

# ──────────────────────────────────────────────────────────────────────────────
# Diagnostics (OpenAPI + Health)
# ──────────────────────────────────────────────────────────────────────────────

def _get_json(url: str, timeout: float = REQ_TIMEOUT) -> tuple[bool, int | None, dict | str]:
    try:
        r = requests.get(url, timeout=timeout)
        if r.ok:
            return True, r.status_code, r.json()
        return False, r.status_code, r.text
    except Exception as e:
        return False, None, str(e)

with st.expander("🔎 Diagnostics", expanded=False):
    st.write("**BACKEND_URL:**", BACKEND_URL)

    ok_h, code_h, body_h = _get_json(urljoin(BACKEND_URL + "/", "health"))
    st.write("Health:", "✅ 200" if ok_h else f"❌ {code_h or 'error'}")
    if not ok_h and body_h:
        st.code(str(body_h)[:1000])

    ok_o, code_o, body_o = _get_json(urljoin(BACKEND_URL + "/", "openapi.json"))
    st.write("OpenAPI:", "✅ reachable" if ok_o else f"❌ {code_o or 'error'}")
    if ok_o and isinstance(body_o, dict):
        try:
            call_schema = (
                body_o.get("paths", {})
                      .get("/call", {})
                      .get("post", {})
                      .get("requestBody", {})
                      .get("content", {})
                      .get("application/json", {})
                      .get("schema", {})
            )
            st.caption("`/call` request schema (truncated):")
            st.code(json.dumps(call_schema, indent=2)[:1600], language="json")
        except Exception as e:
            st.write("OpenAPI parse error:", e)

# ──────────────────────────────────────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────────────────────────────────────

def _safe_e164(phone: str) -> str:
    p = (phone or "").strip()
    if not E164_RE.match(p):
        raise ValueError("Invalid phone format. Use E.164 like +14155550123")
    return p

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

@st.cache_data(ttl=OPENAPI_TTL, show_spinner=False)
def _cached_openapi(url: str) -> Optional[dict]:
    ok, _, body = _get_json(url)
    return body if ok and isinstance(body, dict) else None

def _get_openapi() -> Optional[dict]:
    return _cached_openapi(urljoin(BACKEND_URL + "/", "openapi.json"))

@st.cache_data(ttl=30, show_spinner=False)
def _supabase_select(url: str, apikey: str, params: dict) -> list[dict]:
    r = requests.get(
        url,
        headers={
            "apikey": apikey,
            "Authorization": f"Bearer {apikey}",
        },
        params=params,
        timeout=REQ_TIMEOUT,
    )
    r.raise_for_status()
    return r.json()

def fetch_call_scripts() -> list[dict]:
    url = _get_secret("SUPABASE_URL")
    key = _get_secret("SUPABASE_ANON_KEY")
    if not url or not key:
        return []
    try:
        return _supabase_select(
            f"{url}/rest/v1/call_scripts",
            key,
            {"select": "id,name", "order": "name.asc"},
        )
    except Exception as e:
        st.toast(f"Supabase scripts error: {e}", icon="⚠️")
        return []

def fetch_lead_by_phone(phone: str) -> Optional[dict]:
    url = _get_secret("SUPABASE_URL")
    key = _get_secret("SUPABASE_ANON_KEY")
    if not url or not key:
        return None
    try:
        data = _supabase_select(
            f"{url}/rest/v1/leads",
            key,
            {
                "select": "name,property_type,location_area,callback_offer",
                "phone": f"eq.{phone}",
                "limit": 1,
            },
        )
        return data[0] if data else None
    except Exception as e:
        st.toast(f"Supabase lead fetch error: {e}", icon="⚠️")
        return None

# ──────────────────────────────────────────────────────────────────────────────
# OpenAPI-aware payload builder
# ──────────────────────────────────────────────────────────────────────────────

def _deref(openapi: dict, obj: dict) -> dict:
    if not isinstance(obj, dict) or "$ref" not in obj:
        return obj
    ref = obj.get("$ref", "")
    m = re.match(r"#/components/schemas/(?P<name>.+)", ref or "")
    if m:
        return openapi.get("components", {}).get("schemas", {}).get(m["name"], obj)
    return obj

def _shape_call_payload(*, openapi: Optional[dict], local: dict) -> dict:
    """
    Use OpenAPI schema to map UI fields → backend fields. If OpenAPI is
    unavailable, send a sane subset covering snake_case/camelCase aliases.
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
            schema = _deref(openapi, content.get("schema", {}))
            props = schema.get("properties", {})
            expected_fields = list(props.keys())
            required_fields = set(schema.get("required", []))
        except Exception as e:
            st.toast(f"OpenAPI parse error (fallback payload): {e}", icon="⚠️")
            expected_fields = []

    payload: dict = {}

    if expected_fields:
        for field in expected_fields:
            sources = alias_map.get(field, []) + [field]
            val = None
            for s in sources:
                if s in candidates and candidates[s] not in (None, "", []):
                    val = candidates[s]
                    break
            if val is None and field in required_fields:
                val = ""  # send empty value rather than omit required key
            if val is not None:
                payload[field] = val
    else:
        payload = {
            "to": candidates["lead_phone"],
            "lead_name": candidates["lead_name"],
            "property_type": candidates["property_type"],
            "location_area": candidates["location_area"],
            "callback_offer": candidates["callback_offer"],
            "script_id": candidates["script_id"],
            "system_prompt": candidates["system_prompt"],
            # provide common alternates; backend uses pydantic aliases anyway
            "name": candidates["lead_name"],
            "propertyType": candidates["property_type"],
            "location": candidates["location_area"],
            "offer": candidates["callback_offer"],
            "scriptId": candidates["script_id"],
            "systemPrompt": candidates["system_prompt"],
        }
        payload = {k: v for k, v in payload.items() if v not in (None, "", [])}

    return payload

# ──────────────────────────────────────────────────────────────────────────────
# Backend calls
# ──────────────────────────────────────────────────────────────────────────────

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
    lead_phone = _safe_e164(lead_phone)
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
        timeout=REQ_TIMEOUT,
    )

    if not resp.ok:
        try:
            detail = resp.json()
        except Exception:
            detail = resp.text
        raise RuntimeError(
            f"{resp.status_code} error from /call\n"
            f"Payload:\n{json.dumps(payload, indent=2)}\n\n"
            f"Response:\n{detail}"
        )

    data = resp.json()
    call_sid = data.get("call_sid") or data.get("sid") or data.get("callSid")
    if not call_sid:
        raise RuntimeError(f"Backend response missing call_sid: {data}")
    return call_sid

def stream_events(call_sid: str) -> Generator[dict, None, None]:
    """
    SSE event generator with basic keep-alive handling.
    """
    params = {"sid": call_sid}
    with requests.get(
        urljoin(BACKEND_URL + "/", "sse"),
        params=params,
        stream=True,
        timeout=SSE_TIMEOUT,
    ) as r:
        r.raise_for_status()
        for raw in r.iter_lines(decode_unicode=True):
            if not raw:
                continue
            if not raw.startswith("data:"):
                continue
            payload = raw.split("data:", 1)[1].strip()
            if payload == "{}":  # heartbeat
                continue
            try:
                yield json.loads(payload)
            except json.JSONDecodeError:
                st.toast("SSE decode error (skipped line)", icon="⚠️")

# ──────────────────────────────────────────────────────────────────────────────
# Session State
# ──────────────────────────────────────────────────────────────────────────────

if "messages" not in st.session_state:
    st.session_state.messages = []
if "call_sid" not in st.session_state:
    st.session_state.call_sid = None
if "scripts" not in st.session_state:
    st.session_state.scripts = []
if "loaded_phone" not in st.session_state:
    st.session_state.loaded_phone = None
if "script_text" not in st.session_state:
    st.session_state.script_text = ""
if "lead_defaults" not in st.session_state:
    st.session_state.lead_defaults = {
        "lead_name": "Fritz",
        "property_type": "apartment buildings",
        "location_area": "San Francisco",
        "lead_phone": "+14155550123",
        "callback_offer": "schedule a free design session",
        "system_prompt": "",
    }

def add_msg(role: str, content: str) -> None:
    st.session_state.messages.append({"role": role, "content": content})

def render_history() -> None:
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.write(m["content"])

# ──────────────────────────────────────────────────────────────────────────────
# Initial data fetch
# ──────────────────────────────────────────────────────────────────────────────

if not st.session_state.scripts:
    st.session_state.scripts = fetch_call_scripts()
script_map = {s.get("name", s.get("id")): s.get("id") for s in st.session_state.scripts}

# ──────────────────────────────────────────────────────────────────────────────
# Lead form
# ──────────────────────────────────────────────────────────────────────────────

with st.form("lead_form", clear_on_submit=False):
    col1, col2 = st.columns(2)

    with col1:
        lead_name = st.text_input("Lead name", value=st.session_state.lead_defaults["lead_name"], key="lead_name")
        property_type = st.text_input("Property type", value=st.session_state.lead_defaults["property_type"], key="property_type")
        location_area = st.text_input("Location area", value=st.session_state.lead_defaults["location_area"], key="location_area")

    with col2:
        lead_phone = st.text_input("Lead phone (E.164)", value=st.session_state.lead_defaults["lead_phone"], key="lead_phone")
        callback_offer = st.text_input("Callback offer", value=st.session_state.lead_defaults["callback_offer"], key="callback_offer")

        if script_map:
            script_label = st.selectbox("Call script", list(script_map.keys()), key="script_label")
            script_id = script_map.get(script_label)
        else:
            script_id = st.text_input("Call script ID", key="script_id")

        system_prompt = st.text_area("Custom system prompt (optional)", value=st.session_state.lead_defaults["system_prompt"], key="system_prompt")

    script_text = st.text_area("Call script (saved to Supabase when you click Save)", key="script_text", height=220)

    col_lookup, col_save, col_call = st.columns(3)
    with col_lookup:
        lookup_pressed = st.form_submit_button("🔎 Lookup Lead")
    with col_save:
        save_script = st.form_submit_button("💾 Save Script")
    with col_call:
        submitted = st.form_submit_button("📞 Start Call")

    if lookup_pressed:
        try:
            lp = _safe_e164(st.session_state.lead_phone)
            lead = fetch_lead_by_phone(lp)
            if lead:
                st.session_state.lead_name = lead.get("name", st.session_state.lead_name)
                st.session_state.property_type = lead.get("property_type", st.session_state.property_type)
                st.session_state.location_area = lead.get("location_area", st.session_state.location_area)
                st.session_state.callback_offer = lead.get("callback_offer", st.session_state.callback_offer)
                add_msg("assistant", "🔎 Lead details loaded.")
            else:
                add_msg("assistant", "🔎 No matching lead found.")
        except Exception as e:
            add_msg("assistant", f"❌ Lookup failed: {e}")

    if save_script:
        try:
            _ = _safe_async_run(
                log_script(
                    LeadScript(
                        lead_phone=_safe_e164(lead_phone),
                        script_id=(script_id or "default"),
                        script_text=script_text or "",
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

# ──────────────────────────────────────────────────────────────────────────────
# Chat history
# ──────────────────────────────────────────────────────────────────────────────

render_history()

# ──────────────────────────────────────────────────────────────────────────────
# Live event stream (SSE)
# ──────────────────────────────────────────────────────────────────────────────

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

# ──────────────────────────────────────────────────────────────────────────────
# Freeform note box (stubbed)
# ──────────────────────────────────────────────────────────────────────────────

if prompt := st.chat_input("Type a note to log with this lead…"):
    add_msg("user", prompt)
    with st.chat_message("assistant"):
        st.write("Noted. (Wire this to Supabase logging if desired.)")