"""
routers/diagnose.py — POST /diagnose

Accepts a rice leaf photo, runs the TFLite classifier (or random stub in dev),
looks up the vetted treatment from diseases.json, logs to SQLite, and returns
a structured result with confidence, treatment, and a KVK referral flag.

To change the confidence threshold: set CONFIDENCE_THRESHOLD env var (default 60.0).
"""

import io
import logging
import os
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

import database
from inference import DiseaseModel, get_model
from routers.diseases import load_diseases
from schemas import DiagnoseResponse, TreatmentInfo

logger = logging.getLogger(__name__)
router = APIRouter()

# Allowed image MIME types
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/bmp", "image/gif"}

# Maximum upload size (bytes)
MAX_IMAGE_BYTES = int(os.environ.get("MAX_IMAGE_SIZE_MB", "10")) * 1024 * 1024

# Minimum confidence to trust the prediction. Below this we fall back to "Normal"
# and ask the farmer for a clearer photo.
# Override: set CONFIDENCE_THRESHOLD env var (e.g. CONFIDENCE_THRESHOLD=70)
CONFIDENCE_THRESHOLD = float(os.environ.get("CONFIDENCE_THRESHOLD", "60.0"))


def _open_image(contents: bytes) -> Image.Image:
    """Open and validate an image from raw bytes. Raises HTTPException on invalid input."""
    try:
        img = Image.open(io.BytesIO(contents))
        img.verify()                     # catches truncated files
        img = Image.open(io.BytesIO(contents))  # reopen after verify (verify closes the file)
        img.load()                       # force full decode
        return img
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid or corrupt image: {exc}") from exc


def _get_treatment(disease_name: str) -> TreatmentInfo:
    """Fetch vetted treatment data for a disease. Raises HTTPException 500 if disease not in KB."""
    diseases = load_diseases()
    data = diseases.get(disease_name)
    if data is None:
        # This means inference.py predicted a class not in diseases.json.
        # Fix: add the missing class to diseases.json.
        logger.error(
            "Predicted class '%s' not found in diseases.json. "
            "Add it to backend/diseases.json to fix this.",
            disease_name,
        )
        raise HTTPException(
            status_code=500,
            detail=(
                f"No treatment data for predicted class '{disease_name}'. "
                "This is a configuration error — contact the system administrator."
            ),
        )
    return TreatmentInfo(**data)


@router.post("/diagnose", response_model=DiagnoseResponse, summary="Diagnose a paddy leaf image")
async def diagnose(
    image: UploadFile = File(..., description="JPEG / PNG / WebP rice leaf photo"),
    village: Optional[str] = Form(None, description="Farmer's village (optional, stored for pilot tracking)"),
    language: str = Form("hi", description="Farmer's language code: hi / mr / en"),
):
    """
    Upload a rice leaf photo → get disease name, confidence, and vetted treatment advice.

    **Confidence threshold** (default 60%):
    - Above threshold → returns the predicted disease and treatment.
    - Below threshold → returns `safe_to_act=False` with a message asking for a clearer photo.
      Disease defaults to 'Normal' so no harmful advice is given.

    **model_mode** in the response:
    - `tflite` — real ResNet34 model, predictions are meaningful.
    - `random` — demo stub (no .tflite file found), predictions are random. For development only.
    """
    # --- Validate content type ---
    if not image.content_type or image.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type '{image.content_type}'. "
                f"Please upload a JPEG, PNG, or WebP image."
            ),
        )

    # --- Read and size-check ---
    contents = await image.read()
    if not contents:
        raise HTTPException(status_code=400, detail="Empty file uploaded.")
    if len(contents) > MAX_IMAGE_BYTES:
        max_mb = MAX_IMAGE_BYTES // (1024 * 1024)
        raise HTTPException(status_code=413, detail=f"Image too large. Maximum size is {max_mb} MB.")

    # --- Decode image ---
    img = _open_image(contents)

    # --- Run inference ---
    model: DiseaseModel = get_model()
    try:
        disease_name, confidence = model.predict(img)
    except ValueError as exc:
        # Model output index out of range — class count mismatch between model and code
        logger.error("Inference class mismatch: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Model output does not match expected classes. Check MODEL_PATH and class list.",
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected inference error")
        raise HTTPException(status_code=500, detail=f"Inference error: {exc}") from exc

    # --- Confidence gate ---
    # If confidence is too low, don't guess — ask for a clearer photo instead.
    safe_to_act = confidence >= CONFIDENCE_THRESHOLD
    low_confidence_message: Optional[str] = None
    if not safe_to_act:
        low_confidence_message = (
            f"Photo unclear ({confidence:.1f}% confidence). "
            "Please take a closer, well-lit photo of the affected leaf and try again."
        )
        disease_name = "Normal"  # safe default — no harmful advice given when uncertain

    # --- Fetch vetted treatment ---
    treatment = _get_treatment(disease_name)

    # --- Log to database (non-blocking) ---
    diagnosis_id = await database.insert_diagnosis(
        disease=disease_name,
        confidence=round(confidence, 2),
        model_mode=model.model_mode,
        language=language,
        village=village or None,
    )

    return DiagnoseResponse(
        disease=disease_name,
        confidence=round(confidence, 2),
        treatment=treatment,
        diagnosis_id=diagnosis_id,
        model_mode=model.model_mode,
        safe_to_act=safe_to_act,
        low_confidence_message=low_confidence_message,
    )
