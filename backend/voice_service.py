"""Unified voice STT/TTS — MLX local STT or Bhashini cloud."""

import logging
import os

import bhashini_service
import mlx_stt_service

logger = logging.getLogger(__name__)


class VoiceNotConfiguredError(Exception):
    """No STT provider available."""


class VoiceServiceError(Exception):
    """Voice API call failed."""


def get_stt_provider() -> str:
    return os.environ.get("VOICE_STT_PROVIDER", "mlx").lower()


def is_stt_configured() -> bool:
    provider = get_stt_provider()
    if provider == "mlx":
        return mlx_stt_service.is_loaded()
    if provider == "bhashini":
        return bhashini_service.is_voice_configured()
    if provider == "auto":
        return mlx_stt_service.is_loaded() or bhashini_service.is_voice_configured()
    return False


def stt_status() -> dict:
    return {
        "provider": get_stt_provider(),
        "mlx_loaded": mlx_stt_service.is_loaded(),
        "mlx_error": mlx_stt_service.load_error(),
        "bhashini_configured": bhashini_service.is_voice_configured(),
        "stt_ready": is_stt_configured(),
    }


async def init_stt() -> None:
    """Load MLX model at startup when configured."""
    provider = get_stt_provider()
    if provider in ("mlx", "auto") and mlx_stt_service.is_enabled():
        import asyncio

        await asyncio.to_thread(mlx_stt_service.init_model)


async def speech_to_text(audio_bytes: bytes, source_language: str) -> str:
    provider = get_stt_provider()

    if provider == "mlx" or (provider == "auto" and mlx_stt_service.is_loaded()):
        try:
            return await mlx_stt_service.speech_to_text(audio_bytes, source_language)
        except mlx_stt_service.MlxSTTNotAvailable as exc:
            if provider == "mlx":
                raise VoiceNotConfiguredError(str(exc)) from exc
            logger.warning("MLX STT unavailable, trying Bhashini: %s", exc)
        except mlx_stt_service.MlxSTTError as exc:
            raise VoiceServiceError(str(exc)) from exc

    if provider in ("bhashini", "auto") and bhashini_service.is_voice_configured():
        try:
            return await bhashini_service.speech_to_text(audio_bytes, source_language)
        except bhashini_service.VoiceNotConfiguredError as exc:
            raise VoiceNotConfiguredError(str(exc)) from exc
        except bhashini_service.VoiceServiceError as exc:
            raise VoiceServiceError(str(exc)) from exc

    raise VoiceNotConfiguredError(
        "Voice STT not configured. Enable MLX STT (Apple Silicon + mlx-audio) "
        "or set BHASHINI_USER_ID and BHASHINI_API_KEY."
    )


async def text_to_speech(text: str, language: str) -> bytes | None:
    """TTS via Bhashini only; returns None if unavailable (browser fallback)."""
    if not bhashini_service.is_voice_configured():
        return None
    return await bhashini_service.text_to_speech(text, language)
