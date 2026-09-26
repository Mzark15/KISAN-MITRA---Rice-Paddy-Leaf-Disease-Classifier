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

# Which LLM provider to use. Options: sambanova | gemini | openai | anthropic | huggingface
LLM_PROVIDER_ENV = "LLM_PROVIDER"

# Map of provider name → env var that holds its API key
PROVIDER_KEYS: dict[str, str] = {
    "sambanova":   "SAMBANOVA_API_KEY",
    "gemini":      "GEMINI_API_KEY",
    "openai":      "OPENAI_API_KEY",
    "anthropic":   "ANTHROPIC_API_KEY",
    "huggingface": "HUGGINGFACE_API_KEY",
}

# Per-provider default model names (overridable via env)
DEFAULT_MODELS: dict[str, str] = {
    "sambanova":   "Meta-Llama-3.3-70B-Instruct",
    "gemini":      "gemini-3.8-flash",
    "openai":      "gpt-4o-mini",
    "anthropic":   "claude-haiku-4-5-20251001",
    # ":novita" picks a specific backing provider behind HF's router — swap via
    # HUGGINGFACE_MODEL if you want a different one from huggingface.co/models.
    "huggingface": "meta-llama/Llama-3.3-70B-Instruct:novita",
}

HUGGINGFACE_BASE_URL = "https://router.huggingface.co/v1"

SAMBANOVA_BASE_URL = "https://api.sambanova.ai/v1"

MAX_HISTORY_MESSAGES = 6     # Maximum number of past turns sent to the LLM (keeps token usage low)
MAX_OUTPUT_TOKENS    = 600   # Enough room for a detailed, jargon-free explanation (not just 3-5 terse sentences)

DISEASES_FILE = Path(__file__).resolve().parent / "diseases.json"

# ---------------------------------------------------------------------------
# System prompt — the core of the grounding mechanism
# ---------------------------------------------------------------------------

SYSTEM_PROMPT_TEMPLATE = """\
You are Kisan Mitra, a trusted AI advisor for paddy (rice) farmers in India.

STRICT RULES — follow these exactly:
1. Only answer questions about paddy/rice farming. For anything else, politely say you only help with rice crops.
2. Every message below starts with "Farmer language: <code>" (hi=Hindi, mr=Marathi, en=English). You MUST reply
   in that exact language, in its native script (Hindi → Devanagari Hindi, Marathi → Devanagari Marathi). This
   overrides whatever script or language the "Message:" text itself happens to be written in — voice transcripts
   are sometimes mistakenly translated to English before reaching you, but the farmer still spoke their own
   language and expects a reply in it.
3. All treatment advice MUST come only from the KNOWLEDGE BASE below. Never invent dosages or chemicals.
4. The farmer may not be literate and has no agricultural or scientific training. Explain things the way
   you would to a neighbour, not a textbook:
   - Never use technical/scientific jargon (e.g. "pathogen", "fungicide class", "necrosis", "inoculum") without
     immediately explaining it in one simple everyday phrase right after it.
   - Give a real, detailed, practical answer — not a one-line summary. Cover: what is likely happening and why
     (in plain terms), what to do about it step by step, and what to watch out for next. Roughly 6-10 short
     sentences is normal for a real question — do not artificially cut it short.
   - Use short sentences and common words. Prefer concrete instructions ("spray in the early morning or evening,
     not in strong sun") over vague ones ("apply appropriately").
   - It is fine to take a little more space if it means the farmer actually understands what to do.
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


def get_fallback_providers() -> list[str]:
    """
    Return the ordered list of fallback providers from LLM_FALLBACK_PROVIDERS
    (comma-separated, e.g. "gemini,openai"). Empty by default — fallback is opt-in.
    """
    raw = os.environ.get("LLM_FALLBACK_PROVIDERS", "")
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def _is_provider_configured(provider: str) -> bool:
    key_name = PROVIDER_KEYS.get(provider)
    return bool(key_name and os.environ.get(key_name))


def _provider_chain() -> list[str]:
    """
    Ordered, de-duplicated list: primary provider first, then any configured
    fallback providers. Providers with no API key set are skipped entirely.
    """
    chain = [get_provider(), *get_fallback_providers()]
    seen: set[str] = set()
    ordered: list[str] = []
    for p in chain:
        if p not in seen:
            seen.add(p)
            ordered.append(p)
    return ordered


def is_chat_configured() -> bool:
    """True when at least one provider in the chain (primary or fallback) has a key set."""
    return any(_is_provider_configured(p) for p in _provider_chain())


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


def _strip_leaked_preamble(reply: str) -> str:
    """
    Some less instruction-tuned models (seen with Hugging Face-hosted models)
    echo back the internal message framing we send in — e.g. a reply starting
    with "Farmer language: hi" or "Message: ..." — instead of just answering.
    Strip that leaked scaffolding so it never reaches the farmer.
    """
    import re
    cleaned = reply
    for _ in range(2):  # strip up to two leaked lines (language tag, then message echo)
        cleaned = re.sub(
            r"^\s*(Farmer language:\s*\S+|Message:\s*.*|Diagnosis context:\s*.*)\s*\n+",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
    return cleaned.strip() or reply.strip()  # never return empty — fall back to original


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


def _generate_huggingface(user_msg: str, history: list[ChatMessage]) -> str:
    """
    Call Hugging Face's Inference Providers router (OpenAI-compatible), which
    fronts many hosted models/providers under one free-tier token. Same client
    pattern as SambaNova since both speak the OpenAI chat-completions format.
    """
    from openai import OpenAI, OpenAIError

    api_key = os.environ.get("HUGGINGFACE_API_KEY")
    if not api_key:
        raise ChatNotConfiguredError("HUGGINGFACE_API_KEY not set.")

    base_url = os.environ.get("HUGGINGFACE_BASE_URL", HUGGINGFACE_BASE_URL)
    model    = os.environ.get("HUGGINGFACE_MODEL", DEFAULT_MODELS["huggingface"])

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
        raise ChatServiceError(f"Hugging Face API error: {exc}") from exc

    if not reply:
        raise ChatServiceError("Empty response from Hugging Face.")
    return reply


def _generate_gemini(user_msg: str, history: list[ChatMessage]) -> str:
    """
    Call Google Gemini API via the google-genai SDK (the old
    google-generativeai package is fully deprecated and its models 404).
    """
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ChatNotConfiguredError("GEMINI_API_KEY not set.")

    model_name = os.environ.get("GEMINI_MODEL", DEFAULT_MODELS["gemini"])

    try:
        client = genai.Client(api_key=api_key)
        gemini_history = [
            types.Content(
                role="user" if h.role == "user" else "model",
                parts=[types.Part(text=h.content)],
            )
            for h in history
        ]
        chat = client.chats.create(
            model=model_name,
            history=gemini_history,
            config=types.GenerateContentConfig(
                system_instruction=_get_system_prompt(),
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ),
        )
        resp = chat.send_message(user_msg)
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
    Generate a grounded reply, trying the primary LLM provider first, then
    falling back through LLM_FALLBACK_PROVIDERS (in order) if the primary
    fails with a ChatServiceError (network error, rate limit, empty reply, etc).

    This matters because free-tier providers like SambaNova occasionally return
    HTTP 429 "high demand" errors that have nothing to do with your account —
    the whole shared model is briefly overloaded. Without a fallback, that
    turns into a dead end for the farmer. With one, the app quietly tries the
    next configured provider and the farmer just gets an answer.

    Raises:
        ChatNotConfiguredError: No provider in the chain has an API key set.
                                Caller should return HTTP 503.
        ChatServiceError:       Every configured provider in the chain failed.
                                Caller should return HTTP 502.
    """
    generators = {
        "sambanova":   _generate_sambanova,
        "gemini":      _generate_gemini,
        "openai":      _generate_openai,
        "anthropic":   _generate_anthropic,
        "huggingface": _generate_huggingface,
    }

    chain = [p for p in _provider_chain() if p in generators]
    configured_chain = [p for p in chain if _is_provider_configured(p)]

    if not configured_chain:
        provider = get_provider()
        key_var  = PROVIDER_KEYS.get(provider, f"{provider.upper()}_API_KEY")
        raise ChatNotConfiguredError(f"Chat not configured. Set {key_var}.")

    history  = trim_history(conversation_history)
    user_msg = _build_user_message(message, language, diagnosis_context)

    last_error: Optional[ChatServiceError] = None
    for i, provider in enumerate(configured_chain):
        fn = generators[provider]
        try:
            reply = _strip_leaked_preamble(fn(user_msg, history))
            if i > 0:
                logger.warning(
                    "Chat fallback: '%s' failed, '%s' handled this reply instead.",
                    configured_chain[0], provider,
                )
            return reply
        except ChatServiceError as exc:
            last_error = exc
            logger.warning("Provider '%s' failed (%s), trying next in chain...", provider, exc)
            continue

    # Every provider in the chain failed.
    raise last_error
