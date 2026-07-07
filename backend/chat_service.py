"""
chat_service.py — LLM chat grounded in diseases.json

Supports four providers: SambaNova (default), Gemini, OpenAI, Anthropic.
Switch provider: set LLM_PROVIDER env var.
Switch model:    set SAMBANOVA_MODEL / GEMINI_MODEL / OPENAI_MODEL / ANTHROPIC_MODEL env var.

The system prompt injects the full diseases.json so the AI can only give advice
that exists in the knowledge base — it cannot hallucinate pesticide doses or chemicals.

To add a new provider:
  1. Add its key name to PROVIDER_KEYS below.
  2. Write a _generate_<provider>() function following the existing pattern.
  3. Add a branch to generate_reply().
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

from schemas import ChatMessage, DiagnosisContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration — change these env vars, not the code
# ---------------------------------------------------------------------------

# Which LLM provider to use. Options: sambanova | gemini | openai | anthropic
LLM_PROVIDER_ENV = "LLM_PROVIDER"

# Map of provider name → env var that holds its API key
PROVIDER_KEYS: dict[str, str] = {
    "sambanova": "SAMBANOVA_API_KEY",
    "gemini":    "GEMINI_API_KEY",
    "openai":    "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}

# Per-provider default model names (overridable via env)
DEFAULT_MODELS: dict[str, str] = {
    "sambanova": "Meta-Llama-3.1-8B-Instruct",
    "gemini":    "gemini-2.0-flash",
    "openai":    "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5",
}

SAMBANOVA_BASE_URL = "https://api.sambanova.ai/v1"

MAX_HISTORY_MESSAGES = 6     # Maximum number of past turns sent to the LLM (keeps token usage low)
MAX_OUTPUT_TOKENS    = 300   # Short answers only — farmers need simple, actionable advice

DISEASES_FILE = Path(__file__).resolve().parent / "diseases.json"

# ---------------------------------------------------------------------------
# System prompt — the core of the grounding mechanism
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = """\
You are Kisan Mitra, a trusted AI advisor for paddy (rice) farmers in India.

STRICT RULES — follow these exactly:
1. Only answer questions about paddy/rice farming. For anything else, politely say you only help with rice crops.
2. Always reply in the SAME language the farmer used. Hindi → Hindi. Marathi → Marathi. English → English.
3. All treatment advice MUST come only from the KNOWLEDGE BASE below. Never invent dosages or chemicals.
4. Keep answers to 3–5 sentences. Simple words. No jargon.
5. For Tungro or Bacterial Panicle Blight, always end with: "अपने नजदीकी KVK या कृषि अधिकारी से सलाह लें।"
6. If a diagnosis_context is given in the message, give advice specific to that disease.

--- KNOWLEDGE BASE ---
{diseases_json}
--- END KNOWLEDGE BASE ---
"""

# Fallback error messages per language (used when the LLM call fails)
ERROR_MESSAGES: dict[str, str] = {
    "hi": "क्षमा करें, अभी उत्तर नहीं दे पा रहे। कृपया थोड़ी देर बाद फिर कोशिश करें।",
    "mr": "क्षमस्व, आत्ता उत्तर देऊ शकत नाही. कृपया थोड्या वेळाने पुन्हा प्रयत्न करा.",
    "en": "Sorry, we could not get an answer right now. Please try again later.",
}

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ChatNotConfiguredError(Exception):
    """Raised when no API key is set for the active provider."""

class ChatServiceError(Exception):
    """Raised when the LLM API call fails (network error, rate limit, bad response, etc.)."""

# ---------------------------------------------------------------------------
# Internal state
# ---------------------------------------------------------------------------

_diseases_json: Optional[str] = None   # Loaded once at startup by init_knowledge_base()


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def init_knowledge_base() -> None:
    """
    Load diseases.json and cache it as a JSON string for injection into the system prompt.
    Called once at startup from main.py lifespan.
    Raises FileNotFoundError if diseases.json is missing.
    """
    global _diseases_json
    if not DISEASES_FILE.exists():
        raise FileNotFoundError(
            f"diseases.json not found at {DISEASES_FILE}. "
            "This file must exist for the chat to work safely."
        )
    with open(DISEASES_FILE, "r", encoding="utf-8") as f:
        diseases = json.load(f)
    _diseases_json = json.dumps(diseases, ensure_ascii=False, indent=2)
    logger.info("Knowledge base loaded: %d diseases", len(diseases))


def get_provider() -> str:
    """Return the active LLM provider name (from LLM_PROVIDER env var, default 'sambanova')."""
    return os.environ.get(LLM_PROVIDER_ENV, "sambanova").lower()


def is_chat_configured() -> bool:
    """True when the API key for the active provider is set."""
    provider  = get_provider()
    key_name  = PROVIDER_KEYS.get(provider)
    return bool(key_name and os.environ.get(key_name))


def error_message(language: str) -> str:
    """Return a farmer-friendly error message in the given language."""
    return ERROR_MESSAGES.get(language, ERROR_MESSAGES["en"])


def trim_history(history: list[ChatMessage]) -> list[ChatMessage]:
    """Keep only the last MAX_HISTORY_MESSAGES turns to avoid token limit issues."""
    return history[-MAX_HISTORY_MESSAGES:]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _get_system_prompt() -> str:
    if _diseases_json is None:
        # Lazy-load if init_knowledge_base() was not called at startup
        init_knowledge_base()
    return SYSTEM_PROMPT_TEMPLATE.format(diseases_json=_diseases_json)


def _build_user_message(
    message: str,
    language: str,
    diagnosis_context: Optional[DiagnosisContext],
) -> str:
    """
    Wrap the farmer's message with metadata so the LLM has full context.
    The language code reminds the model which language to reply in.
    """
    parts = [f"Farmer language: {language}", f"Message: {message}"]
    if diagnosis_context:
        parts.append(
            f"Diagnosis context: {diagnosis_context.disease} "
            f"(confidence {diagnosis_context.confidence:.1f}%)"
        )
    return "\n".join(parts)


def _openai_messages(user_msg: str, history: list[ChatMessage]) -> list[dict]:
    """Build the messages array for OpenAI-compatible chat APIs (OpenAI, SambaNova)."""
    messages = [{"role": "system", "content": _get_system_prompt()}]
    for h in history:
        messages.append({"role": h.role, "content": h.content})
    messages.append({"role": "user", "content": user_msg})
    return messages


# ---------------------------------------------------------------------------
# Provider-specific generators
# ---------------------------------------------------------------------------

def _generate_sambanova(user_msg: str, history: list[ChatMessage]) -> str:
    """Call SambaNova's OpenAI-compatible API."""
    from openai import OpenAI, OpenAIError

    api_key  = os.environ.get("SAMBANOVA_API_KEY")
    if not api_key:
        raise ChatNotConfiguredError("SAMBANOVA_API_KEY not set.")

    base_url = os.environ.get("SAMBANOVA_BASE_URL", SAMBANOVA_BASE_URL)
    model    = os.environ.get("SAMBANOVA_MODEL", DEFAULT_MODELS["sambanova"])

    try:
        client   = OpenAI(base_url=base_url, api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=_openai_messages(user_msg, history),
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=0.2,
        )
        reply = (response.choices[0].message.content or "").strip()
    except OpenAIError as exc:
        raise ChatServiceError(f"SambaNova API error: {exc}") from exc

    if not reply:
        raise ChatServiceError("Empty response from SambaNova.")
    return reply


def _generate_gemini(user_msg: str, history: list[ChatMessage]) -> str:
    """Call Google Gemini API."""
    import google.generativeai as genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ChatNotConfiguredError("GEMINI_API_KEY not set.")

    model_name = os.environ.get("GEMINI_MODEL", DEFAULT_MODELS["gemini"])

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=_get_system_prompt(),
        )
        gemini_history = [
            {"role": "user" if h.role == "user" else "model", "parts": [h.content]}
            for h in history
        ]
        if gemini_history:
            chat = model.start_chat(history=gemini_history)
            resp = chat.send_message(
                user_msg, generation_config={"max_output_tokens": MAX_OUTPUT_TOKENS}
            )
        else:
            resp = model.generate_content(
                user_msg, generation_config={"max_output_tokens": MAX_OUTPUT_TOKENS}
            )
        reply = (resp.text or "").strip()
    except Exception as exc:
        raise ChatServiceError(f"Gemini API error: {exc}") from exc

    if not reply:
        raise ChatServiceError("Empty response from Gemini.")
    return reply


def _generate_openai(user_msg: str, history: list[ChatMessage]) -> str:
    """Call OpenAI API (gpt-4o-mini by default)."""
    from openai import OpenAI, OpenAIError

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ChatNotConfiguredError("OPENAI_API_KEY not set.")

    model = os.environ.get("OPENAI_MODEL", DEFAULT_MODELS["openai"])

    try:
        client   = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=_openai_messages(user_msg, history),
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=0.2,
        )
        reply = (response.choices[0].message.content or "").strip()
    except OpenAIError as exc:
        raise ChatServiceError(f"OpenAI API error: {exc}") from exc

    if not reply:
        raise ChatServiceError("Empty response from OpenAI.")
    return reply


def _generate_anthropic(user_msg: str, history: list[ChatMessage]) -> str:
    """Call Anthropic API (claude-haiku by default)."""
    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ChatNotConfiguredError("ANTHROPIC_API_KEY not set.")

    model = os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODELS["anthropic"])

    try:
        client = anthropic.Anthropic(api_key=api_key)
        msgs   = [{"role": h.role, "content": h.content} for h in history]
        msgs.append({"role": "user", "content": user_msg})
        resp   = client.messages.create(
            model=model,
            max_tokens=MAX_OUTPUT_TOKENS,
            system=_get_system_prompt(),
            messages=msgs,
        )
        reply = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
    except anthropic.APIError as exc:
        raise ChatServiceError(f"Anthropic API error: {exc}") from exc

    if not reply:
        raise ChatServiceError("Empty response from Anthropic.")
    return reply


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_reply(
    message: str,
    language: str,
    diagnosis_context: Optional[DiagnosisContext],
    conversation_history: list[ChatMessage],
) -> str:
    """
    Generate a grounded reply from the active LLM provider.

    Raises:
        ChatNotConfiguredError: No API key set. Caller should return HTTP 503.
        ChatServiceError:       Provider call failed. Caller should return HTTP 502.
    """
    if not is_chat_configured():
        provider = get_provider()
        key_var  = PROVIDER_KEYS.get(provider, f"{provider.upper()}_API_KEY")
        raise ChatNotConfiguredError(f"Chat not configured. Set {key_var}.")

    provider   = get_provider()
    history    = trim_history(conversation_history)
    user_msg   = _build_user_message(message, language, diagnosis_context)

    generators = {
        "sambanova": _generate_sambanova,
        "gemini":    _generate_gemini,
        "openai":    _generate_openai,
        "anthropic": _generate_anthropic,
    }
    fn = generators.get(provider)
    if fn is None:
        raise ChatNotConfiguredError(
            f"Unknown LLM_PROVIDER '{provider}'. "
            f"Valid options: {', '.join(generators)}"
        )

    return fn(user_msg, history)
