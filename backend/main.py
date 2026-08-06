"""
main.py — Kisan Mitra FastAPI application

Startup order:
  1. Load diseases.json into chat_service memory (for LLM grounding)
  2. Initialise SQLite database (creates tables if missing)
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
from routers import chat, dashboard, diagnose, diseases, health, voice

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR      = Path(__file__).resolve().parent
FRONTEND_DIR  = (BASE_DIR.parent / "frontend").resolve()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup tasks — run once before serving requests."""
    logger.info("Starting Kisan Mitra...")

    # 1. Load diseases.json for LLM grounding (raises on missing/corrupt file)
    chat_service.init_knowledge_base()

    # 2. Init SQLite (creates data/ dir and tables if needed)
    await database.init_db()
    logger.info("Database ready: %s", database.DB_PATH)

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

# Allow all origins in development. In production, restrict to your domain.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- API routers ---
app.include_router(health.router)
app.include_router(diseases.router)
app.include_router(diagnose.router)
app.include_router(chat.router)
app.include_router(voice.router)
app.include_router(dashboard.router)


# --- Serve frontend ---
@app.get("/", include_in_schema=False)
def serve_frontend():
    index = FRONTEND_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404, detail="Frontend not built. Run from project root.")
    return FileResponse(index)


@app.get("/dashboard", include_in_schema=False)
def serve_dashboard_page():
    page = FRONTEND_DIR / "dashboard.html"
    if not page.is_file():
        raise HTTPException(status_code=404, detail="dashboard.html not found.")
    return FileResponse(page)


if FRONTEND_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=False)
