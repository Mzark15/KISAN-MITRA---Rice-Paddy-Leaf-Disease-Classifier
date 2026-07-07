import json
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

import chat_service
import database
import voice_service
from schemas import (
    DiagnosisContext,
    VoiceChatResponse,
    VoiceSTTResponse,
    VoiceTTSRequest,
)

router = APIRouter(prefix="/voice", tags=["voice"])


@router.get("/status")
def voice_status():
    return voice_service.stt_status()


@router.post("/stt", response_model=VoiceSTTResponse)
async def speech_to_text(
    audio: UploadFile = File(...),
    language: str = Form("hi"),
):
    if not voice_service.is_stt_configured():
        raise HTTPException(
            status_code=503,
            detail="Voice STT not configured. Set VOICE_STT_PROVIDER=mlx (Apple Silicon) or Bhashini keys.",
        )

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file.")

    try:
        text = await voice_service.speech_to_text(audio_bytes, language)
    except voice_service.VoiceNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except voice_service.VoiceServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return VoiceSTTResponse(text=text, language=language)


@router.post("/tts")
async def text_to_speech(request: VoiceTTSRequest):
    try:
        audio_bytes = await voice_service.text_to_speech(request.text, request.language)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if not audio_bytes:
        raise HTTPException(
            status_code=503,
            detail="TTS unavailable. Use browser speech synthesis.",
        )

    return Response(content=audio_bytes, media_type="audio/mpeg")


@router.post("/chat", response_model=VoiceChatResponse)
async def voice_chat(
    background_tasks: BackgroundTasks,
    audio: UploadFile = File(...),
    language: str = Form("hi"),
    diagnosis_context: Optional[str] = Form(None),
):
    if not voice_service.is_stt_configured():
        raise HTTPException(
            status_code=503,
            detail="Voice STT not configured. Set VOICE_STT_PROVIDER=mlx or Bhashini keys.",
        )

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="Empty audio file.")

    stt_ok = False
    tts_ok = False
    try:
        transcript = await voice_service.speech_to_text(audio_bytes, language)
        stt_ok = bool(transcript)

        ctx: Optional[DiagnosisContext] = None
        if diagnosis_context:
            try:
                ctx = DiagnosisContext(**json.loads(diagnosis_context))
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

        if not chat_service.is_chat_configured():
            raise HTTPException(
                status_code=503,
                detail="Chat not configured. Set SAMBANOVA_API_KEY.",
            )

        reply_text = chat_service.generate_reply(
            message=transcript,
            language=language,
            diagnosis_context=ctx,
            conversation_history=[],
        )

        audio_out = await voice_service.text_to_speech(reply_text, language)
        tts_ok = audio_out is not None

        background_tasks.add_task(
            database.insert_voice_session, language, stt_ok, tts_ok
        )

        return VoiceChatResponse(
            transcript=transcript,
            reply_text=reply_text,
            reply_audio_url="/voice/tts",
        )
    except HTTPException:
        background_tasks.add_task(
            database.insert_voice_session, language, stt_ok, tts_ok
        )
        raise
    except voice_service.VoiceNotConfiguredError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (voice_service.VoiceServiceError, chat_service.ChatServiceError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except chat_service.ChatNotConfiguredError:
        raise HTTPException(
            status_code=503,
            detail="Chat not configured. Set SAMBANOVA_API_KEY.",
        ) from None
