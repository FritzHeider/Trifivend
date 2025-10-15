# TriFiVend — API + UI

## API (FastAPI on Fly.io)

**Run local**
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.backend.txt
cp .env.example .env   # fill in values
python -m uvicorn main:app --host :: --port 8080
```

## Deployment Secrets Quickstart

### Vercel (UI)
1. Open **GitHub → Repo → Settings → Secrets and variables → Actions**.
2. Add the following repository secrets for the Vercel integration:
   - `VERCEL_TOKEN`
   - `VERCEL_ORG_ID`
   - `VERCEL_PROJECT_ID`
3. In Vercel, link the project to the repository root so the provided `vercel.json` builds the `/ui` workspace.

### Fly.io (API)
1. Generate a Fly access token (e.g. `fly auth token`).
2. Store it as a GitHub repository secret named `FLY_API_TOKEN` **or** log in locally and run:
   ```bash
   fly auth token # prints token
   ```
   and then use it with CI or `flyctl`.
3. Backend runtime configuration goes into Fly secrets or GitHub environment variables, for example:
   ```bash
   fly secrets set SUPABASE_URL=... SUPABASE_ANON_KEY=...
   ```

## One-Time Sanity Checklist
- `fly apps list` → confirm `withai-callbot` (and `trifivend-ui` if you manage the UI app).
- `flyctl deploy -c fly.api.toml` to ship the API.
- Confirm Vercel is linked to the repo root so deploying the UI just works.

Need a production-ready Next.js `/ui` skeleton (landing + dashboard with SSE stream, call launcher form, shadcn/ui prewired)? Let me know and I can generate the full codebase.
