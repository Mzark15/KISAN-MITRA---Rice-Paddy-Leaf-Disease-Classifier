"""
routers/diagnose.py — POST /diagnose

Upload a rice leaf photo → classifier → disease name + treatment.

Returns 503 if model file is missing.
Returns 400 for invalid images.
"""

import io
import logging
import os
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

import database
from inference import ModelNotLoadedError, get_model
from routers.diseases import load_diseases
from schemas import DiagnoseResponse, TreatmentInfo

logger = logging.getLogger(__name__)
router = APIRouter()

ALLOWED_TYPES  = {"image/jpeg", "image/png", "image/webp", "image/bmp", "image/gif"}
MAX_BYTES      = int(os.environ.get("MAX_IMAGE_SIZE_MB", "10")) * 1024 * 1024


def _open_image(data: bytes) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        return Image.open(io.BytesIO(data))
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid image: {exc}") from exc


def _get_treatment(disease: str) -> TreatmentInfo:
    entry = load_diseases().get(disease)
    if entry is None:
        raise HTTPException(
            status_code=500,
            detail=f"No treatment data for '{disease}'. Add it to diseases.json."
        )
    return TreatmentInfo(**entry)


@router.post("/diagnose", response_model=DiagnoseResponse)
async def diagnose(
    image:    UploadFile       = File(...),
    village:  Optional[str]    = Form(None),
    language: str              = Form("hi"),
):
    # Validate type
    if image.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{image.content_type}'. Use JPEG or PNG."
        )

    # Read + size check
    data = await image.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 10 MB).")

    # Decode
    img = _open_image(data)

    # Run classifier
    try:
        disease, confidence = get_model().predict(img)
    except ModelNotLoadedError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Inference error")
        raise HTTPException(status_code=500, detail=f"Inference error: {exc}") from exc

    # Fetch treatment
    treatment = _get_treatment(disease)

    # Log to DB
    diagnosis_id = await database.insert_diagnosis(
        disease=disease,
        confidence=round(confidence, 2),
        model_mode="tflite",
        language=language,
        village=village or None,
    )

    return DiagnoseResponse(
        disease=disease,
        confidence=round(confidence, 2),
        treatment=treatment,
        diagnosis_id=diagnosis_id,
    )
