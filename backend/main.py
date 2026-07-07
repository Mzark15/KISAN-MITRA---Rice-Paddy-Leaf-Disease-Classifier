import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import chat_service
import database
import voice_service
from routers import chat, dashboard, diagnose, diseases, health, voice

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = (BASE_DIR.parent / "frontend").resolve()


@asynccontextmanager
async def lifespan(app: FastAPI):
    chat_service.init_knowledge_base()
    await database.init_db()
    await voice_service.init_stt()
    logger.info("Database initialized at %s", database.DB_PATH)
    logger.info("Voice STT status: %s", voice_service.stt_status())
    yield


app = FastAPI(title="Kisan Mitra - AI Crop Advisor", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(diseases.router)
app.include_router(diagnose.router)
app.include_router(chat.router)
app.include_router(voice.router)
app.include_router(dashboard.router)


@app.get("/")
def serve_frontend():
    index = FRONTEND_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404, detail="Frontend not found.")
    return FileResponse(index)


@app.get("/dashboard")
def serve_dashboard():
    dashboard_file = FRONTEND_DIR / "dashboard.html"
    if not dashboard_file.is_file():
        raise HTTPException(status_code=404, detail="Dashboard not found.")
    return FileResponse(dashboard_file)


if FRONTEND_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
