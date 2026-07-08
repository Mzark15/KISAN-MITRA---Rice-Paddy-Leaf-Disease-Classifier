"""
routers/health.py — GET /health
"""

import logging
from fastapi import APIRouter
import chat_service
from inference import DISEASE_CLASSES, INPUT_SIZE, MODEL_ARCH, get_model

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health")
def health():
    model = get_model()
    return {
        "status":          "ok",
        "model_loaded":    model.is_loaded,
        "model_arch":      MODEL_ARCH,
        "input_size":      INPUT_SIZE,
        "num_classes":     len(DISEASE_CLASSES),
        "chat_configured": chat_service.is_chat_configured(),
        "chat_provider":   chat_service.get_provider(),
        "chat_model":      chat_service.DEFAULT_MODELS.get(chat_service.get_provider()),
    }
