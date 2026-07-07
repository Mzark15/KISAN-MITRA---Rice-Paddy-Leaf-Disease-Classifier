from fastapi import APIRouter, BackgroundTasks, HTTPException

import chat_service
import database
from schemas import ChatRequest, ChatResponse

router = APIRouter()


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, background_tasks: BackgroundTasks):
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    if not chat_service.is_chat_configured():
        raise HTTPException(
            status_code=503,
            detail="Chat not configured. Set SAMBANOVA_API_KEY.",
        )

    try:
        reply = chat_service.generate_reply(
            message=request.message.strip(),
            language=request.language,
            diagnosis_context=request.diagnosis_context,
            conversation_history=request.conversation_history,
        )
    except chat_service.ChatNotConfiguredError:
        raise HTTPException(
            status_code=503,
            detail="Chat not configured. Set SAMBANOVA_API_KEY.",
        ) from None
    except chat_service.ChatServiceError:
        raise HTTPException(
            status_code=502,
            detail=chat_service.error_message(request.language),
        ) from None

    background_tasks.add_task(
        database.insert_chat_session,
        request.language,
        len(request.conversation_history) + 1,
        request.diagnosis_context is not None,
    )

    return ChatResponse(
        reply=reply,
        language=request.language,
        grounded=True,
    )
