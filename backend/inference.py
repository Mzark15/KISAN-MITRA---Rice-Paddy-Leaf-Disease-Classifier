"""
inference.py — TFLite classifier for rice disease detection

Model: ResNet34 trained on Paddy Doctor dataset (13 classes)
Place model at: backend/models/rice_disease_model.tflite

If model file is missing, the server starts but /diagnose returns HTTP 503.
"""

import logging
import os
from typing import Optional, Tuple

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# 13 Paddy Doctor classes — must match the order your model was trained with
DISEASE_CLASSES = [
    "Bacterial Leaf Blight",
    "Bacterial Leaf Streak",
    "Bacterial Panicle Blight",
    "Black Stem Borer",
    "Blast",
    "Brown Spot",
    "Downy Mildew",
    "Hispa",
    "Leaf Roller",
    "Tungro",
    "White Stem Borer",
    "Yellow Stem Borer",
    "Normal",
]

MODEL_ARCH   = "resnet34"
INPUT_SIZE   = int(os.environ.get("MODEL_INPUT_SIZE", "256"))
PREPROCESS_MODE = os.environ.get("MODEL_PREPROCESS", "resnet").lower()

DEFAULT_MODEL_PATH = os.path.join(
    os.path.dirname(__file__), "models", "rice_disease_model.tflite"
)

# ResNet ImageNet mean subtraction (caffe mode, BGR)
_RESNET_MEANS_BGR = np.array([103.939, 116.779, 123.68], dtype=np.float32)


class ModelNotLoadedError(Exception):
    """Model file not found or failed to load."""


def _preprocess(img: Image.Image) -> np.ndarray:
    img = img.convert("RGB").resize((INPUT_SIZE, INPUT_SIZE), Image.Resampling.BILINEAR)
    arr = np.array(img, dtype=np.float32)
    if PREPROCESS_MODE == "resnet":
        arr = arr[..., ::-1]  # RGB → BGR
        arr -= _RESNET_MEANS_BGR
    else:
        arr /= 255.0
    return np.expand_dims(arr, axis=0)


class DiseaseModel:
    def __init__(self):
        self.interpreter   = None
        self.input_details = None
        self.output_details = None
        self._load()

    def _load(self) -> None:
        model_path = os.environ.get("MODEL_PATH", DEFAULT_MODEL_PATH)

        if not os.path.isfile(model_path):
            logger.error("Model file not found: %s", model_path)
            return   # is_loaded will be False; /diagnose will return 503

        try:
            import tflite_runtime.interpreter as tflite
        except ImportError:
            try:
                import tensorflow.lite as tflite  # type: ignore
            except ImportError:
                logger.error("Install tflite-runtime or tensorflow to run the model.")
                return

        self.interpreter = tflite.Interpreter(model_path=model_path)
        self.interpreter.allocate_tensors()
        self.input_details  = self.interpreter.get_input_details()
        self.output_details = self.interpreter.get_output_details()
        logger.info("Model loaded: %s (%d classes, %dx%d)",
                    model_path, len(DISEASE_CLASSES), INPUT_SIZE, INPUT_SIZE)

    @property
    def is_loaded(self) -> bool:
        return self.interpreter is not None

    def predict(self, img: Image.Image) -> Tuple[str, float]:
        """
        Run inference on a PIL image.
        Returns (disease_name, confidence_percent).
        Raises ModelNotLoadedError if model file was not found.
        """
        if not self.is_loaded:
            raise ModelNotLoadedError(
                "rice_disease_model.tflite not found in backend/models/. "
                "Place the trained model file there and restart the server."
            )

        data = _preprocess(img)
        self.interpreter.set_tensor(self.input_details[0]["index"], data)
        self.interpreter.invoke()
        output = self.interpreter.get_tensor(self.output_details[0]["index"])[0]

        # Softmax if model outputs logits instead of probabilities
        if output.min() < 0 or abs(output.sum() - 1.0) > 0.1:
            exp    = np.exp(output - np.max(output))
            output = exp / exp.sum()

        idx = int(np.argmax(output))
        if idx >= len(DISEASE_CLASSES):
            raise ValueError(
                f"Model output index {idx} out of range "
                f"(expected < {len(DISEASE_CLASSES)}). "
                "Check that DISEASE_CLASSES matches your training class order."
            )

        return DISEASE_CLASSES[idx], float(output[idx]) * 100


_model: Optional[DiseaseModel] = None


def get_model() -> DiseaseModel:
    global _model
    if _model is None:
        _model = DiseaseModel()
    return _model
