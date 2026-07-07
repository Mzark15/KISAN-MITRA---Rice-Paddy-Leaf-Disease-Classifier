"""SambaNova LLM chat grounded in diseases.json."""

import json
import logging
import os
from pathlib import Path
from typing import Optional

from schemas import ChatMessage, DiagnosisContext

logger = logging.getLogger(__name__)

DISEASES_FILE = Path(__file__).resolve().parent / "diseases.json"
MAX_HISTORY_MESSAGES = 6
MAX_OUTPUT_TOKENS = 300
DEFAULT_SAMBANOVA_BASE_URL = "https://api.sambanova.ai/v1"
DEFAULT_SAMBANOVA_MODEL = "Meta-Llama-3.1-8B-Instruct"

SYSTEM_PROMPT_TEMPLATE = '''You are Kisan Mitra, a trusted AI advisor for paddy (rice) farmers in India.

STRICT RULES:
1. Only answer questions about paddy/rice farming. For anything else, say you only help with rice crops.
2. Always reply in the SAME language the farmer used. Hindi → Hindi. Marathi → Marathi. English → English.
3. All treatment advice MUST come only from the KNOWLEDGE BASE below. Never invent dosages or chemicals.
4. Keep answers to 3–5 sentences. Simple words. No jargon.
5. For Tungro or Bacterial Panicle Blight, always end with: "अपने नजदीकी KVK या कृषि अधिकारी से सलाह लें।"
6. If diagnosis_context is given, give advice specific to that disease.

--- KNOWLEDGE BASE ---
{diseases_json}
--- END KNOWLEDGE BASE ---
'''

ERROR_MESSAGES = {
    "hi": "क्षमा करें, अभी उत्तर नहीं दे पा रहे। कृपया थोड़ी देर बाद फिर कोशिश करें।",
    "mr": "क्षमस्व, आत्ता उत्तर देऊ शकत नाही. कृपया थोड्या वेळाने पुन्हा प्रयत्न करा.",
    "en": "Sorry, we could not get an answer right now. Please try again later.",
}

PROVIDER_KEYS = {
    "sambanova": "SAMBANOVA_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}

_diseases_json: Optional[str] = None


class ChatNotConfiguredError(Exception):
    """No LLM provider API key configured."""


class ChatServiceError(Exception):
    """LLM API call failed."""


def init_knowledge_base() -> None:
    global _diseases_json
    with open(DISEASES_FILE, "r", encoding="utf-8") as f:
        diseases = json.load(f)
    _diseases_json = json.dumps(diseases, ensure_ascii=False, indent=2)
    logger.info("Loaded diseases.json for chat grounding (%d diseases)", len(diseases))


def get_system_prompt() -> str:
    if _diseases_json is None:
        init_knowledge_base()
    return SYSTEM_PROMPT_TEMPLATE.format(diseases_json=_diseases_json)


def get_provider() -> str:
    return os.environ.get("LLM_PROVIDER", "sambanova").lower()


def is_chat_configured() -> bool:
    provider = get_provider()
    key_name = PROVIDER_KEYS.get(provider)
    return bool(key_name and os.environ.get(key_name))


def trim_history(history: list[ChatMessage]) -> list[ChatMessage]:
    return history[-MAX_HISTORY_MESSAGES:]


def _build_user_message(
    message: str,
    language: str,
    diagnosis_context: Optional[DiagnosisContext],
) -> str:
    parts = [f"Farmer language code: {language}", f"Farmer message: {message}"]
    if diagnosis_context:
        parts.append(
            "diagnosis_context: "
            f"{diagnosis_context.disease} (confidence {diagnosis_context.confidence}%)"
        )
    return "\n".join(parts)


def _messages_for_chat_api(
    user_message: str, history: list[ChatMessage]
) -> list[dict]:
    messages = [{"role": "system", "content": get_system_prompt()}]
    for item in history:
        role = "assistant" if item.role == "assistant" else "user"
        messages.append({"role": role, "content": item.content})
    messages.append({"role": "user", "content": user_message})
    return messages


def _generate_sambanova(user_message: str, history: list[ChatMessage]) -> str:
    from openai import OpenAI

    api_key = os.environ.get("SAMBANOVA_API_KEY")
    if not api_key:
        raise ChatNotConfiguredError()

    base_url = os.environ.get("SAMBANOVA_BASE_URL", DEFAULT_SAMBANOVA_BASE_URL)
    model = os.environ.get("SAMBANOVA_MODEL", DEFAULT_SAMBANOVA_MODEL)

    client = OpenAI(base_url=base_url, api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=_messages_for_chat_api(user_message, history),
        max_tokens=MAX_OUTPUT_TOKENS,
        temperature=0.2,
    )
    reply = (response.choices[0].message.content or "").strip()
    if not reply:
        raise ChatServiceError("Empty response from SambaNova")
    return reply


def _generate_gemini(user_message: str, history: list[ChatMessage]) -> str:
    import google.generativeai as genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ChatNotConfiguredError()

    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name="gemini-2.0-flash",
        system_instruction=get_system_prompt(),
    )

    gemini_history = []
    for item in history:
        role = "user" if item.role == "user" else "model"
        gemini_history.append({"role": role, "parts": [item.content]})

    if gemini_history:
        chat = model.start_chat(history=gemini_history)
        response = chat.send_message(
            user_message,
            generation_config={"max_output_tokens": MAX_OUTPUT_TOKENS},
        )
    else:
        response = model.generate_content(
            user_message,
            generation_config={"max_output_tokens": MAX_OUTPUT_TOKENS},
        )
    reply = (response.text or "").strip()
    if not reply:
        raise ChatServiceError("Empty response from Gemini")
    return reply


def _generate_openai(user_message: str, history: list[ChatMessage]) -> str:
    from openai import OpenAI

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ChatNotConfiguredError()

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=_messages_for_chat_api(user_message, history),
        max_tokens=MAX_OUTPUT_TOKENS,
    )
    reply = (response.choices[0].message.content or "").strip()
    if not reply:
        raise ChatServiceError("Empty response from OpenAI")
    return reply


def _generate_anthropic(user_message: str, history: list[ChatMessage]) -> str:
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ChatNotConfiguredError()

    client = anthropic.Anthropic(api_key=api_key)
    anthropic_messages = []
    for item in history:
        role = "assistant" if item.role == "assistant" else "user"
        anthropic_messages.append({"role": role, "content": item.content})
    anthropic_messages.append({"role": "user", "content": user_message})

    response = client.messages.create(
        model="claude-haiku-4-5",
        max_tokens=MAX_OUTPUT_TOKENS,
        system=get_system_prompt(),
        messages=anthropic_messages,
    )
    parts = [block.text for block in response.content if hasattr(block, "text")]
    reply = "".join(parts).strip()
    if not reply:
        raise ChatServiceError("Empty response from Anthropic")
    return reply


def generate_reply(
    message: str,
    language: str,
    diagnosis_context: Optional[DiagnosisContext],
    conversation_history: list[ChatMessage],
) -> str:
    if not is_chat_configured():
        raise ChatNotConfiguredError(
            "Chat not configured. Set SAMBANOVA_API_KEY (or LLM_PROVIDER and matching key)."
        )

    provider = get_provider()
    trimmed = trim_history(conversation_history)
    user_message = _build_user_message(message, language, diagnosis_context)

    try:
        if provider == "sambanova":
            return _generate_sambanova(user_message, trimmed)
        if provider == "gemini":
            return _generate_gemini(user_message, trimmed)
        if provider == "openai":
            return _generate_openai(user_message, trimmed)
        if provider == "anthropic":
            return _generate_anthropic(user_message, trimmed)
        raise ChatNotConfiguredError(f"Unknown LLM_PROVIDER: {provider}")
    except ChatNotConfiguredError:
        raise
    except Exception as exc:
        logger.exception("LLM API error (%s)", provider)
        raise ChatServiceError(str(exc)) from exc


def error_message(language: str) -> str:
    return ERROR_MESSAGES.get(language, ERROR_MESSAGES["en"])
