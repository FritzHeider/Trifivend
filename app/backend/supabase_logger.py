import os
import requests
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

# ✅ Original function
def log_to_supabase(lead_name, time, contact_method):
    data = {
        "lead_name": lead_name,
        "time": time,
        "contact_method": contact_method
    }

    response = requests.post(
        f"{SUPABASE_URL}/rest/v1/scheduled_calls",
        headers=headers,
        json=data
    )

    if response.status_code != 201:
        raise Exception(f"Failed to log lead: {response.text}")
    return response.json()

# ✅ NEW: log_conversation
def log_conversation(user_input: str, bot_reply: str, lead_id: int = None):
    data = {
        "user_input": user_input,
        "bot_reply": bot_reply,
        "timestamp": datetime.utcnow().isoformat(),
        "lead_id": lead_id
    }

    response = requests.post(
        f"{SUPABASE_URL}/rest/v1/conversations",
        headers=headers,
        json=data
    )

    if response.status_code != 201:
        raise Exception(f"Failed to log conversation: {response.text}")
    return response.json()

# ✅ NEW: fetch_lead_context
def fetch_lead_context(lead_id: int):
    response = requests.get(
        f"{SUPABASE_URL}/rest/v1/leads?id=eq.{lead_id}&select=company_name,lead_name,property_type,location_area,callback_offer,phone",
        headers=headers
    )

    if response.status_code != 200 or not response.json():
        raise Exception(f"Lead not found: {response.text}")

    lead = response.json()[0]
    return {
        "company_name": lead["company_name"],
        "lead_name": lead["lead_name"],
        "property_type": lead["property_type"],
        "location_area": lead["location_area"],
        "callback_offer": lead.get("callback_offer", "schedule a call"),
        "phone": lead["phone"]
    }