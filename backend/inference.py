"""TFLite inference for the Kaggle Paddy Doctor 10-class MobileNetV2 classifier."""

import logging
import os
from typing import Optional, Tuple

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

MODEL_ARCH = "mobilenetv2"

# Kaggle "Paddy Doctor: Paddy Disease Classification" competition dataset —
# 10 classes (9 diseases + normal), Keras folder alphabetical order.
# This matches what Kisan_Mitra_Rice_Disease_Classifier_v2.ipynb actually trains.
DISEASE_CLASSES = [
    "Bacterial Leaf Blight",
    "Bacterial Leaf Streak",
    "Bacterial Panicle Blight",
    "Blast",
    "Brown Spot",
    "Dead Heart",
    "Downy Mildew",
    "Hispa",
    "Normal",
    "Tungro",
]

DEFAULT_MODEL_PATH = os.path.join(
    os.path.dirname(__file__), "models", "paddy_disease_model.tflite"
)
INPUT_SIZE = int(os.environ.get("MODEL_INPUT_SIZE", "224"))
# none = pass raw pixels through (preprocess_input is already baked into the
# model graph — this is correct for the training notebook's model); mobilenet
# = MobileNetV2 preprocess (scale to [-1, 1], only if NOT baked in already);
# resnet = ImageNet ResNet preprocess (BGR + mean subtraction); scale = pixel/255
PREPROCESS_MODE = os.environ.get("MODEL_PREPROCESS", "none").lower()

# Keras ResNet / ResNet34 ImageNet mean subtraction (caffe mode, BGR order)
_RESNET_MEANS_BGR = np.array([103.939, 116.779, 123.68], dtype=np.float32)


class ModelNotLoadedError(Exception):
    """Raised when the TFLite model file is missing or failed to load."""


def _none_preprocess(arr: np.ndarray) -> np.ndarray:
    """No-op — pass raw 0-255 pixel values through unchanged.

    Use this when preprocess_input is already baked into the model graph,
    which is the case for Kisan_Mitra_Rice_Disease_Classifier_v2.ipynb:
    `preprocess_input(x)` is applied as a layer *inside* the Keras
    functional model (before base_model), so it gets traced into the
    exported .tflite graph automatically. Applying it again here would
    double-scale every image and skew every prediction.
    """
    return arr


def _mobilenet_preprocess(arr: np.ndarray) -> np.ndarray:
    """Match tf.keras.applications.mobilenet_v2.preprocess_input (scale to [-1, 1]).

    Only use this if your model does NOT already apply preprocess_input
    internally (e.g. you rescaled outside the model graph before saving).
    """
    return (arr / 127.5) - 1.0


def _resnet_preprocess(arr: np.ndarray) -> np.ndarray:
    """Match tf.keras.applications.resnet50.preprocess_input (caffe mode)."""
    arr = arr[..., ::-1]  # RGB -> BGR
    arr[..., 0] -= _RESNET_MEANS_BGR[0]
    arr[..., 1] -= _RESNET_MEANS_BGR[1]
    arr[..., 2] -= _RESNET_MEANS_BGR[2]
    return arr


def _scale_preprocess(arr: np.ndarray) -> np.ndarray:
    return arr / 255.0


def preprocess_image(arr: np.ndarray) -> np.ndarray:
    if PREPROCESS_MODE == "none":
        return _none_preprocess(arr)
    if PREPROCESS_MODE == "mobilenet":
        return _mobilenet_preprocess(arr)
    if PREPROCESS_MODE == "resnet":
        return _resnet_preprocess(arr)
    if PREPROCESS_MODE == "scale":
        return _scale_preprocess(arr)
    raise ValueError(
        f"Unknown MODEL_PREPROCESS={PREPROCESS_MODE!r}. Use 'none', 'mobilenet', 'resnet', or 'scale'."
    )


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve_model_path(path: str) -> str:
    """
    Resolve MODEL_PATH regardless of the process's working directory.

    .env documents MODEL_PATH as "backend/models/paddy_disease_model.tflite"
    (relative to the project root), but start.sh runs the app from inside
    backend/ (cd backend && python main.py), so a naive relative lookup would
    incorrectly resolve to backend/backend/models/... and silently fall back
    to random predictions. Resolve relative paths against the project root
    instead of CWD. Absolute paths (e.g. Docker's /app/backend/models/...)
    pass through unchanged.
    """
    if os.path.isabs(path):
        return path
    return os.path.join(PROJECT_ROOT, path)


class DiseaseModel:
    def __init__(self, model_path: Optional[str] = None):
        raw_path = model_path or os.environ.get("MODEL_PATH", DEFAULT_MODEL_PATH)
        self.model_path = _resolve_model_path(raw_path)
        self.interpreter = None
        self.input_details = None
        self.output_details = None
        self._load()

    def _load(self) -> None:
        if not os.path.isfile(self.model_path):
            logger.warning(
                "TFLite model not found at %s — using random classification fallback for testing",
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

        output_shape = self.output_details[0]["shape"][-1]
        if output_shape != len(DISEASE_CLASSES):
            logger.warning(
                "Model has %d output classes but app expects %d — verify class order",
                output_shape,
                len(DISEASE_CLASSES),
            )
        logger.info(
            "Loaded %s TFLite model from %s (%dx%d, preprocess=%s)",
            MODEL_ARCH,
            self.model_path,
            INPUT_SIZE,
            INPUT_SIZE,
            PREPROCESS_MODE,
        )

    @property
    def is_loaded(self) -> bool:
        return self.interpreter is not None

    @property
    def model_mode(self) -> str:
        return "tflite" if self.is_loaded else "random"

    def _random_predict(self, img: Image.Image) -> Tuple[str, float]:
        """Temporary testing fallback when no .tflite model is available."""
        arr = np.array(img.convert("RGB"), dtype=np.uint8)
        seed = int(np.sum(arr, dtype=np.uint64) % (2**32 - 1))
        rng = np.random.default_rng(seed)
        confidences = rng.random(len(DISEASE_CLASSES))
        confidences /= confidences.sum()
        idx = int(np.argmax(confidences))
        return DISEASE_CLASSES[idx], float(confidences[idx]) * 100

    def _preprocess(self, img: Image.Image) -> np.ndarray:
        """Resize and normalize to match the model's training pipeline (default 224×224 MobileNetV2)."""
        img = img.convert("RGB").resize((INPUT_SIZE, INPUT_SIZE), Image.Resampling.BILINEAR)
        arr = np.array(img, dtype=np.float32)
        arr = preprocess_image(arr)
        return np.expand_dims(arr, axis=0)

    def predict(self, img: Image.Image) -> Tuple[str, float]:
        if not self.is_loaded:
            return self._random_predict(img)

        input_data = self._preprocess(img)
        self.interpreter.set_tensor(self.input_details[0]["index"], input_data)
        self.interpreter.invoke()
        output = self.interpreter.get_tensor(self.output_details[0]["index"])[0]

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
