"""
main.py — Kisan Mitra FastAPI application

Two features only:
  1. POST /diagnose  — upload rice leaf image → TFLite classifier → disease + treatment
  2. POST /chat      — text chat via LangGraph + SambaNova LLM, grounded in diseases.json

Startup order:
  1. Load .env (python-dotenv)
  2. Load diseases.json into chat_service
  3. Initialise SQLite database
  4. Mount routers and serve frontend
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

# Load .env automatically — no need to export vars manually before starting
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass  # install python-dotenv if you need auto .env loading

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import chat_service
import database
from routers import chat, dashboard, diagnose, diseases, health

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR     = Path(__file__).resolve().parent
FRONTEND_DIR = (BASE_DIR.parent / "frontend").resolve()


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Kisan Mitra...")
    chat_service.init_knowledge_base()
    await database.init_db()
    logger.info("Database ready: %s", database.DB_PATH)
    yield
    logger.info("Kisan Mitra shutting down.")


app = FastAPI(
    title="Kisan Mitra API",
    description="Paddy disease classifier + LangGraph chat advisor",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Active routers — image diagnosis + text chat only
app.include_router(health.router)
app.include_router(diseases.router)
app.include_router(diagnose.router)
app.include_router(chat.router)
app.include_router(dashboard.router)


@app.get("/", include_in_schema=False)
def serve_frontend():
    index = FRONTEND_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404, detail="Frontend not found.")
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
