import os
import httpx
from datetime import datetime

def log_conversation(user_input: str, bot_reply: str):
    supabase_url = os.getenv("SUPABASE_URL")
    supabase_key = os.getenv("SUPABASE_SERVICE_KEY")

    if not supabase_url or not supabase_key:
        print("⚠️ Supabase credentials missing — skipping log.")
        return

    payload = {
        "user_input": user_input,
        "bot_reply": bot_reply,
        "timestamp": datetime.utcnow().isoformat()
    }

    try:
        with httpx.Client(timeout=10.0) as client:
            client.post(
                f"{supabase_url}/rest/v1/conversations",
                headers={
                    "apikey": supabase_key,
                    "Authorization": f"Bearer {supabase_key}",
                    "Content-Type": "application/json",
                    "Prefer": "return=minimal"
                },
                json=payload
            )
    except Exception as e:
        print(f"Supabase log error: {e}")