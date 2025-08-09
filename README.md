# Trifivend AI Coldcaller Bot

A full-stack AI-powered coldcalling system that uses OpenAI GPT-4o, ElevenLabs, Whisper, and Twilio to contact, engage, and log leads automatically.

## Features
- 🧠 GPT-4o logic for intelligent calling and responses
- 🗣️ ElevenLabs voice for ultra-humanlike responses
- 🔊 Whisper-based mic input handling (CLI + Web)
- 📞 Twilio outbound voice calling and webhook response
- 🛠 FastAPI backend with Supabase integration
- 🌐 Web interface for local simulation and testing
- 🚀 Fly.io deployable backend and full infrastructure config

## Setup

1. Clone the repo or unzip this folder
2. Install dependencies:

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

3. Create a `.env` from the example:

```bash
cp .env.example .env
```
Then edit `.env` with your API keys and phone numbers. Key variables include:
```
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4
ELEVEN_API_KEY=...
SUPABASE_URL=...
SUPABASE_SERVICE_KEY=...
TWILIO_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_NUMBER=...
LEAD_PHONE=...
VOICE_WEBHOOK_URL=https://your-app.fly.dev/twilio-voice
```

4. Start backend:
```bash
./run_dev.sh
```

5. Open simulator:
```bash
cd ../frontend
open index.html
```

6. Trigger outbound coldcalls:
```bash
python twilio/outbound_call.py
```

## Making Cold Calls for Vending Machine Leads

To launch the dialer for your vending machine business, follow these steps:

1. **Install dependencies** – create and activate a virtual environment, then install the required packages:

   ```bash
   python -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   ```

2. **Configure environment variables** – copy the example file and populate it with your API keys and phone numbers:

   ```bash
   cp .env.example .env
   ```

   Important variables include `OPENAI_API_KEY`, `ELEVEN_API_KEY`, `TWILIO_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_NUMBER`, `LEAD_PHONE`, and `VOICE_WEBHOOK_URL`.

3. **Start the backend server**:

   ```bash
   ./run_dev.sh
   ```

4. **Initiate outbound cold calls** using the Twilio helper script:

   ```bash
   python twilio/outbound_call.py
   ```


## Deploy to Fly.io
```bash
cd deploy
./deploy.sh
```

## Authors
Built by Fritz
