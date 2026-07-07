"""
routers/health.py — GET /health

Single endpoint to check the full system status:
model, chat provider, and voice STT availability.
The frontend calls this on load to decide what to show.
"""

import logging

from fastapi import APIRouter

import chat_service
import voice_service
from inference import DISEASE_CLASSES, INPUT_SIZE, MODEL_ARCH, PREPROCESS_MODE, get_model

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health", summary="Full system health check")
def health():
    """
    Returns the status of all major components.

    **model_mode:**
    - `tflite` — real ResNet34 model loaded. Predictions are meaningful.
    - `random`  — no .tflite file found. Demo stub active (predictions are random).
                  Place your model at backend/models/paddy_disease_model.tflite to fix.

    **chat_configured:**
    - True when the LLM API key for the active provider is set.
    - Set LLM_PROVIDER (sambanova/gemini/openai/anthropic) and the matching key.

    **voice_stt.stt_ready:**
    - True when MLX or Bhashini STT is available.
    - See voice_stt.mlx_error for load failure details.
    """
    model = get_model()
    return {
        "status": "ok",
        # Model
        "model_loaded":      model.is_loaded,
        "model_mode":        model.model_mode,       # tflite | random
        "model_arch":        MODEL_ARCH,
        "input_size":        INPUT_SIZE,
        "preprocess":        PREPROCESS_MODE,
        "num_classes":       len(DISEASE_CLASSES),
        "classes":           DISEASE_CLASSES,
        # Chat
        "chat_configured":   chat_service.is_chat_configured(),
        "chat_provider":     chat_service.get_provider(),
        # Voice
        "voice_stt":         voice_service.stt_status(),
    }
