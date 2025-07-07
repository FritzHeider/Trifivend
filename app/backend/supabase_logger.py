### 📂 `app/backend/supabase_logger.py`

import os
import requests
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json"
}

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
