"""
routers/health.py — GET /health

Shows model status (tflite vs random stub) and chat configuration.
The frontend calls this on load to decide what to show.
"""

import logging
from fastapi import APIRouter

import chat_service
from inference import DISEASE_CLASSES, INPUT_SIZE, MODEL_ARCH, PREPROCESS_MODE, get_model

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health", summary="System health check")
def health():
    """
    model_mode:
      tflite  — real rice_disease_model.tflite loaded, predictions are real
      random  — model file not found, using random fallback (development only)

    chat_configured:
      true  — SAMBANOVA_API_KEY (or other provider key) is set, chat works
      false — no key set, /chat will return 503
    """
    model = get_model()
    return {
        "status":           "ok",
        "model_loaded":     model.is_loaded,
        "model_mode":       model.model_mode,
        "model_arch":       MODEL_ARCH,
        "input_size":       INPUT_SIZE,
        "preprocess":       PREPROCESS_MODE,
        "num_classes":      len(DISEASE_CLASSES),
        "chat_configured":  chat_service.is_chat_configured(),
        "chat_provider":    chat_service.get_provider(),
        "chat_model":       chat_service.DEFAULT_MODELS.get(chat_service.get_provider(), "unknown"),
    }
