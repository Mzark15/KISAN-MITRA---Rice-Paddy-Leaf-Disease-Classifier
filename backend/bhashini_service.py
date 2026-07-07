"""Bhashini ULCA pipeline integration for voice STT, translation, and TTS."""

import base64
import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

BHASHINI_URL = "https://dhruva-api.bhashini.gov.in/services/inference/pipeline"

LANGUAGE_MAP = {
    "hi": "hi",
    "mr": "mr",
    "en": "en",
    "ta": "ta",
    "te": "te",
    "kn": "kn",
    "pa": "pa",
    "gu": "gu",
    "bn": "bn",
    "ml": "ml",
}


class VoiceNotConfiguredError(Exception):
    """Bhashini credentials not set."""


class VoiceServiceError(Exception):
    """Bhashini API call failed."""


def is_voice_configured() -> bool:
    return bool(os.environ.get("BHASHINI_USER_ID") and os.environ.get("BHASHINI_API_KEY"))


def _headers() -> dict[str, str]:
    if not is_voice_configured():
        raise VoiceNotConfiguredError(
            "Voice not configured. Set BHASHINI_USER_ID and BHASHINI_API_KEY."
        )
    return {
        "Authorization": os.environ["BHASHINI_API_KEY"],
        "userID": os.environ["BHASHINI_USER_ID"],
        "Content-Type": "application/json",
    }


def _normalize_lang(language: str) -> str:
    return LANGUAGE_MAP.get(language.lower(), language.lower())


def _pipeline_id() -> Optional[str]:
    return os.environ.get("BHASHINI_PIPELINE_ID")


def _extract_text(data: dict[str, Any]) -> str:
    if "pipelineResponse" in data:
        for task in data["pipelineResponse"]:
            output = task.get("output", [])
            for item in output:
                if "source" in item:
                    return str(item["source"]).strip()
                if "text" in item:
                    return str(item["text"]).strip()
    if "output" in data:
        for item in data["output"]:
            if isinstance(item, dict):
                if "source" in item:
                    return str(item["source"]).strip()
                if "text" in item:
                    return str(item["text"]).strip()
    if "text" in data:
        return str(data["text"]).strip()
    raise VoiceServiceError("Could not parse Bhashini text response")


def _extract_audio(data: dict[str, Any]) -> Optional[bytes]:
    if "pipelineResponse" in data:
        for task in data["pipelineResponse"]:
            output = task.get("output", [])
            for item in output:
                audio_b64 = item.get("audioContent") or item.get("audio")
                if audio_b64:
                    return base64.b64decode(audio_b64)
    if "audio" in data:
        return base64.b64decode(data["audio"])
    if "audioContent" in data:
        return base64.b64decode(data["audioContent"])
    return None


def _base_payload(task_type: str, language: str, extra_config: Optional[dict] = None) -> dict:
    config: dict[str, Any] = {"language": {"sourceLanguage": _normalize_lang(language)}}
    if extra_config:
        config.update(extra_config)
    payload: dict[str, Any] = {
        "pipelineTasks": [{"taskType": task_type, "config": config}],
        "inputData": {},
    }
    pipeline_id = _pipeline_id()
    if pipeline_id:
        payload["pipelineRequestConfig"] = {"pipelineId": pipeline_id}
    return payload


async def _post_pipeline(payload: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(BHASHINI_URL, headers=_headers(), json=payload)
        if response.status_code >= 400:
            raise VoiceServiceError(
                f"Bhashini API error {response.status_code}: {response.text[:300]}"
            )
        return response.json()


async def speech_to_text(audio_bytes: bytes, source_language: str) -> str:
    payload = _base_payload("asr", source_language)
    payload["inputData"]["audio"] = [
        {"audioContent": base64.b64encode(audio_bytes).decode("utf-8")}
    ]
    data = await _post_pipeline(payload)
    return _extract_text(data)


async def translate_text(text: str, source_lang: str, target_lang: str) -> str:
    payload = _base_payload(
        "translation",
        source_lang,
        {
            "language": {
                "sourceLanguage": _normalize_lang(source_lang),
                "targetLanguage": _normalize_lang(target_lang),
            }
        },
    )
    payload["inputData"]["input"] = [{"source": text}]
    data = await _post_pipeline(payload)
    return _extract_text(data)


async def text_to_speech(text: str, language: str) -> Optional[bytes]:
    try:
        payload = _base_payload("tts", language)
        payload["inputData"]["input"] = [{"source": text}]
        data = await _post_pipeline(payload)
        audio = _extract_audio(data)
        if not audio:
            raise VoiceServiceError("No audio in TTS response")
        return audio
    except Exception as exc:
        logger.warning("Bhashini TTS failed, frontend should use speechSynthesis: %s", exc)
        return None
