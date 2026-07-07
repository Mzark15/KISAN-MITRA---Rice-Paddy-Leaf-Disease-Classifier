"""
bhashini_service.py — Bhashini ULCA pipeline: STT, TTS, translation

Bhashini is India's government language AI platform (free for Indian languages).
Docs: https://bhashini.gitbook.io/bhashini-apis/

Required env vars:
  BHASHINI_USER_ID    — your Bhashini user ID
  BHASHINI_API_KEY    — your Bhashini API key / authorisation token
  BHASHINI_PIPELINE_ID — (optional) pipeline ID; if not set, Bhashini selects a default

Supported STT languages: hi mr en ta te kn pa gu bn ml
Supported TTS languages: hi mr en ta te kn pa gu bn ml

If credentials are missing, all functions raise VoiceNotConfiguredError (HTTP 503).
"""

import base64
import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# Bhashini ULCA inference endpoint
BHASHINI_URL = "https://dhruva-api.bhashini.gov.in/services/inference/pipeline"

# BCP-47 language codes accepted by Bhashini
LANGUAGE_MAP: dict[str, str] = {
    "hi": "hi", "mr": "mr", "en": "en",
    "ta": "ta", "te": "te", "kn": "kn",
    "pa": "pa", "gu": "gu", "bn": "bn", "ml": "ml",
}

# Bhashini-accepted audio formats for ASR
# Browser MediaRecorder produces webm; ffmpeg converts it to wav for MLX.
# For Bhashini we send webm directly and declare the format.
BHASHINI_AUDIO_FORMAT = "webm"     # change to "wav" if you pre-convert
BHASHINI_SAMPLE_RATE  = 16000      # Hz — Bhashini expects 16 kHz mono

# Request timeout in seconds (Bhashini can be slow on first request)
REQUEST_TIMEOUT = 60.0


class VoiceNotConfiguredError(Exception):
    """Raised when BHASHINI_USER_ID or BHASHINI_API_KEY is not set."""

class VoiceServiceError(Exception):
    """Raised when the Bhashini API call fails (network, bad response, parse error)."""


# ---------------------------------------------------------------------------
# Auth & config helpers
# ---------------------------------------------------------------------------

def is_voice_configured() -> bool:
    """True when both required Bhashini credentials are set."""
    return bool(os.environ.get("BHASHINI_USER_ID") and os.environ.get("BHASHINI_API_KEY"))


def _require_configured() -> None:
    if not is_voice_configured():
        raise VoiceNotConfiguredError(
            "Bhashini not configured. Set BHASHINI_USER_ID and BHASHINI_API_KEY."
        )


def _headers() -> dict[str, str]:
    _require_configured()
    return {
        "Authorization":  os.environ["BHASHINI_API_KEY"],
        "userID":         os.environ["BHASHINI_USER_ID"],
        "Content-Type":   "application/json",
    }


def _normalize_lang(language: str) -> str:
    """Map a language code to the form Bhashini expects, defaulting to the code itself."""
    return LANGUAGE_MAP.get(language.lower(), language.lower())


def _pipeline_id() -> Optional[str]:
    return os.environ.get("BHASHINI_PIPELINE_ID") or None


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------

def _build_asr_payload(audio_bytes: bytes, language: str) -> dict[str, Any]:
    """Build the ASR (speech-to-text) request payload for Bhashini."""
    lang = _normalize_lang(language)
    payload: dict[str, Any] = {
        "pipelineTasks": [{
            "taskType": "asr",
            "config": {
                "language":    {"sourceLanguage": lang},
                "audioFormat": BHASHINI_AUDIO_FORMAT,
                "samplingRate": BHASHINI_SAMPLE_RATE,
            },
        }],
        "inputData": {
            "audio": [{"audioContent": base64.b64encode(audio_bytes).decode("utf-8")}]
        },
    }
    if pid := _pipeline_id():
        payload["pipelineRequestConfig"] = {"pipelineId": pid}
    return payload


def _build_tts_payload(text: str, language: str) -> dict[str, Any]:
    """Build the TTS (text-to-speech) request payload for Bhashini."""
    lang = _normalize_lang(language)
    payload: dict[str, Any] = {
        "pipelineTasks": [{
            "taskType": "tts",
            "config": {
                "language": {"sourceLanguage": lang},
                "gender":   "female",
                "samplingRate": 8000,
            },
        }],
        "inputData": {
            "input": [{"source": text}]
        },
    }
    if pid := _pipeline_id():
        payload["pipelineRequestConfig"] = {"pipelineId": pid}
    return payload


def _build_translation_payload(text: str, source_lang: str, target_lang: str) -> dict[str, Any]:
    """Build a translation request payload for Bhashini."""
    payload: dict[str, Any] = {
        "pipelineTasks": [{
            "taskType": "translation",
            "config": {
                "language": {
                    "sourceLanguage": _normalize_lang(source_lang),
                    "targetLanguage": _normalize_lang(target_lang),
                },
            },
        }],
        "inputData": {
            "input": [{"source": text}]
        },
    }
    if pid := _pipeline_id():
        payload["pipelineRequestConfig"] = {"pipelineId": pid}
    return payload


# ---------------------------------------------------------------------------
# Response parsers
# ---------------------------------------------------------------------------

def _extract_text(data: dict[str, Any], task_type: str) -> str:
    """
    Extract the text result from a Bhashini pipeline response.
    Handles both pipelineResponse shape and flat output shape.
    Raises VoiceServiceError if no text found.
    """
    # Primary shape: pipelineResponse[].output[].source or .text
    if "pipelineResponse" in data:
        for task in data["pipelineResponse"]:
            for item in task.get("output", []):
                for key in ("source", "text", "target"):
                    val = item.get(key, "").strip()
                    if val:
                        return val

    # Flat shape fallback
    for item in data.get("output", []):
        if isinstance(item, dict):
            for key in ("source", "text", "target"):
                val = item.get(key, "").strip()
                if val:
                    return val

    if text := data.get("text", "").strip():
        return text

    logger.error("Unexpected Bhashini %s response shape: %s", task_type, str(data)[:400])
    raise VoiceServiceError(
        f"Could not parse Bhashini {task_type} response. "
        "Check BHASHINI_PIPELINE_ID or contact Bhashini support."
    )


def _extract_audio(data: dict[str, Any]) -> Optional[bytes]:
    """
    Extract base64-encoded audio from a Bhashini TTS response and return raw bytes.
    Returns None if no audio field found (caller decides whether to raise or fall back).
    """
    if "pipelineResponse" in data:
        for task in data["pipelineResponse"]:
            for item in task.get("audio", []):
                for key in ("audioContent", "audio"):
                    b64 = item.get(key)
                    if b64:
                        return base64.b64decode(b64)
            # Some pipeline responses nest audio inside output
            for item in task.get("output", []):
                for key in ("audioContent", "audio"):
                    b64 = item.get(key)
                    if b64:
                        return base64.b64decode(b64)

    # Flat shape
    for key in ("audioContent", "audio"):
        if b64 := data.get(key):
            return base64.b64decode(b64)

    return None


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

async def _post(payload: dict[str, Any]) -> dict[str, Any]:
    """POST a payload to the Bhashini pipeline endpoint and return parsed JSON."""
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(BHASHINI_URL, headers=_headers(), json=payload)
    except httpx.TimeoutException as exc:
        raise VoiceServiceError(
            f"Bhashini request timed out after {REQUEST_TIMEOUT}s. "
            "The service may be slow — try again."
        ) from exc
    except httpx.RequestError as exc:
        raise VoiceServiceError(f"Network error reaching Bhashini: {exc}") from exc

    if resp.status_code >= 400:
        raise VoiceServiceError(
            f"Bhashini API returned HTTP {resp.status_code}: {resp.text[:300]}"
        )

    try:
        return resp.json()
    except Exception as exc:
        raise VoiceServiceError(
            f"Bhashini returned non-JSON response (status {resp.status_code}): {resp.text[:200]}"
        ) from exc


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def speech_to_text(audio_bytes: bytes, source_language: str) -> str:
    """
    Convert audio bytes (webm from browser MediaRecorder) to text.

    Raises:
        VoiceNotConfiguredError: credentials not set
        VoiceServiceError: API call failed or response could not be parsed
    """
    _require_configured()
    if not audio_bytes:
        raise VoiceServiceError("Empty audio bytes passed to Bhashini STT.")

    payload = _build_asr_payload(audio_bytes, source_language)
    data    = await _post(payload)
    return _extract_text(data, "asr")


async def text_to_speech(text: str, language: str) -> Optional[bytes]:
    """
    Convert text to audio bytes (mp3/wav) using Bhashini TTS.

    Returns None if Bhashini is not configured (caller should use browser speechSynthesis).
    Raises VoiceServiceError if configured but the API call fails.
    """
    if not is_voice_configured():
        return None   # caller falls back to browser TTS

    if not text.strip():
        raise VoiceServiceError("Cannot generate TTS for empty text.")

    try:
        payload = _build_tts_payload(text, language)
        data    = await _post(payload)
        audio   = _extract_audio(data)
        if audio is None:
            logger.warning(
                "Bhashini TTS returned no audio for language=%s. Response: %s",
                language, str(data)[:300],
            )
            return None
        return audio
    except VoiceServiceError:
        raise   # re-raise — caller decides whether to fall back
    except Exception as exc:
        raise VoiceServiceError(f"Unexpected TTS error: {exc}") from exc


async def translate_text(text: str, source_lang: str, target_lang: str) -> str:
    """
    Translate text between languages using Bhashini.

    Raises:
        VoiceNotConfiguredError: credentials not set
        VoiceServiceError: API call failed
    """
    _require_configured()
    payload = _build_translation_payload(text, source_lang, target_lang)
    data    = await _post(payload)
    return _extract_text(data, "translation")
