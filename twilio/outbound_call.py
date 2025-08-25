# 📂 twilio/outbound_call.py

"""Utilities for initiating and managing outbound Twilio calls."""

from __future__ import annotations

import os
from typing import Tuple

from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
FROM_NUMBER = os.getenv("TWILIO_NUMBER")  # Your Twilio verified number
VOICE_URL = os.getenv("VOICE_WEBHOOK_URL", "https://your-app.fly.dev/twilio-voice")

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def initiate_call(to_number: str,
                  from_number: str = FROM_NUMBER,
                  voice_url: str = VOICE_URL) -> Tuple[str, str]:
    """Start an outbound call and return the call SID and status."""

    call = client.calls.create(
        to=to_number,
        from_=from_number,
        url=voice_url,  # 🔁 Starts the AI loop webhook
        method="POST",  # Required for <Gather> to POST back
    )
    return call.sid, call.status


def cancel_call(call_sid: str) -> Tuple[str, str]:
    """Cancel a ringing/queued call."""

    call = client.calls(call_sid).update(status="canceled")
    return call.sid, call.status


def end_call(call_sid: str) -> Tuple[str, str]:
    """End an in-progress call."""

    call = client.calls(call_sid).update(status="completed")
    return call.sid, call.status


def get_call_status(call_sid: str) -> str:
    """Fetch the current status of a call."""

    return client.calls(call_sid).fetch().status


if __name__ == "__main__":
    to_number = os.getenv("LEAD_PHONE")  # e.g. +15551231234
    if not to_number:
        raise SystemExit("LEAD_PHONE environment variable is required")
    sid, status = initiate_call(to_number)
    print(f"📞 Calling {to_number} via Twilio. SID: {sid}. Status: {status}")

