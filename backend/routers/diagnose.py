"""
routers/diagnose.py — POST /diagnose

Accepts a rice leaf photo, runs the TFLite classifier (or random stub in dev),
looks up the vetted treatment from diseases.json, logs to SQLite, and returns
a structured result with confidence, treatment, and a KVK referral flag.

Confidence threshold: CONFIDENCE_THRESHOLD env var if set, otherwise the
recommended_threshold from model_meta.json (v3 notebook), otherwise 60.0.
"""

import asyncio
import io
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError

import database
from auth_service import Farmer
from ratelimit import limit_farmer
from inference import DiseaseModel, get_gate, get_model
from routers.diseases import load_diseases
from schemas import DiagnoseResponse, PredictionScore, TreatmentInfo

logger = logging.getLogger(__name__)
router = APIRouter()

# Allowed image MIME types
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/bmp", "image/gif"}

# Maximum upload size (bytes)
MAX_IMAGE_BYTES = int(os.environ.get("MAX_IMAGE_SIZE_MB", "10")) * 1024 * 1024

# Minimum confidence to treat the prediction as reliable. Below this, the model's
# top guess is still shown (not hidden) but flagged as unverified via safe_to_act
# and low_confidence_message — see the confidence gate below.
# Override: set CONFIDENCE_THRESHOLD env var (e.g. CONFIDENCE_THRESHOLD=70)
DEFAULT_CONFIDENCE_THRESHOLD = 60.0


def _confidence_threshold(model: DiseaseModel) -> float:
    """Env var wins; then the threshold calibrated in model_meta.json; then 60%."""
    env_value = os.environ.get("CONFIDENCE_THRESHOLD")
    if env_value:
        return float(env_value)
    if model.recommended_threshold is not None:
        return float(model.recommended_threshold)
    return DEFAULT_CONFIDENCE_THRESHOLD


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
    farmer: Farmer = Depends(limit_farmer("diagnose")),
):
    """
    Upload a rice leaf photo → get disease name, confidence, and vetted treatment advice.

    **Confidence threshold** (default 60%):
    - Above threshold → returns the predicted disease and treatment, `safe_to_act=True`.
    - Below threshold → still returns the model's actual top prediction and treatment,
      but with `safe_to_act=False` and `low_confidence_message` set. Treat this as an
      unverified hint, not a confirmed diagnosis — the frontend must keep the warning
      visible whenever `safe_to_act` is False.

    **Crop gate**: before the disease model runs, a separate gate checks the photo really is
    a rice leaf. Anything else (people, objects, other plants, blank frames) is rejected
    with HTTP 422 and no diagnosis is stored. See `scripts/train_crop_gate.py`.

    **model_mode** in the response:
    - `tflite` — real trained model loaded, predictions are meaningful.
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
    # Runs in a worker thread: an ensemble with TTA takes a few seconds on CPU and
    # would otherwise block every other request on the event loop.
    model: DiseaseModel = get_model()

    # --- Crop gate: reject photos that aren't a rice leaf before predicting any disease ---
    gate = get_gate()
    try:
        is_leaf, leaf_p = await asyncio.to_thread(gate.is_rice_leaf, img)
    except Exception as exc:
        logger.exception("Crop gate error")
        raise HTTPException(status_code=500, detail=f"Inference error: {exc}") from exc
    if not is_leaf:
        logger.info("Rejected non-rice image (leaf probability %.3f < %.3f)", leaf_p, gate.threshold)
        raise HTTPException(
            status_code=422,
            detail=(
                "This doesn't look like a rice leaf. Take a close, well-lit photo of a single "
                "rice leaf (fill the frame with the leaf) and try again."
            ),
        )

    try:
        top = await asyncio.to_thread(model.predict_top, img, 3)
    except Exception as exc:
        logger.exception("Unexpected inference error")
        raise HTTPException(status_code=500, detail=f"Inference error: {exc}") from exc
    disease_name, confidence = top[0]

    # --- Confidence gate ---
    # Below threshold, we don't hide the model's guess — we still show it (and its
    # treatment info) so the farmer isn't left with nothing, but safe_to_act=False
    # and low_confidence_message flag it clearly as unverified. The frontend must
    # keep showing that warning prominently whenever safe_to_act is False; treat
    # the accompanying treatment/disease name as a hint, not a confirmed diagnosis.
    safe_to_act = confidence >= _confidence_threshold(model)
    low_confidence_message: Optional[str] = None
    if not safe_to_act:
        if disease_name == "Normal":
            # Never tell a farmer the crop is healthy on a low-confidence guess.
            low_confidence_message = (
                f"Low confidence ({confidence:.1f}%) — the photo is unclear, so we cannot "
                "confirm the plant is healthy. Take a closer, well-lit photo of the leaf "
                "and try again, or consult your KVK."
            )
        else:
            low_confidence_message = (
                f"Low confidence ({confidence:.1f}%) — this is the model's best guess, not a "
                "confirmed diagnosis. Take a closer, well-lit photo of the affected leaf and "
                "try again, or consult your KVK before acting on this."
            )

    # --- Fetch vetted treatment ---
    treatment = _get_treatment(disease_name)

    # --- Log to database ---
    # Logging must never block the diagnosis: with no database (e.g. a laptop test backend)
    # the farmer still gets the result, just without a feedback id.
    try:
        diagnosis_id = await database.insert_diagnosis(
            user_id=farmer.user_id,
            disease=disease_name,
            confidence=round(confidence, 2),
            model_mode=model.model_mode,
            language=language,
            village=village or None,
        )
    except Exception as exc:
        logger.error("Could not store diagnosis, returning result anyway: %s", exc)
        diagnosis_id = ""

    return DiagnoseResponse(
        disease=disease_name,
        confidence=round(confidence, 2),
        treatment=treatment,
        diagnosis_id=diagnosis_id,
        model_mode=model.model_mode,
        safe_to_act=safe_to_act,
        low_confidence_message=low_confidence_message,
        top_predictions=[
            PredictionScore(disease=name, confidence=round(conf, 2)) for name, conf in top
        ],
    )
