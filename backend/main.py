"""
main.py — Kisan Mitra FastAPI application

Startup order:
  1. Load diseases.json into chat_service memory (for LLM grounding)
  2. Check the DynamoDB tables exist (created by infra/ Terraform)
  3. Load MLX STT model if VOICE_STT_PROVIDER=mlx (async thread)
  4. Mount routers and static frontend

Run locally:
  uvicorn backend.main:app --reload --port 8000

Or use start.sh / docker compose up --build.
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# Load .env so config (API keys, MODEL_PATH, etc.) is present even when this
# file is run directly (e.g. `python backend/main.py` from an IDE) instead of
# via start.sh, which sources .env itself. No-op if .env is missing or
# python-dotenv isn't installed.
try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

import chat_service
import database
import voice_service
from routers import auth, chat, dashboard, diagnose, diseases, health, voice

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR      = Path(__file__).resolve().parent
FRONTEND_DIR  = (BASE_DIR.parent / "frontend").resolve()   # staff dashboard + legal pages
WEB_DIST      = (BASE_DIR.parent / "web" / "dist").resolve()  # farmer app (npm run build)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup tasks — run once before serving requests."""
    logger.info("Starting Kisan Mitra...")

    # 1. Load diseases.json for LLM grounding (raises on missing/corrupt file)
    chat_service.init_knowledge_base()

    # 2. Check DynamoDB (logs a clear error instead of crashing if AWS is unreachable)
    app.state.database_ready = await database.init_db()

    # 3. Load MLX STT model (only on Apple Silicon; no-op otherwise)
    await voice_service.init_stt()
    logger.info("Voice status: %s", voice_service.stt_status())

    yield  # application runs here

    logger.info("Kisan Mitra shutting down.")


app = FastAPI(
    title="Kisan Mitra API",
    description="AI crop advisor for paddy farmers — FastAPI backend",
    version="1.0.0",
    lifespan=lifespan,
)

# Auth uses bearer tokens (no cookies), so credentials are never needed cross-origin.
# The Android app's origin is https://localhost. Restrict with CORS_ORIGINS in production,
# e.g. "https://localhost,https://kisanmitra.example".
CORS_ORIGINS = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- API routers ---
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(diseases.router)
app.include_router(diagnose.router)
app.include_router(chat.router)
app.include_router(voice.router)
app.include_router(dashboard.router)


# --- Serve the farmer app (React build in web/dist) ---
@app.get("/", include_in_schema=False)
def serve_app():
    index = WEB_DIST / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404, detail="App not built. Run `npm install && npm run build`.")
    return FileResponse(index, headers={"Cache-Control": "no-cache"})


@app.get("/logo.svg", include_in_schema=False)
def serve_logo():
    return FileResponse(FRONTEND_DIR / "logo.svg")


# --- Public legal pages (linked from the app and the Play Store listing) ---
@app.get("/privacy", include_in_schema=False)
def serve_privacy():
    return FileResponse(FRONTEND_DIR / "privacy.html")


@app.get("/delete-account", include_in_schema=False)
def serve_delete_account():
    return FileResponse(FRONTEND_DIR / "delete-account.html")


@app.get("/dashboard", include_in_schema=False)
def serve_dashboard_page():
    page = FRONTEND_DIR / "dashboard.html"
    if not page.is_file():
        raise HTTPException(status_code=404, detail="dashboard.html not found.")
    return FileResponse(page)


if (WEB_DIST / "assets").is_dir():
    # Hashed file names: safe to cache for a long time.
    app.mount("/assets", StaticFiles(directory=str(WEB_DIST / "assets")), name="assets")
if FRONTEND_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    # Each worker loads its own copy of the model (~100 MB), so size WEB_CONCURRENCY to the
    # container's memory/CPU. To handle more traffic, add containers rather than workers.
    workers = int(os.environ.get("WEB_CONCURRENCY", "1"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, workers=workers, reload=False,
                proxy_headers=True, forwarded_allow_ips="*", timeout_graceful_shutdown=25)
