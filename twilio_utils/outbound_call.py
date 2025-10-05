# twilio/outbound_call.py
# ──────────────────────────────────────────────────────────────────────────────
# Utilities for initiating and managing outbound Twilio calls.
# - E.164 validation
# - Voice webhook URL derived from APP_BASE_URL if VOICE_WEBHOOK_URL unset
# - Optional timeouts & light retry for transient errors
# - CLI: call | cancel | end | status
# ──────────────────────────────────────────────────────────────────────────────

from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Optional, Tuple

from dotenv import load_dotenv
from twilio.base.exceptions import TwilioException
from twilio.http.http_client import HttpClient
from twilio.rest import Client

# Load .env early so local dev Just Works™
load_dotenv()

# ──────────────────────────────────────────────────────────────────────────────
# Config & helpers
# ──────────────────────────────────────────────────────────────────────────────

E164_RE = re.compile(r"^\+\d{8,15}$")

def _require_env(key: str, *, allow_empty: bool = False) -> str:
    val = os.getenv(key, "")
    if not allow_empty and not (val or "").strip():
        raise RuntimeError(f"Missing required environment variable: {key}")
    return val.strip()

def _resolve_voice_url() -> str:
    """
    VOICE_WEBHOOK_URL (absolute) takes precedence.
    Otherwise derive https://.../twilio-voice from APP_BASE_URL.
    """
    voice = os.getenv("VOICE_WEBHOOK_URL", "").strip()
    if voice:
        return voice.rstrip("/")
    base = os.getenv("APP_BASE_URL", "").strip() or "https://ai-callbot.fly.dev"
    return f"{base.rstrip('/')}/twilio-voice"

def _e164(phone: str) -> str:
    p = (phone or "").strip()
    if not E164_RE.match(p):
        raise ValueError("Invalid phone number format. Use E.164 like +14155550123")
    return p

# ──────────────────────────────────────────────────────────────────────────────
# Twilio client factory (with optional timeout)
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TwilioConfig:
    account_sid: str
    auth_token: str
    from_number: str
    voice_url: str
    timeout: float = 10.0  # seconds

def _http_client(timeout: float) -> HttpClient:
    # Twilio's default client supports a timeout; keep lean to avoid extra deps
    class _T(HttpClient):
        def request(self, *args, **kwargs):
            kwargs.setdefault("timeout", timeout)
            return super().request(*args, **kwargs)
    return _T()

def create_twilio_client(cfg: TwilioConfig) -> Client:
    return Client(cfg.account_sid, cfg.auth_token, http_client=_http_client(cfg.timeout))

def _load_config() -> TwilioConfig:
    return TwilioConfig(
        account_sid=_require_env("TWILIO_ACCOUNT_SID"),
        auth_token=_require_env("TWILIO_AUTH_TOKEN"),
        from_number=_require_env("TWILIO_NUMBER"),
        voice_url=_resolve_voice_url(),
        timeout=float(os.getenv("TWILIO_HTTP_TIMEOUT", "10")),
    )

# ──────────────────────────────────────────────────────────────────────────────
# Light retry wrapper for transient API errors
# ──────────────────────────────────────────────────────────────────────────────

def _retry(fn, *, attempts: int = 3, backoff: float = 0.6):
    last_err = None
    for i in range(1, attempts + 1):
        try:
            return fn()
        except TwilioException as e:
            last_err = e
            # Backoff on network glitches / 5xx; re-raise for 4xx immediately
            msg = str(e).lower()
            is_transient = any(x in msg for x in ("timeout", "timed out", "5", "service unavailable", "gateway"))
            if i == attempts or not is_transient:
                raise
            time.sleep(backoff * i)
    if last_err:
        raise last_err

# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def initiate_call(
    to_number: str,
    from_number: Optional[str] = None,
    voice_url: Optional[str] = None,
    *,
    client: Optional[Client] = None,
) -> Tuple[str, str]:
    """
    Start an outbound call and return (call_sid, status).
    - Validates E.164 for 'to_number'
    - 'from_number' and 'voice_url' fall back to env/config
    """
    cfg = _load_config()
    c = client or create_twilio_client(cfg)

    to = _e164(to_number)
    frm = _e164(from_number or cfg.from_number)
    url = (voice_url or cfg.voice_url).rstrip("/")

    def _do():
        return c.calls.create(
            to=to,
            from_=frm,
            url=url,
            method="POST",  # required for <Gather> to POST back
        )

    call = _retry(_do)
    return call.sid, getattr(call, "status", "queued")

def cancel_call(call_sid: str, *, client: Optional[Client] = None) -> Tuple[str, str]:
    """Cancel a ringing/queued call. Returns (sid, status)."""
    cfg = _load_config()
    c = client or create_twilio_client(cfg)
    def _do():
        return c.calls(call_sid).update(status="canceled")
    call = _retry(_do)
    return call.sid, getattr(call, "status", "canceled")

def end_call(call_sid: str, *, client: Optional[Client] = None) -> Tuple[str, str]:
    """End an in-progress call. Returns (sid, status)."""
    cfg = _load_config()
    c = client or create_twilio_client(cfg)
    def _do():
        return c.calls(call_sid).update(status="completed")
    call = _retry(_do)
    return call.sid, getattr(call, "status", "completed")

def get_call_status(call_sid: str, *, client: Optional[Client] = None) -> str:
    """Fetch the current status of a call."""
    cfg = _load_config()
    c = client or create_twilio_client(cfg)
    def _do():
        return c.calls(call_sid).fetch()
    call = _retry(_do)
    return getattr(call, "status", "(unknown)")

# ──────────────────────────────────────────────────────────────────────────────
# CLI (for quick ops): call | cancel | end | status
# ──────────────────────────────────────────────────────────────────────────────

def _cli() -> int:
    parser = argparse.ArgumentParser(description="Twilio outbound call utilities")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_call = sub.add_parser("call", help="Initiate an outbound call")
    p_call.add_argument("--to", required=True, help="E.164 number, e.g. +14155550123")
    p_call.add_argument("--from", dest="from_number", help="Override FROM number (E.164)")
    p_call.add_argument("--voice-url", help="Override voice webhook URL")

    p_cancel = sub.add_parser("cancel", help="Cancel a ringing/queued call")
    p_cancel.add_argument("--sid", required=True, help="Call SID")

    p_end = sub.add_parser("end", help="End an in-progress call")
    p_end.add_argument("--sid", required=True, help="Call SID")

    p_status = sub.add_parser("status", help="Get call status")
    p_status.add_argument("--sid", required=True, help="Call SID")

    args = parser.parse_args()

    try:
        if args.cmd == "call":
            sid, status = initiate_call(args.to, args.from_number, args.voice_url)
            print(f"📞 Call queued: SID={sid} status={status}")
        elif args.cmd == "cancel":
            sid, status = cancel_call(args.sid)
            print(f"🛑 Call canceled: SID={sid} status={status}")
        elif args.cmd == "end":
            sid, status = end_call(args.sid)
            print(f"✅ Call ended: SID={sid} status={status}")
        elif args.cmd == "status":
            status = get_call_status(args.sid)
            print(f"ℹ️  Call status: SID={args.sid} status={status}")
        return 0
    except (RuntimeError, ValueError, TwilioException) as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(_cli())