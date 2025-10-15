# TriFiVend — API + UI

## API (FastAPI on Fly.io)

**Run local**
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.backend.txt
cp .env.example .env   # fill in values
python -m uvicorn main:app --host :: --port 8080
