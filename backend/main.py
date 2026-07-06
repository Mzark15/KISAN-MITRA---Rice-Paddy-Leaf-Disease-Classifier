import io
import json
import logging
import os
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError

from inference import DISEASE_CLASSES, ModelNotLoadedError, get_model

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Kisan Mitra - Disease Detection API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
DISEASES_FILE = BASE_DIR / "diseases.json"
FRONTEND_DIR = (BASE_DIR.parent / "frontend").resolve()
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/bmp", "image/gif"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB


def load_diseases() -> dict:
    with open(DISEASES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


@app.get("/health")
def health():
    model = get_model()
    return {
        "status": "ok",
        "model_loaded": model.is_loaded,
        "classes": DISEASE_CLASSES,
    }


@app.get("/diseases")
def get_diseases():
    return load_diseases()


@app.post("/diagnose")
async def diagnose(image: UploadFile = File(...)):
    if not image.content_type or image.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type: {image.content_type}. Upload a JPEG, PNG, or WebP image.",
        )

    contents = await image.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Empty file uploaded.")
    if len(contents) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=400, detail="Image too large (max 10 MB).")

    try:
        img = Image.open(io.BytesIO(contents))
        img.verify()
        img = Image.open(io.BytesIO(contents))
        img.load()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid or corrupt image: {exc}",
        ) from exc

    try:
        disease_name, confidence = get_model().predict(img)
    except ModelNotLoadedError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Inference failed")
        raise HTTPException(status_code=500, detail=f"Inference error: {exc}") from exc

    diseases = load_diseases()
    treatment_info = diseases.get(disease_name)
    if treatment_info is None:
        raise HTTPException(
            status_code=500,
            detail=f"No treatment data for predicted class: {disease_name}",
        )

    return {
        "disease": disease_name,
        "confidence": round(confidence, 2),
        "treatment": treatment_info,
    }


@app.get("/")
def serve_frontend():
    index = FRONTEND_DIR / "index.html"
    if not index.is_file():
        raise HTTPException(status_code=404, detail="Frontend not found.")
    return FileResponse(index)


if FRONTEND_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
