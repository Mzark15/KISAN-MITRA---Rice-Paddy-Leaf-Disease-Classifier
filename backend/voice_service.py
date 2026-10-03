"""
voice_service.py — Unified STT/TTS router

Sits between the voice router and the actual providers (MLX, Bhashini).
Selects provider based on VOICE_STT_PROVIDER env var:

  mlx      — local Qwen2-Audio on Apple Silicon (requires mlx-audio + ffmpeg)
  bhashini — Bhashini cloud API (requires BHASHINI_USER_ID + BHASHINI_API_KEY)
  auto     — try MLX first, fall back to Bhashini if MLX is not loaded
  browser  — no server STT; always return 503 so frontend uses Web Speech API

TTS is always Bhashini-only. If Bhashini is not configured, returns None
and the frontend uses the browser's speechSynthesis API.

To add a new STT provider:
  1. Create a new service module (e.g. google_stt_service.py).
  2. Add a branch to speech_to_text() below.
  3. Update is_stt_configured() and stt_status() to include the new provider.
"""

import logging
import os

import bhashini_service
import mlx_stt_service

logger = logging.getLogger(__name__)


class VoiceNotConfiguredError(Exception):
    """No STT provider is available. Frontend should fall back to Web Speech API."""

class VoiceServiceError(Exception):
    """An STT or TTS provider call failed."""


# ---------------------------------------------------------------------------
# Provider selection
# ---------------------------------------------------------------------------

def get_stt_provider() -> str:
    """
    Return the active STT provider from VOICE_STT_PROVIDER env var.
    Valid values: mlx | bhashini | auto | browser
    Default: auto  (tries MLX, then Bhashini, then raises 503)
    """
    return os.environ.get("VOICE_STT_PROVIDER", "auto").lower()


def is_stt_configured() -> bool:
    """
    True when at least one STT provider is ready to accept requests.
    The frontend uses this to decide whether to show the server-side voice button
    or go straight to the browser Web Speech API fallback.
    """
    provider = get_stt_provider()
    if provider == "mlx":
        return mlx_stt_service.is_loaded()
    if provider == "bhashini":
        return bhashini_service.is_voice_configured()
    if provider == "auto":
        # Auto: ready if either provider works
        return mlx_stt_service.is_loaded() or bhashini_service.is_voice_configured()
    # "browser" or unknown: always use browser fallback
    return False


def stt_status() -> dict:
    """
    Full status dict returned by GET /voice/status.
    Lets the frontend (and developers) see exactly why voice is/isn't working.
    """
    return {
        "provider":             get_stt_provider(),
        "mlx_loaded":           mlx_stt_service.is_loaded(),
        "mlx_error":            mlx_stt_service.load_error(),
        "bhashini_configured":  bhashini_service.is_voice_configured(),
        "stt_ready":            is_stt_configured(),
    }


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

async def init_stt() -> None:
    """
    Called once at startup (main.py lifespan).
    Loads the MLX model in a background thread when VOICE_STT_PROVIDER is mlx or auto.
    No-op on non-Apple-Silicon machines.
    """
    provider = get_stt_provider()
    if provider in ("mlx", "auto") and mlx_stt_service.is_enabled():
        import asyncio
        logger.info("Loading MLX STT model in background thread...")
        await asyncio.to_thread(mlx_stt_service.init_model)
        if mlx_stt_service.is_loaded():
            logger.info("MLX STT ready.")
        else:
            logger.warning("MLX STT did not load: %s", mlx_stt_service.load_error())


# ---------------------------------------------------------------------------
# STT
# ---------------------------------------------------------------------------

async def speech_to_text(audio_bytes: bytes, source_language: str, filename: str = "") -> str:
    """
    Convert audio bytes to text using the configured STT provider.

    Provider order for 'auto':
      1. MLX (if loaded)
      2. Bhashini (if credentials are set)
      3. VoiceNotConfiguredError → frontend falls back to Web Speech API

    `filename` is the original upload filename (e.g. "recording.mp4" on Safari,
    "recording.webm" elsewhere) — the frontend already detects the browser's
    actual MediaRecorder output format and names the file accordingly. We must
    use that real extension when converting with ffmpeg; hardcoding ".webm"
    breaks on Safari/iOS, which record audio/mp4 instead.

    Raises:
        VoiceNotConfiguredError: no provider available
        VoiceServiceError: provider call failed
    """
    provider = get_stt_provider()
    suffix = os.path.splitext(filename)[1] or ".webm"

    # --- MLX path ---
    if provider == "mlx" or (provider == "auto" and mlx_stt_service.is_loaded()):
        try:
            return await mlx_stt_service.speech_to_text(audio_bytes, source_language, suffix)
        except mlx_stt_service.MlxSTTNotAvailable as exc:
            if provider == "mlx":
                # Hard fail: user explicitly chose MLX and it's not available
                raise VoiceNotConfiguredError(
                    f"MLX STT unavailable: {exc}. "
                    "Set VOICE_STT_PROVIDER=bhashini or install mlx-audio on Apple Silicon."
                ) from exc
            # Auto mode: log and try Bhashini next
            logger.warning("MLX STT not available, trying Bhashini: %s", exc)
        except mlx_stt_service.MlxSTTError as exc:
            raise VoiceServiceError(f"MLX STT error: {exc}") from exc

    # --- Bhashini path ---
    if provider in ("bhashini", "auto") and bhashini_service.is_voice_configured():
        try:
            return await bhashini_service.speech_to_text(audio_bytes, source_language)
        except bhashini_service.VoiceNotConfiguredError as exc:
            raise VoiceNotConfiguredError(str(exc)) from exc
        except bhashini_service.VoiceServiceError as exc:
            raise VoiceServiceError(str(exc)) from exc

    # --- Nothing available ---
    raise VoiceNotConfiguredError(
        "No STT provider is configured or ready. "
        "Options:\n"
        "  • Apple Silicon: install mlx-audio and set VOICE_STT_PROVIDER=mlx\n"
        "  • Cloud: set BHASHINI_USER_ID + BHASHINI_API_KEY and VOICE_STT_PROVIDER=bhashini\n"
        "  • Browser-only: the frontend will use the Web Speech API automatically when this returns 503."
    )


# ---------------------------------------------------------------------------
# TTS
# ---------------------------------------------------------------------------

async def text_to_speech(text: str, language: str) -> bytes | None:
    """
    Convert text to audio bytes using Bhashini TTS.

    Returns:
        bytes — audio data (mp3/wav) if Bhashini is configured and the call succeeds.
        None  — if Bhashini is not configured (caller falls back to browser speechSynthesis).

    Raises:
        VoiceServiceError — if Bhashini IS configured but the API call fails.
                            Caller may choose to fall back to browser or surface the error.
    """
    if not bhashini_service.is_voice_configured():
        return None   # frontend uses speechSynthesis

    return await bhashini_service.text_to_speech(text, language)
    # Note: bhashini_service.text_to_speech raises VoiceServiceError on failure,
    # which the caller (voice router) catches and turns into HTTP 502.
