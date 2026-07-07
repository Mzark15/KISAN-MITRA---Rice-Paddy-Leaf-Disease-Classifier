"""Local speech-to-text via MLX Audio (Qwen2-Audio) on Apple Silicon."""

import asyncio
import logging
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "mlx-community/Qwen2-Audio-7B-Instruct-4bit"

LANG_PROMPTS = {
    "hi": "Transcribe the audio. The speaker is speaking Hindi. Return only the transcription text.",
    "mr": "Transcribe the audio. The speaker is speaking Marathi. Return only the transcription text.",
    "en": "Transcribe the audio. The speaker is speaking English. Return only the transcription text.",
}


class MlxSTTError(Exception):
    """MLX STT failed."""


class MlxSTTNotAvailable(Exception):
    """MLX STT is not available on this system."""


_model = None
_load_error: Optional[str] = None


def is_platform_supported() -> bool:
    return platform.system() == "Darwin" and platform.machine() in ("arm64", "aarch64")


def is_enabled() -> bool:
    return os.environ.get("MLX_STT_ENABLED", "1").lower() not in ("0", "false", "no")


def is_loaded() -> bool:
    return _model is not None


def load_error() -> Optional[str]:
    return _load_error


def init_model() -> None:
    """Load Qwen2-Audio model once at startup (blocking — call from a thread)."""
    global _model, _load_error

    if not is_enabled():
        _load_error = "MLX STT disabled (MLX_STT_ENABLED=0)"
        return
    if not is_platform_supported():
        _load_error = "MLX STT requires Apple Silicon (M-series Mac)"
        return

    try:
        from mlx_audio.stt.utils import load_model
    except ImportError as exc:
        _load_error = "mlx-audio not installed. Run: pip install mlx-audio"
        logger.warning(_load_error)
        return

    model_id = os.environ.get("MLX_STT_MODEL", DEFAULT_MODEL)
    try:
        logger.info("Loading MLX STT model %s (first run may download ~4GB)...", model_id)
        _model = load_model(model_id)
        _load_error = None
        logger.info("MLX STT model ready: %s", model_id)
    except Exception as exc:
        _load_error = str(exc)
        logger.exception("Failed to load MLX STT model")


def _bytes_to_wav_path(audio_bytes: bytes, suffix: str = ".webm") -> str:
    """Convert uploaded audio to a WAV file path for mlx-audio."""
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as src:
        src.write(audio_bytes)
        src_path = src.name

    wav_path = src_path.rsplit(".", 1)[0] + ".wav"

    if suffix.lower() == ".wav":
        return src_path

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise MlxSTTError(
            "ffmpeg is required to convert browser audio (webm) to wav. "
            "Install with: brew install ffmpeg"
        )

    result = subprocess.run(
        [ffmpeg, "-y", "-i", src_path, "-ar", "16000", "-ac", "1", wav_path],
        capture_output=True,
        text=True,
    )
    Path(src_path).unlink(missing_ok=True)
    if result.returncode != 0:
        Path(wav_path).unlink(missing_ok=True)
        raise MlxSTTError(f"ffmpeg conversion failed: {result.stderr[:300]}")
    return wav_path


def _transcribe_sync(wav_path: str, language: str) -> str:
    if _model is None:
        raise MlxSTTNotAvailable(_load_error or "MLX STT model not loaded")

    prompt = LANG_PROMPTS.get(language, LANG_PROMPTS["en"])
    result = _model.generate(wav_path, prompt=prompt)
    text = (getattr(result, "text", None) or str(result)).strip()
    if not text:
        raise MlxSTTError("Empty transcription from MLX STT")
    return text


async def speech_to_text(audio_bytes: bytes, source_language: str) -> str:
    if _model is None:
        raise MlxSTTNotAvailable(_load_error or "MLX STT model not loaded")

    wav_path = await asyncio.to_thread(_bytes_to_wav_path, audio_bytes, ".webm")
    try:
        return await asyncio.to_thread(_transcribe_sync, wav_path, source_language)
    finally:
        Path(wav_path).unlink(missing_ok=True)
