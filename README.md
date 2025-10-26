# TriFiVend MVP

This repository contains a deliberately minimal implementation of the TriFiVend calling tool. The goal is to provide a working proof of concept without the layers of experimental agents and deployment scripts that previously cluttered the project.

## Project layout

```
backend/   # FastAPI application code
ui/        # Vite + React front-end for triggering calls
main.py    # Uvicorn entrypoint that exposes `backend.create_app`
```

A lightweight JSON file in `data/calls.json` keeps track of every call request. The file is created automatically when the API boots.

## Running the API locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.backend.txt
uvicorn main:app --reload
```

Environment variables (optional but required for real phone calls):

- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN`
- `TWILIO_FROM_NUMBER`

If these values are missing the API will still accept requests, but it will only record them locally instead of placing real calls.

## Running the UI

```bash
cd ui
npm install
npm run dev
```

The development server assumes the API is available at `http://localhost:8000`. You can change this by updating the `API_BASE_URL` constant in `ui/src/api.ts`.

## Tests

```bash
pytest
```

The tests cover the most important flows: creating calls, listing them, and updating their status.
