# Deploying the Kisan Mitra backend (Railway)

This deploys `backend/` + `frontend/` using the existing `Dockerfile`. `railway.json`
already tells Railway to build with that Dockerfile and health-check `/health`.

## Why Railway

You already have a working `Dockerfile` — Railway builds directly from it with
almost no extra setup, gives you a free HTTPS domain (the mobile app requires
HTTPS), and supports a persistent volume for the SQLite database on the Hobby
plan (~$5/month once you're past the free trial).

## Important: MLX voice will NOT work here

`mlx_stt_service.py` only runs on Apple Silicon (`platform.system() == "Darwin"`).
Railway's containers are Linux. In production, voice falls back to whatever
`VOICE_STT_PROVIDER` you configure — set it to `bhashini` (with real
`BHASHINI_USER_ID` / `BHASHINI_API_KEY`) or leave STT unconfigured and let the
frontend fall back to the browser's Web Speech API. Diagnosis and text chat are
unaffected — those don't depend on the host OS.

## Steps

1. **Push this repo to GitHub** (if not already) — Railway deploys from a GitHub repo.
2. **Create a new Railway project** → Deploy from GitHub repo → select this repo.
   Railway will detect the `Dockerfile` and `railway.json` automatically.
3. **Add a persistent volume** (Railway dashboard → your service → Volumes):
   - Mount path: `/app/data`
   - This is where the SQLite database lives. Without this, every redeploy
     wipes all diagnosis history, chat logs, and feedback.
4. **Set environment variables** (Railway dashboard → Variables). Copy every key
   from `.env.example`, filling in real values:
   - `LLM_PROVIDER=sambanova`, `SAMBANOVA_API_KEY=<rotate this — see note below>`,
     `SAMBANOVA_MODEL=Meta-Llama-3.3-70B-Instruct`
   - `DB_PATH=/app/data/kisan_mitra.db` — must match the volume mount path above
   - `MODEL_PATH=/app/backend/models/paddy_disease_model.tflite` (already the
     Dockerfile default — only set this if you want to override it)
   - `MODEL_INPUT_SIZE=224`, `MODEL_PREPROCESS=none`
   - `VOICE_STT_PROVIDER=bhashini` (or omit — see MLX note above)
   - `BHASHINI_USER_ID`, `BHASHINI_API_KEY`, `BHASHINI_PIPELINE_ID` if using Bhashini
   - `DASHBOARD_PASSWORD=<pick something that isn't kisan123>`
5. **Deploy.** Railway builds the Dockerfile and starts the container. Check
   the `/health` endpoint on your Railway-assigned domain once it's live.
6. **Point the mobile app at it** — edit `capacitor.config.json`:
   ```json
   "server": { "url": "https://your-app.up.railway.app" }
   ```
   Drop `"cleartext": true` entirely once you're on `https`. Then `npm run sync`.

## Before you deploy — rotate the SambaNova key

The `SAMBANOVA_API_KEY` currently in `.env` was committed to this repo's git
history earlier (before `.gitignore` excluded `.env`). Anyone with repo access
can read old commits and get that key. Generate a new one in your SambaNova
dashboard before going live, and only put the new key in Railway's environment
variables — never back in a committed file.
