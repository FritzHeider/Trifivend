# twilio_utils/outbound_call.py
# ──────────────────────────────────────────────────────────────────────────────
# Utilities for initiating and managing outbound Twilio calls.
# - E.164 validation
# - Voice webhook URL derived from APP_BASE_URL if VOICE_WEBHOOK_URL unset
# - Optional HTTP timeouts + light retry on transient errors
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

load_dotenv()

E164_RE = re.compile(r"^\+\d{8,15}$")

def _require_env(key: str, *, allow_empty: bool = False) -> str:
    v = os.getenv(key, "").strip()
    if not allow_empty and not v:
        raise RuntimeError(f"Missing required environment variable: {key}")
    return v

def _resolve_voice_url() -> str:
    voice = os.getenv("VOICE_WEBHOOK_URL", "").strip()
    if voice:
        return voice.rstrip("/")
    base = os.getenv("APP_BASE_URL", "").strip() or "https://ai-callbot.fly.dev"
    return f"{base.rstrip('/')}/twilio-voice"

def _e164(phone: str) -> str:
    p = (phone or "").strip()
    if not E164_RE.match(p):
        raise ValueError("Invalid E.164 phone format (e.g., +14155550123).")
    return p

@dataclass(frozen=True)
class TwilioConfig:
    account_sid: str
    auth_token: str
    from_number: str
    voice_url: str
    timeout: float = 10.0  # seconds

def _http_client(timeout: float) -> HttpClient:
    class _T(HttpClient):
        def request(self, *args, **kwargs):
            kwargs.setdefault("timeout", timeout)
            return super().request(*args, **kwargs)
    return _T()

def _load_cfg() -> TwilioConfig:
    return TwilioConfig(
        account_sid=_require_env("TWILIO_ACCOUNT_SID"),
        auth_token=_require_env("TWILIO_AUTH_TOKEN"),
        from_number=_require_env("TWILIO_NUMBER"),
        voice_url=_resolve_voice_url(),
        timeout=float(os.getenv("TWILIO_HTTP_TIMEOUT", "10")),
    )

def _client(cfg: TwilioConfig) -> Client:
    return Client(cfg.account_sid, cfg.auth_token, http_client=_http_client(cfg.timeout))

def _retry(fn, *, attempts: int = 3, backoff: float = 0.6):
    err = None
    for i in range(1, attempts + 1):
        try:
            return fn()
        except TwilioException as e:
            msg = str(e).lower()
            transient = any(s in msg for s in ("timeout", "timed out", "5", "unavailable", "gateway"))
            if i == attempts or not transient:
                raise
            err = e
            time.sleep(backoff * i)
    if err:
        raise err

def initiate_call(
    to_number: str,
    from_number: Optional[str] = None,
    voice_url: Optional[str] = None,
    *,
    client_obj: Optional[Client] = None,
) -> Tuple[str, str]:
    cfg = _load_cfg()
    c = client_obj or _client(cfg)
    to = _e164(to_number)
    frm = _e164(from_number or cfg.from_number)
    url = (voice_url or cfg.voice_url).rstrip("/")

    call = _retry(lambda: c.calls.create(to=to, from_=frm, url=url, method="POST"))
    return call.sid, getattr(call, "status", "queued")

def cancel_call(call_sid: str, *, client_obj: Optional[Client] = None) -> Tuple[str, str]:
    cfg = _load_cfg()
    c = client_obj or _client(cfg)
    call = _retry(lambda: c.calls(call_sid).update(status="canceled"))
    return call.sid, getattr(call, "status", "canceled")

def end_call(call_sid: str, *, client_obj: Optional[Client] = None) -> Tuple[str, str]:
    cfg = _load_cfg()
    c = client_obj or _client(cfg)
    call = _retry(lambda: c.calls(call_sid).update(status="completed"))
    return call.sid, getattr(call, "status", "completed")

def get_call_status(call_sid: str, *, client_obj: Optional[Client] = None) -> str:
    cfg = _load_cfg()
    c = client_obj or _client(cfg)
    call = _retry(lambda: c.calls(call_sid).fetch())
    return getattr(call, "status", "(unknown)")

def _cli() -> int:
    ap = argparse.ArgumentParser(description="Twilio outbound call utilities")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_call = sub.add_parser("call", help="Initiate an outbound call")
    p_call.add_argument("--to", required=True, help="E.164 number, e.g. +14155550123")
    p_call.add_argument("--from", dest="from_number", help="Override FROM number (E.164)")
    p_call.add_argument("--voice-url", help="Override voice webhook URL")

    p_cancel = sub.add_parser("cancel", help="Cancel a ringing/queued call")
    p_cancel.add_argument("--sid", required=True)

    p_end = sub.add_parser("end", help="End an in-progress call")
    p_end.add_argument("--sid", required=True)

    p_status = sub.add_parser("status", help="Get call status")
    p_status.add_argument("--sid", required=True)

    args = ap.parse_args()
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
            print(f"ℹ️  Call status: {get_call_status(args.sid)}")
        return 0
    except (RuntimeError, ValueError, TwilioException) as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(_cli())
