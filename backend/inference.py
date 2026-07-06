"""TFLite model inference for paddy disease classification."""

import logging
import os
from typing import Optional, Tuple

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

DISEASE_CLASSES = [
    "Leaf Blast",
    "Bacterial Leaf Blight",
    "Brown Spot",
    "Tungro",
    "Sheath Blight",
    "Healthy",
]

DEFAULT_MODEL_PATH = os.path.join(
    os.path.dirname(__file__), "models", "paddy_disease_model.tflite"
)
INPUT_SIZE = int(os.environ.get("MODEL_INPUT_SIZE", "224"))


class ModelNotLoadedError(Exception):
    """Raised when the TFLite model file is missing or failed to load."""


class DiseaseModel:
    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path or os.environ.get("MODEL_PATH", DEFAULT_MODEL_PATH)
        self.interpreter = None
        self.input_details = None
        self.output_details = None
        self._load()

    def _load(self) -> None:
        if not os.path.isfile(self.model_path):
            logger.warning(
                "TFLite model not found at %s — /diagnose will return 503 until model is placed",
                self.model_path,
            )
            return

        try:
            import tflite_runtime.interpreter as tflite
        except ImportError:
            try:
                import tensorflow.lite as tflite  # type: ignore
            except ImportError as exc:
                raise ModelNotLoadedError(
                    "Neither tflite-runtime nor tensorflow is installed"
                ) from exc

        self.interpreter = tflite.Interpreter(model_path=self.model_path)
        self.interpreter.allocate_tensors()
        self.input_details = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()
        logger.info("Loaded TFLite model from %s", self.model_path)

    @property
    def is_loaded(self) -> bool:
        return self.interpreter is not None

    def _preprocess(self, img: Image.Image) -> np.ndarray:
        """Resize and normalize image for MobileNetV2-style input."""
        img = img.convert("RGB").resize((INPUT_SIZE, INPUT_SIZE), Image.Resampling.BILINEAR)
        arr = np.array(img, dtype=np.float32)

        # MobileNetV2 expects pixels in [-1, 1]
        arr = (arr / 127.5) - 1.0
        return np.expand_dims(arr, axis=0)

    def predict(self, img: Image.Image) -> Tuple[str, float]:
        if not self.is_loaded:
            raise ModelNotLoadedError(
                f"Model file not found at {self.model_path}. "
                "Place your trained .tflite file there or set MODEL_PATH."
            )

        input_data = self._preprocess(img)
        self.interpreter.set_tensor(self.input_details[0]["index"], input_data)
        self.interpreter.invoke()
        output = self.interpreter.get_tensor(self.output_details[0]["index"])[0]

        # Softmax if logits
        if output.min() < 0 or abs(output.sum() - 1.0) > 0.1:
            exp = np.exp(output - np.max(output))
            output = exp / exp.sum()

        idx = int(np.argmax(output))
        if idx >= len(DISEASE_CLASSES):
            raise ValueError(
                f"Model output index {idx} exceeds {len(DISEASE_CLASSES)} classes"
            )

        confidence = float(output[idx]) * 100
        return DISEASE_CLASSES[idx], confidence


_model: Optional[DiseaseModel] = None


def get_model() -> DiseaseModel:
    global _model
    if _model is None:
        _model = DiseaseModel()
    return _model
