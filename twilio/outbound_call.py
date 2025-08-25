# 📂 twilio/outbound_call.py

"""Initiate an outbound Twilio call that starts the voice bot webhook."""

import os
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

to_number = os.getenv("LEAD_PHONE")  # e.g. +15551231234
from_number = os.getenv("TWILIO_NUMBER")  # Your Twilio verified number
lead_name = os.getenv("LEAD_NAME", "lead")
voice_base = os.getenv("VOICE_WEBHOOK_URL", "https://your-app.fly.dev/twilio-voice")
voice_url = f"{voice_base}?lead_name={lead_name}"
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

call = client.calls.create(
    to=to_number,
    from_=from_number,
    url=voice_url,  # 🔁 Starts the AI loop webhook
    method="POST"  # Required for <Gather> to POST back
)

print(f"📞 Calling {to_number} via Twilio. SID: {call.sid}")
