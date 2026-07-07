"""
routers/voice.py — Voice endpoints

Three endpoints:
  GET  /voice/status  — check which STT/TTS providers are configured
  POST /voice/stt     — audio → text (Bhashini or MLX)
  POST /voice/tts     — text → audio bytes (Bhashini; 503 if not configured → frontend uses speechSynthesis)
  POST /voice/chat    — full pipeline: audio → STT → LLM → TTS → return transcript + reply

STT provider is selected by VOICE_STT_PROVIDER env var:
  mlx      = local Qwen2-Audio model on Apple Silicon (default)
  bhashini = Bhashini cloud API
  auto     = try MLX first, then Bhashini
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

import chat_service
import database
import voice_service
from schemas import DiagnosisContext, VoiceChatResponse, VoiceSTTResponse, VoiceTTSRequest

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/voice", tags=["voice"])


@router.get("/status", summary="Check STT/TTS provider availability")
def voice_status():
    """
    Returns which voice providers are configured and ready.
    Useful for the frontend to decide whether to show the voice section.

    Response fields:
    - provider:              active VOICE_STT_PROVIDER setting
    - mlx_loaded:            True if MLX Qwen2-Audio model is in memory
    - mlx_error:             error string if MLX failed to load, else null
    - bhashini_configured:   True if BHASHINI_USER_ID + BHASHINI_API_KEY are set
    - stt_ready:             True if at least one STT provider is available
    """
    return voice_service.stt_status()


@router.post("/stt", response_model=VoiceSTTResponse, summary="Speech to text")
async def speech_to_text(
    audio: UploadFile = File(..., description="Audio file (webm from browser MediaRecorder, or wav)"),
    language: str = Form("hi", description="Expected language code: hi / mr / en / ta / te / kn etc."),
):
    """
    Convert farmer's voice recording to text.

    Uses MLX (local, Apple Silicon) or Bhashini (cloud) depending on VOICE_STT_PROVIDER.

    **Errors:**
    - 400 — empty audio file
    - 503 — no STT provider configured
    - 502 — STT provider call failed
    """
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file uploaded.")

    if not voice_service.is_stt_configured():
        raise HTTPException(
            status_code=503,
            detail=(
                "Voice STT not configured. "
                "On Apple Silicon: install mlx-audio (see requirements-mlx.txt). "
                "Otherwise: set BHASHINI_USER_ID and BHASHINI_API_KEY."
            ),
        )

    try:
        text = await voice_service.speech_to_text(audio_bytes, language)
    except voice_service.VoiceNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except voice_service.VoiceServiceError as exc:
        logger.error("STT failed for language=%s: %s", language, exc)
        raise HTTPException(status_code=502, detail=f"Speech recognition failed: {exc}") from exc

    return VoiceSTTResponse(text=text, language=language)


@router.post("/tts", summary="Text to speech (Bhashini)")
async def text_to_speech(request: VoiceTTSRequest):
    """
    Convert text to audio bytes using Bhashini TTS.

    Returns audio/mpeg binary response.

    **503** is returned when Bhashini is not configured — the frontend should fall back
    to the browser's `speechSynthesis` API in this case.

    **Errors:**
    - 503 — Bhashini not configured (BHASHINI_USER_ID / BHASHINI_API_KEY not set)
    - 502 — Bhashini API call failed
    """
    if not request.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty.")

    try:
        audio_bytes = await voice_service.text_to_speech(request.text, request.language)
    except Exception as exc:
        logger.error("TTS failed for language=%s: %s", request.language, exc)
        raise HTTPException(status_code=502, detail=f"TTS failed: {exc}") from exc

    if not audio_bytes:
        # voice_service returns None when Bhashini is not configured
        raise HTTPException(
            status_code=503,
            detail="TTS not available. Set BHASHINI_USER_ID and BHASHINI_API_KEY, or use browser speechSynthesis.",
        )

    return Response(content=audio_bytes, media_type="audio/mpeg")


@router.post("/chat", response_model=VoiceChatResponse, summary="Full voice pipeline")
async def voice_chat(
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(..., description="Farmer's audio recording (webm)"),
    language: str = Form("hi", description="Language code: hi / mr / en"),
    diagnosis_context: Optional[str] = Form(
        None,
        description="JSON-encoded DiagnosisContext from a recent /diagnose call (optional)",
    ),
):
    """
    Full voice pipeline in one request:
    1. Audio → STT (transcript)
    2. Transcript → LLM chat (reply_text)
    3. Reply → TTS (audio available via POST /voice/tts)

    Returns `reply_audio_url` = '/voice/tts' — call it with the reply_text to get audio.
    The frontend plays the audio using the browser or Bhashini TTS.

    **Errors:**
    - 400 — empty audio
    - 503 — STT or chat not configured
    - 502 — STT or LLM provider error
    """
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file.")

    if not voice_service.is_stt_configured():
        raise HTTPException(
            status_code=503,
            detail="Voice STT not configured. See /voice/status for details.",
        )
    if not chat_service.is_chat_configured():
        provider = chat_service.get_provider()
        key_var = chat_service.PROVIDER_KEYS.get(provider, f"{provider.upper()}_API_KEY")
        raise HTTPException(
            status_code=503,
            detail=f"Chat not configured. Set {key_var} in your environment.",
        )

    stt_ok = False
    tts_ok = False

    # --- Step 1: Speech to text ---
    try:
        transcript = await voice_service.speech_to_text(audio_bytes, language)
        stt_ok = bool(transcript)
    except voice_service.VoiceNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except voice_service.VoiceServiceError as exc:
        logger.error("Voice STT error: %s", exc)
        raise HTTPException(status_code=502, detail=f"Speech recognition failed: {exc}") from exc

    # --- Parse optional diagnosis context ---
    ctx: Optional[DiagnosisContext] = None
    if diagnosis_context:
        try:
            ctx = DiagnosisContext(**json.loads(diagnosis_context))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.warning("Could not parse diagnosis_context JSON: %s", exc)
            # Non-fatal — continue without context

    # --- Step 2: LLM chat ---
    try:
        reply_text = chat_service.generate_reply(
            message=transcript,
            language=language,
            diagnosis_context=ctx,
            conversation_history=[],
        )
    except chat_service.ChatNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except chat_service.ChatServiceError as exc:
        logger.error("LLM error in voice chat: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=chat_service.error_message(language),
        ) from exc

    # --- Step 3: Check if TTS is available (non-blocking check) ---
    # Actual TTS is done client-side via POST /voice/tts to keep this response fast.
    import bhashini_service
    tts_ok = bhashini_service.is_voice_configured()

    # Log session in background
    background_tasks.add_task(database.insert_voice_session, language, stt_ok, tts_ok)

    return VoiceChatResponse(
        transcript=transcript,
        reply_text=reply_text,
        reply_audio_url="/voice/tts",
    )
