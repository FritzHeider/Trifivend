# 📂 twilio/outbound_call.py

import os
from twilio.rest import Client
from dotenv import load_dotenv

load_dotenv()

to_number = os.getenv("LEAD_PHONE")          # e.g. +15551231234
from_number = os.getenv("TWILIO_NUMBER")     # Your Twilio verified number
TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

client = Client(TWILIO_SID, TWILIO_TOKEN)

call = client.calls.create(
    to=to_number,
    from_=from_number,
    url="https://your-app.fly.dev/twilio-voice",  # 🔁 Starts the AI loop webhook
    method="POST"  # Required for <Gather> to POST back
)

print(f"📞 Calling {to_number} via Twilio. SID: {call.sid}")