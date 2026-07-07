from fastapi import APIRouter

import voice_service
from inference import (
    DISEASE_CLASSES,
    INPUT_SIZE,
    MODEL_ARCH,
    PREPROCESS_MODE,
    get_model,
)

router = APIRouter()


@router.get("/health")
def health():
    model = get_model()
    return {
        "status": "ok",
        "model_loaded": model.is_loaded,
        "model_mode": model.model_mode,
        "model_arch": MODEL_ARCH,
        "input_size": INPUT_SIZE,
        "preprocess": PREPROCESS_MODE,
        "num_classes": len(DISEASE_CLASSES),
        "classes": DISEASE_CLASSES,
        "voice_stt": voice_service.stt_status(),
    }
