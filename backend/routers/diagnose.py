import io
import logging
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

import database
from inference import get_model
from routers.diseases import load_diseases
from schemas import DiagnoseResponse, TreatmentInfo

logger = logging.getLogger(__name__)

router = APIRouter()

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/bmp", "image/gif"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB


@router.post("/diagnose", response_model=DiagnoseResponse)
async def diagnose(
    image: UploadFile = File(...),
    village: Optional[str] = Form(None),
    language: str = Form("hi"),
):
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

    model = get_model()
    try:
        disease_name, confidence = model.predict(img)
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

    model_mode = model.model_mode
    diagnosis_id = await database.insert_diagnosis(
        disease=disease_name,
        confidence=round(confidence, 2),
        model_mode=model_mode,
        language=language,
        village=village,
    )

    return DiagnoseResponse(
        disease=disease_name,
        confidence=round(confidence, 2),
        treatment=TreatmentInfo(**treatment_info),
        diagnosis_id=diagnosis_id,
    )
