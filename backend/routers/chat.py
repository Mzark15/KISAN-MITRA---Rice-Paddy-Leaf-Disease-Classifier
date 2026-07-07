"""
routers/chat.py — POST /chat

Text chat grounded in diseases.json. The LLM (SambaNova / Gemini / OpenAI / Anthropic)
is only used for natural language generation — all treatment advice is injected from the
vetted knowledge base, so the AI cannot hallucinate pesticide doses.

To switch LLM provider: set LLM_PROVIDER env var (sambanova | gemini | openai | anthropic)
and the matching API key.
"""

import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException

import chat_service
import database
from schemas import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/chat", response_model=ChatResponse, summary="Ask the AI crop advisor")
async def chat(request: ChatRequest, background_tasks: BackgroundTasks):
    """
    Send a text message and get a reply in the same language (hi / mr / en).

    Pass `diagnosis_context` (disease + confidence from a recent /diagnose call)
    to get advice specific to the detected disease.

    Pass `conversation_history` (last few turns) so the AI has context.
    The service automatically trims history to the last 6 turns to stay within token limits.

    **Errors:**
    - 400 — empty message
    - 503 — no LLM API key configured (set SAMBANOVA_API_KEY or LLM_PROVIDER + key)
    - 502 — LLM API call failed (provider error, rate limit, etc.)
    """
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    if not chat_service.is_chat_configured():
        provider = chat_service.get_provider()
        key_var = chat_service.PROVIDER_KEYS.get(provider, f"{provider.upper()}_API_KEY")
        raise HTTPException(
            status_code=503,
            detail=f"Chat not configured. Set {key_var} in your environment.",
        )

    try:
        reply = chat_service.generate_reply(
            message=request.message.strip(),
            language=request.language,
            diagnosis_context=request.diagnosis_context,
            conversation_history=request.conversation_history,
        )
    except chat_service.ChatNotConfiguredError as exc:
        # Should not reach here (checked above), but handle defensively
        logger.warning("ChatNotConfiguredError in router: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except chat_service.ChatServiceError as exc:
        # LLM API error — return a friendly message in the farmer's language
        logger.error("LLM API error for language=%s: %s", request.language, exc)
        raise HTTPException(
            status_code=502,
            detail=chat_service.error_message(request.language),
        ) from exc

    # Log chat session to DB in the background so it doesn't slow the response
    background_tasks.add_task(
        database.insert_chat_session,
        request.language,
        len(request.conversation_history) + 1,
        request.diagnosis_context is not None,
    )

    return ChatResponse(reply=reply, language=request.language, grounded=True)
