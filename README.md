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

## Prerequisites

Before running the bot you will need accounts and API keys for:

- **OpenAI** – used for GPT-4o responses.
- **ElevenLabs** – text-to-speech voice generation.
- **Supabase** – optional logging of conversations.
- **Twilio** – outbound phone calls. Purchase or verify a phone number and, if on a
  trial account, [verify the destination number](https://www.twilio.com/docs/usage/tutorials/how-to-use-your-free-trial-account#verify-an-outbound-caller-id).

You also need **Python 3.10+** and `git` installed locally.

If Twilio is going to call a server running on your machine, you must expose it to the
internet (for example by using [ngrok](https://ngrok.com/) or by deploying to Fly.io).

## Step‑by‑Step Setup

### 1. Clone the repository and install dependencies

```bash
git clone <this repo>
cd Trifivend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment variables

Create a `.env` file from the provided example and fill in all required values:

```bash
cp .env.example .env
```

Key variables and what they are for:

- `OPENAI_API_KEY` – OpenAI API key.
- `OPENAI_MODEL` – model to use (default `gpt-4`).
- `ELEVEN_API_KEY` – ElevenLabs API key for TTS.
- `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` – optional Supabase logging.
- `TWILIO_SID` and `TWILIO_AUTH_TOKEN` – found in the Twilio console under
  **Account > Keys & Credentials**.
- `TWILIO_NUMBER` – the Twilio phone number making calls.
- `LEAD_PHONE` – the phone number to dial (E.164 format, e.g. `+15551234567`).
- `VOICE_WEBHOOK_URL` – public URL for the bot's voice webhook. When running locally
  you can tunnel your dev server with `ngrok http 8080` and set this to
  `https://<ngrok-id>.ngrok.io/twilio-voice`. If deployed on Fly, use the Fly domain
  (e.g. `https://your-app.fly.dev/twilio-voice`).

### 3. Start the backend service

The backend exposes the `/twilio-voice` endpoint that Twilio calls during outbound
calls. Launch it with:

```bash
./run_dev.sh
```

The server listens on `http://localhost:8080`. Ensure it is reachable from the public
internet at the URL specified by `VOICE_WEBHOOK_URL`.

### 4. (Optional) Open the web simulator

There is a simple frontend for local testing:

```bash
cd ../frontend
open index.html
```

### 5. Place an outbound call

With the backend running and `VOICE_WEBHOOK_URL` pointing to it, initiate a call to
`LEAD_PHONE`:

```bash
python twilio/outbound_call.py
```

Twilio will dial the lead and POST to `/twilio-voice`, which starts the GPT-4o voice
loop.

## Deploy to Fly.io

To run the bot in production on Fly.io and obtain a stable public URL:

```bash
cd deploy
./deploy.sh
```

## Authors
Built by Fritz
