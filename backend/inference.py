"""TFLite inference for Paddy Doctor 13-class ResNet34 classifier."""

import logging
import os
from typing import Optional, Tuple

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

MODEL_ARCH = "resnet34"

# Paddy Doctor dataset class order (paper Table 1 / Keras folder alphabetical order)
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

DEFAULT_MODEL_PATH = os.path.join(
    os.path.dirname(__file__), "models", "paddy_disease_model.tflite"
)
INPUT_SIZE = int(os.environ.get("MODEL_INPUT_SIZE", "256"))
# resnet = ImageNet ResNet preprocess (BGR + mean subtraction); scale = pixel/255
PREPROCESS_MODE = os.environ.get("MODEL_PREPROCESS", "resnet").lower()

# Keras ResNet / ResNet34 ImageNet mean subtraction (caffe mode, BGR order)
_RESNET_MEANS_BGR = np.array([103.939, 116.779, 123.68], dtype=np.float32)


class ModelNotLoadedError(Exception):
    """Raised when the TFLite model file is missing or failed to load."""


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
    if PREPROCESS_MODE == "resnet":
        return _resnet_preprocess(arr)
    if PREPROCESS_MODE == "scale":
        return _scale_preprocess(arr)
    raise ValueError(
        f"Unknown MODEL_PREPROCESS={PREPROCESS_MODE!r}. Use 'resnet' or 'scale'."
    )


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
            "Loaded ResNet34 TFLite model from %s (%dx%d, preprocess=%s)",
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
        """Resize and normalize for Paddy Doctor ResNet34 training (256×256)."""
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
