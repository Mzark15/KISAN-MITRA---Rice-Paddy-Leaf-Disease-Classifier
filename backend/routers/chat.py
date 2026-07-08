"""
routers/chat.py — POST /chat  (LangGraph + Groq)
"""

import logging
import os
from fastapi import APIRouter, BackgroundTasks, HTTPException
import chat_service
import database
from schemas import ChatRequest, ChatResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/chat/debug", summary="Check chat config")
def chat_debug():
    """Visit http://localhost:8000/chat/debug to verify Groq key is loaded."""
    provider = chat_service.get_provider()
    key_var  = chat_service.PROVIDER_KEYS.get(provider, "")
    key_val  = os.environ.get(key_var, "")
    return {
        "provider":        provider,
        "key_env_var":     key_var,
        "key_loaded":      bool(key_val),
        "key_prefix":      key_val[:8] + "…" if key_val else "NOT SET",
        "model":           os.environ.get("GROQ_MODEL", chat_service.DEFAULT_MODELS.get(provider)),
        "chat_configured": chat_service.is_chat_configured(),
    }


@router.get("/chat/test", summary="Test Groq connection directly")
def chat_test():
    """Calls Groq directly — bypasses LangGraph. Visit http://localhost:8000/chat/test"""
    from openai import OpenAI

    api_key = os.environ.get("GROQ_API_KEY", "")
    model   = os.environ.get("GROQ_MODEL", chat_service.DEFAULT_MODELS["groq"])

    if not api_key:
        return {"status": "error", "reason": "GROQ_API_KEY not set"}

    try:
        client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key)
        resp   = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Say hello in one word."}],
            max_tokens=10,
            stream=False,
        )
        reply = (resp.choices[0].message.content or "").strip()
        return {"status": "ok", "reply": reply, "model": model}
    except Exception as exc:
        return {"status": "error", "error_type": type(exc).__name__, "detail": str(exc)}


@router.post("/chat", response_model=ChatResponse, summary="Ask the AI crop advisor")
async def chat(request: ChatRequest, background_tasks: BackgroundTasks):
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    if not chat_service.is_chat_configured():
        provider = chat_service.get_provider()
        key_var  = chat_service.PROVIDER_KEYS.get(provider, f"{provider.upper()}_API_KEY")
        raise HTTPException(
            status_code=503,
            detail=f"Chat not configured. Set {key_var} in your .env file.",
        )

    try:
        reply = chat_service.generate_reply(
            message=request.message.strip(),
            language=request.language,
            diagnosis_context=request.diagnosis_context,
            conversation_history=request.conversation_history,
        )
    except chat_service.ChatNotConfiguredError as exc:
        logger.error("ChatNotConfiguredError: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except chat_service.ChatServiceError as exc:
        logger.error("Groq call failed [lang=%s]: %s", request.language, exc)
        raise HTTPException(
            status_code=502,
            detail=chat_service.error_message(request.language),
        ) from exc

    background_tasks.add_task(
        database.insert_chat_session,
        request.language,
        len(request.conversation_history) + 1,
        request.diagnosis_context is not None,
    )

    return ChatResponse(reply=reply, language=request.language, grounded=True)
