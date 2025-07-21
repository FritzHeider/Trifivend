import openai
import os
from app.backend.supabase_logger import log_conversation, fetch_lead_context
from agent.speak import speak_text  
from dotenv import load_dotenv

load_dotenv()
openai.api_key = os.getenv("OPENAI_API_KEY")

# Dynamic system prompt template
SYSTEM_PROMPT_TEMPLATE = """
You are a professional AI voice agent named Ava, working for {company_name}.
You are calling {lead_name}, the property manager of a {property_type} in {location_area}.

Your goal is to introduce SmartVend — an AI-powered vending solution that improves uptime and revenue. 
Use a confident, friendly tone. If they object, ask one thoughtful follow-up before ending the call.
If they’re interested, offer to {callback_offer}.
"""

def coldcall_lead(transcript_so_far, lead_id=None):
    # 🎯 Pull lead details from Supabase
    lead_context = fetch_lead_context(lead_id) if lead_id else {
        "company_name": "Trifivend",
        "lead_name": "there",
        "property_type": "business",
        "location_area": "your area",
        "callback_offer": "schedule a call"
    }

    # 🧠 Format prompt dynamically
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(**lead_context)

    # 🤖 Call OpenAI
    response = openai.ChatCompletion.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": system_prompt}] + transcript_so_far,
        temperature=0.7
    )

    reply = response.choices[0].message.content
    print("🤖 GPT:", reply)

    # 🔊 Speak with ElevenLabs
    speak_text(reply)

    # 📝 Log to Supabase
    user_input = transcript_so_far[-1]["content"] if transcript_so_far else "N/A"
    log_conversation(user_input=user_input, bot_reply=reply, lead_id=lead_id)

    return reply

# Dev test
if __name__ == "__main__":
    test_convo = [{"role": "user", "content": "Uh hello, who is this?"}]
    coldcall_lead(test_convo, lead_id=1)