"""
routers/health.py — GET /health

Single endpoint to check the full system status:
model, chat provider, and voice STT availability.
The frontend calls this on load to decide what to show.
"""

import logging

from fastapi import APIRouter, Request

import auth_service
import chat_service
import voice_service
from inference import PREPROCESS_MODE, TTA_ENABLED, get_model

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/healthz", include_in_schema=False)
def healthz():
    """Cheap liveness probe for load balancers: no model, DB or provider calls."""
    return {"status": "ok"}


@router.get("/health", summary="Full system health check")
def health(request: Request):
    """
    Returns the status of all major components.

    **model_mode:**
    - `tflite` — real trained model loaded. Predictions are meaningful.
    - `random`  — no .tflite file found. Demo stub active (predictions are random).
                  Place your model(s) in backend/models/ to fix.

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
        "model_arch":        model.arch,
        "ensemble_size":     len(model.members),
        "input_size":        model.input_size,       # (width, height)
        "preprocess":        PREPROCESS_MODE,
        "tta":               TTA_ENABLED,
        "temperature":       model.temperature,
        "num_classes":       len(model.class_names),
        "classes":           model.class_names,
        # Data and login
        "database_ready":    getattr(request.app.state, "database_ready", False),
        "farmer_auth_configured": auth_service.farmer_pool() is not None,
        "staff_auth_configured":  auth_service.admin_pool() is not None,
        # Chat
        "chat_configured":   chat_service.is_chat_configured(),
        "chat_provider":     chat_service.get_provider(),
        # Voice
        "voice_stt":         voice_service.stt_status(),
    }
