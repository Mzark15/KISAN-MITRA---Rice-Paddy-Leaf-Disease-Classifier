"""TFLite inference for the Kaggle Paddy Doctor 10-class classifier.

Supports two layouts under MODEL_PATH:

- A single .tflite file (e.g. the v2 MobileNetV2 export).
- A directory. If it contains model_meta.json (written by
  Kisan_Mitra_Rice_Disease_Classifier_v3.ipynb), the models it lists are loaded
  as an ensemble and its class order, temperature and recommended confidence
  threshold are used. Without model_meta.json, every *.tflite in the directory
  is loaded.

Each prediction averages the softmax output of every model over the original
image and its horizontal flip (test-time augmentation, MODEL_TTA=1), then
applies temperature scaling so the confidence is calibrated.
"""

import json
import logging
import os
import threading
from typing import Optional

import numpy as np
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

# Kaggle "Paddy Doctor: Paddy Disease Classification" competition dataset —
# 10 classes (9 diseases + normal), Keras folder alphabetical order.
# model_meta.json can override this (it must use the same names as diseases.json).
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

MODELS_DIR = os.path.join(os.path.dirname(__file__), "models")
META_FILENAME = "model_meta.json"

# Only used when the model has a dynamic (-1) input shape; otherwise the
# height/width are read from the .tflite file itself.
INPUT_SIZE = int(os.environ.get("MODEL_INPUT_SIZE", "224"))
# none = pass raw pixels through (preprocessing is baked into the model graph —
# true for both the v2 and v3 notebooks); mobilenet = scale to [-1, 1];
# resnet = ImageNet caffe mode (BGR + mean subtraction); scale = pixel/255
PREPROCESS_MODE = os.environ.get("MODEL_PREPROCESS", "none").lower()
# Average predictions over the image and its horizontal flip.
TTA_ENABLED = os.environ.get("MODEL_TTA", "1").lower() not in ("0", "false", "no")
NUM_THREADS = int(os.environ.get("MODEL_NUM_THREADS", str(os.cpu_count() or 1)))

# Keras ResNet / ResNet34 ImageNet mean subtraction (caffe mode, BGR order)
_RESNET_MEANS_BGR = np.array([103.939, 116.779, 123.68], dtype=np.float32)


class ModelNotLoadedError(Exception):
    """Raised when the TFLite model file is missing or failed to load."""


def _none_preprocess(arr: np.ndarray) -> np.ndarray:
    """No-op — pass raw 0-255 pixel values through unchanged.

    Use this when preprocessing is already baked into the model graph, which
    is the case for both training notebooks (MobileNetV2 preprocess_input in
    v2, EfficientNetV2 / ConvNeXt built-in preprocessing layers in v3).
    Applying it again here would double-scale every image.
    """
    return arr


def _mobilenet_preprocess(arr: np.ndarray) -> np.ndarray:
    """Match tf.keras.applications.mobilenet_v2.preprocess_input (scale to [-1, 1])."""
    return (arr / 127.5) - 1.0


def _resnet_preprocess(arr: np.ndarray) -> np.ndarray:
    """Match tf.keras.applications.resnet50.preprocess_input (caffe mode)."""
    arr = arr[..., ::-1].copy()  # RGB -> BGR
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


def prepare_image(img: Image.Image) -> Image.Image:
    """
    Normalise orientation before resizing. Must match the v3 training notebook.

    - Apply the EXIF orientation tag: phone cameras store photos sideways and
      rely on this tag, so without it the model sees a rotated leaf.
    - Rotate landscape images to portrait (90° counter-clockwise). Paddy Doctor
      photos are 480×640 portrait, and the model is trained on portrait input.
    """
    img = ImageOps.exif_transpose(img).convert("RGB")
    if img.width > img.height:
        img = img.rotate(90, expand=True)
    return img


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _resolve_model_path(path: str) -> str:
    """
    Resolve MODEL_PATH regardless of the process's working directory.

    .env documents MODEL_PATH relative to the project root, but start.sh runs
    the app from inside backend/, so a naive relative lookup would resolve to
    backend/backend/... and silently fall back to random predictions. Resolve
    relative paths against the project root instead of CWD. Absolute paths
    (e.g. Docker's /app/backend/models) pass through unchanged.
    """
    if os.path.isabs(path):
        return path
    return os.path.join(PROJECT_ROOT, path)


def _load_tflite_module():
    try:
        import tflite_runtime.interpreter as tflite
        return tflite
    except ImportError:
        try:
            import tensorflow.lite as tflite  # type: ignore
            return tflite
        except ImportError as exc:
            raise ModelNotLoadedError(
                "Neither tflite-runtime nor tensorflow is installed"
            ) from exc


class _Member:
    """One .tflite model in the ensemble."""

    def __init__(self, tflite, path: str):
        self.path = path
        self.interpreter = tflite.Interpreter(model_path=path, num_threads=NUM_THREADS)
        self.interpreter.allocate_tensors()
        inp = self.interpreter.get_input_details()[0]
        out = self.interpreter.get_output_details()[0]
        self.input_index = inp["index"]
        self.input_dtype = inp["dtype"]
        self.output_index = out["index"]
        self.num_outputs = int(out["shape"][-1])

        _, h, w, _ = (int(d) for d in inp["shape"])
        self.height = h if h > 0 else INPUT_SIZE
        self.width = w if w > 0 else INPUT_SIZE

    def predict(self, img: Image.Image, tta: bool) -> np.ndarray:
        resized = img.resize((self.width, self.height), Image.Resampling.BILINEAR)
        arr = preprocess_image(np.asarray(resized, dtype=np.float32))
        batch = [arr]
        if tta:
            batch.append(arr[:, ::-1, :])  # horizontal flip

        probs = []
        for x in batch:
            x = np.ascontiguousarray(x[np.newaxis]).astype(self.input_dtype)
            self.interpreter.set_tensor(self.input_index, x)
            self.interpreter.invoke()
            out = self.interpreter.get_tensor(self.output_index)[0].astype(np.float64)
            if out.min() < 0 or abs(out.sum() - 1.0) > 0.1:
                # Model returned logits rather than softmax probabilities.
                exp = np.exp(out - np.max(out))
                out = exp / exp.sum()
            probs.append(out)
        return np.mean(probs, axis=0)


class DiseaseModel:
    def __init__(self, model_path: Optional[str] = None):
        raw_path = model_path or os.environ.get("MODEL_PATH", MODELS_DIR)
        self.model_path = _resolve_model_path(raw_path)
        self.members: list[_Member] = []
        self.class_names: list[str] = list(DISEASE_CLASSES)
        self.temperature = 1.0
        self.recommended_threshold: Optional[float] = None
        self.arch = "unknown"
        # TFLite interpreters are not thread-safe; predictions run in a worker thread.
        self._lock = threading.Lock()
        self._load()

    def _model_files(self) -> tuple[list[str], dict]:
        """Return (tflite paths, metadata) for MODEL_PATH."""
        path = self.model_path
        if os.path.isfile(path):
            meta = self._read_meta(os.path.dirname(path))
            # Only trust metadata written for this exact file.
            if os.path.basename(path) not in meta.get("models", []):
                meta = {}
            return [path], meta

        if os.path.isdir(path):
            meta = self._read_meta(path)
            if meta.get("models"):
                return [os.path.join(path, name) for name in meta["models"]], meta
            files = sorted(
                os.path.join(path, name) for name in os.listdir(path) if name.endswith(".tflite")
            )
            return files, {}

        return [], {}

    @staticmethod
    def _read_meta_file(meta_path: str) -> dict:
        if not os.path.isfile(meta_path):
            return {}
        with open(meta_path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _read_meta(directory: str) -> dict:
        return DiseaseModel._read_meta_file(os.path.join(directory, META_FILENAME))

    def _load(self) -> None:
        files, meta = self._model_files()
        missing = [f for f in files if not os.path.isfile(f)]
        if missing:
            raise ModelNotLoadedError(f"Model files listed in {META_FILENAME} are missing: {missing}")
        if not files:
            logger.warning(
                "No TFLite model found at %s — using random classification fallback for testing",
                self.model_path,
            )
            return

        tflite = _load_tflite_module()
        self.members = [_Member(tflite, f) for f in files]

        self.class_names = meta.get("class_names", list(DISEASE_CLASSES))
        self.temperature = float(meta.get("temperature", 1.0))
        self.recommended_threshold = meta.get("recommended_threshold")
        self.arch = meta.get("backbone", "mobilenetv2" if not meta else "unknown")

        for m in self.members:
            if m.num_outputs != len(self.class_names):
                raise ModelNotLoadedError(
                    f"{m.path} has {m.num_outputs} outputs but {len(self.class_names)} class names"
                )

        logger.info(
            "Loaded %d TFLite model(s) from %s (%s, %dx%d, preprocess=%s, tta=%s, T=%.3f)",
            len(self.members),
            self.model_path,
            self.arch,
            self.members[0].width,
            self.members[0].height,
            PREPROCESS_MODE,
            TTA_ENABLED,
            self.temperature,
        )

    @property
    def is_loaded(self) -> bool:
        return bool(self.members)

    @property
    def model_mode(self) -> str:
        return "tflite" if self.is_loaded else "random"

    @property
    def input_size(self) -> Optional[tuple[int, int]]:
        """(width, height) of the first model, or None in random mode."""
        if not self.members:
            return None
        return self.members[0].width, self.members[0].height

    def _random_probs(self, img: Image.Image) -> np.ndarray:
        """Temporary testing fallback when no .tflite model is available."""
        arr = np.array(img.convert("RGB"), dtype=np.uint8)
        seed = int(np.sum(arr, dtype=np.uint64) % (2**32 - 1))
        rng = np.random.default_rng(seed)
        probs = rng.random(len(self.class_names))
        return probs / probs.sum()

    def predict_proba(self, img: Image.Image) -> np.ndarray:
        """Calibrated class probabilities, averaged over the ensemble and TTA."""
        img = prepare_image(img)
        if not self.is_loaded:
            return self._random_probs(img)

        with self._lock:
            probs = np.mean([m.predict(img, TTA_ENABLED) for m in self.members], axis=0)

        if self.temperature != 1.0:
            logits = np.log(np.clip(probs, 1e-12, 1.0)) / self.temperature
            exp = np.exp(logits - logits.max())
            probs = exp / exp.sum()
        return probs

    def predict_top(self, img: Image.Image, k: int = 3) -> list[tuple[str, float]]:
        """Top-k (class name, confidence %) pairs, highest first."""
        probs = self.predict_proba(img)
        order = np.argsort(probs)[::-1][:k]
        return [(self.class_names[i], float(probs[i]) * 100) for i in order]

    def predict(self, img: Image.Image) -> tuple[str, float]:
        return self.predict_top(img, k=1)[0]


GATE_FILENAME = "crop_gate.tflite"
GATE_META_FILENAME = "crop_gate.json"
# CROP_GATE=0 turns the gate off; CROP_GATE_THRESHOLD overrides the trained threshold.
GATE_ENABLED = os.environ.get("CROP_GATE", "1").lower() not in ("0", "false", "no")


class CropGate:
    """Answers "is this a rice leaf photo at all?" before any disease is predicted.

    The disease model only knows 10 rice classes, so it labels a photo of anything with one
    of them. scripts/train_crop_gate.py trains this small MobileNetV2 + logistic head on
    rice photos vs. everything else and writes crop_gate.tflite + crop_gate.json.
    When those files are absent the gate is inactive and every image passes.
    """

    def __init__(self, directory: str):
        self.member: Optional[_Member] = None
        self.threshold = 0.5
        self._lock = threading.Lock()
        model_file = os.path.join(directory, GATE_FILENAME)
        if not GATE_ENABLED or not os.path.isfile(model_file):
            logger.warning("Crop gate inactive (%s) — non-rice photos will not be rejected",
                           "disabled" if not GATE_ENABLED else f"{model_file} not found")
            return
        meta = DiseaseModel._read_meta_file(os.path.join(directory, GATE_META_FILENAME))
        self.threshold = float(os.environ.get("CROP_GATE_THRESHOLD") or meta.get("threshold", 0.5))
        self.member = _Member(_load_tflite_module(), model_file)
        logger.info("Loaded crop gate (threshold %.3f)", self.threshold)

    @property
    def is_active(self) -> bool:
        return self.member is not None

    def leaf_probability(self, img: Image.Image) -> Optional[float]:
        """P(image is a rice leaf photo), or None when the gate is inactive."""
        if self.member is None:
            return None
        img = prepare_image(img)
        resized = img.resize((self.member.width, self.member.height), Image.Resampling.BILINEAR)
        x = np.asarray(resized, dtype=np.float32)[np.newaxis].astype(self.member.input_dtype)
        with self._lock:
            self.member.interpreter.set_tensor(self.member.input_index, x)
            self.member.interpreter.invoke()
            out = self.member.interpreter.get_tensor(self.member.output_index)
        return float(np.ravel(out)[0])

    def is_rice_leaf(self, img: Image.Image) -> tuple[bool, Optional[float]]:
        p = self.leaf_probability(img)
        return (p is None or p >= self.threshold), p


_model: Optional[DiseaseModel] = None
_gate: Optional[CropGate] = None


def get_model() -> DiseaseModel:
    global _model
    if _model is None:
        _model = DiseaseModel()
    return _model


def get_gate() -> CropGate:
    global _gate
    if _gate is None:
        model_path = _resolve_model_path(os.environ.get("MODEL_PATH", MODELS_DIR))
        _gate = CropGate(model_path if os.path.isdir(model_path) else os.path.dirname(model_path))
    return _gate
