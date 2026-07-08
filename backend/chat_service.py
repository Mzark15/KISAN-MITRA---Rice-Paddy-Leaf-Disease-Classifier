"""
chat_service.py — Simple Groq chat for Kisan Mitra (no LangGraph)

Flow:
  1. Build a system prompt based on whether a diagnosis exists
  2. Call Groq API
  3. Return reply

To change model: set GROQ_MODEL env var.
To change provider: set LLM_PROVIDER to openai / anthropic / gemini.
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL    = "meta-llama/llama-4-scout-17b-16e-instruct"
MAX_TOKENS    = 1024
MAX_HISTORY   = 6

DISEASES_FILE = Path(__file__).resolve().parent / "diseases.json"

PROVIDER_KEYS = {
    "groq":      "***REMOVED***",
    "openai":    "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini":    "GEMINI_API_KEY",
}

DEFAULT_MODELS = {
    "groq":      "openai/gpt-oss-120b",
    "openai":    "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5",
    "gemini":    "gemini-2.0-flash",
}

ERROR_MESSAGES = {
    "hi": "क्षमा करें, अभी उत्तर नहीं दे पा रहे। कृपया थोड़ी देर बाद फिर कोशिश करें।",
    "mr": "क्षमस्व, आत्ता उत्तर देऊ शकत नाही. कृपया थोड्या वेळाने पुन्हा प्रयत्न करा.",
    "en": "Sorry, we could not get an answer right now. Please try again later.",
}

LANGUAGE_NAMES = {"hi": "Hindi", "mr": "Marathi", "en": "English"}

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ChatNotConfiguredError(Exception):
    pass

class ChatServiceError(Exception):
    pass

# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------

_diseases: Optional[dict] = None


def init_knowledge_base() -> None:
    global _diseases
    if not DISEASES_FILE.exists():
        raise FileNotFoundError(f"diseases.json not found at {DISEASES_FILE}")
    with open(DISEASES_FILE, "r", encoding="utf-8") as f:
        _diseases = json.load(f)
    logger.info("Knowledge base loaded: %d diseases", len(_diseases))


def _get_diseases() -> dict:
    if _diseases is None:
        init_knowledge_base()
    return _diseases

# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_provider() -> str:
    return os.environ.get("LLM_PROVIDER", "groq").lower()


def is_chat_configured() -> bool:
    key_name = PROVIDER_KEYS.get(get_provider())
    return bool(key_name and os.environ.get(key_name))


def error_message(language: str) -> str:
    return ERROR_MESSAGES.get(language, ERROR_MESSAGES["en"])


# ---------------------------------------------------------------------------
# System prompt — dynamic based on diagnosis
# ---------------------------------------------------------------------------

def _build_system_prompt(language: str, disease: Optional[str],
                          confidence: float) -> str:
    lang = LANGUAGE_NAMES.get(language, "English")

    if disease and disease != "Normal":
        entry = _get_diseases().get(disease, {})
        return f"""\
You are Kisan Mitra, a trusted AI advisor for paddy (rice) farmers in India.

The farmer's plant has been diagnosed with: {disease}
Confidence: {confidence:.1f}%

RULES:
1. Reply in {lang}. Match the farmer's language exactly.
2. Give advice ONLY based on the treatment data below. Never invent dosages.
3. Keep answers to 4-6 sentences. Simple words only.
4. For Tungro or Bacterial Panicle Blight, end with:
   "अपने नजदीकी KVK या कृषि विशेषज्ञ से मिलें।"

DISEASE: {disease}
Cause: {entry.get('cause', 'Unknown')}
Severity: {', '.join(entry.get('severity_levels', [])) or 'varies'}
Organic treatment: {entry.get('organic_treatment', '')}
Chemical treatment: {entry.get('chemical_treatment', '')}
Precautions: {entry.get('precautions') or 'Follow label instructions.'}
"""
    else:
        disease_list = ", ".join(_get_diseases().keys())
        return f"""\
You are Kisan Mitra, a trusted AI advisor for paddy (rice) farmers in India.

RULES:
1. Reply in {lang}. Match the farmer's language exactly.
2. Only answer questions about paddy/rice farming. Politely decline other topics.
3. Keep answers to 4-6 sentences. Simple words, no jargon.
4. For serious disease questions, recommend consulting the local KVK.

Known paddy diseases: {disease_list}
"""


# ---------------------------------------------------------------------------
# LLM call — Groq (default), OpenAI, Anthropic, Gemini
# ---------------------------------------------------------------------------

def _call_llm(system_prompt: str, user_msg: str, history: list) -> str:
    provider = get_provider()

    # Build messages
    messages = [{"role": "system", "content": system_prompt}]
    for h in history[-MAX_HISTORY:]:
        messages.append({"role": h.role, "content": h.content})
    messages.append({"role": "user", "content": user_msg})

    if provider in ("groq", "openai"):
        from openai import OpenAI, OpenAIError
        if provider == "groq":
            client = OpenAI(
                base_url=GROQ_BASE_URL,
                api_key=os.environ["GROQ_API_KEY"],
            )
        else:
            client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

        try:
            resp  = client.chat.completions.create(
                model=os.environ.get(
                    f"{provider.upper()}_MODEL", DEFAULT_MODELS[provider]
                ),
                messages=messages,
                max_tokens=MAX_TOKENS,
                temperature=1,
                top_p=1,
                stream=False,
            )
            return (resp.choices[0].message.content or "").strip()
        except OpenAIError as exc:
            raise ChatServiceError(f"{provider} API error: {exc}") from exc

    elif provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        try:
            msgs = [m for m in messages if m["role"] != "system"]
            resp = client.messages.create(
                model=os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODELS["anthropic"]),
                max_tokens=MAX_TOKENS,
                system=system_prompt,
                messages=msgs,
            )
            return "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
        except anthropic.APIError as exc:
            raise ChatServiceError(f"Anthropic error: {exc}") from exc

    elif provider == "gemini":
        import google.generativeai as genai
        genai.configure(api_key=os.environ["GEMINI_API_KEY"])
        try:
            model = genai.GenerativeModel(
                model_name=os.environ.get("GEMINI_MODEL", DEFAULT_MODELS["gemini"]),
                system_instruction=system_prompt,
            )
            hist  = [{"role": "user" if m["role"] == "user" else "model",
                      "parts": [m["content"]]}
                     for m in messages[1:-1]]
            chat  = model.start_chat(history=hist)
            resp  = chat.send_message(user_msg,
                     generation_config={"max_output_tokens": MAX_TOKENS})
            return (resp.text or "").strip()
        except Exception as exc:
            raise ChatServiceError(f"Gemini error: {exc}") from exc

    raise ChatNotConfiguredError(
        f"Unknown LLM_PROVIDER '{provider}'. Valid: groq, openai, anthropic, gemini"
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def generate_reply(message: str, language: str,
                   diagnosis_context, conversation_history: list) -> str:
    """
    Build prompt → call LLM → return reply string.

    diagnosis_context: DiagnosisContext | None
    Raises: ChatNotConfiguredError, ChatServiceError
    """
    if not is_chat_configured():
        provider = get_provider()
        key_var  = PROVIDER_KEYS.get(provider, f"{provider.upper()}_API_KEY")
        raise ChatNotConfiguredError(f"Set {key_var} in your .env file.")

    disease    = diagnosis_context.disease    if diagnosis_context else None
    confidence = diagnosis_context.confidence if diagnosis_context else 0.0

    system_prompt = _build_system_prompt(language, disease, confidence)

    reply = _call_llm(system_prompt, message, conversation_history)

    if not reply:
        raise ChatServiceError("Empty response from LLM.")

    logger.info("Chat [lang=%s disease=%s] → %d chars",
                language, disease or "none", len(reply))
    return reply
