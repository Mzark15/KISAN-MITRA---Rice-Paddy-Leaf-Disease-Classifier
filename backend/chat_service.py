"""
chat_service.py — LangGraph-powered chat for Kisan Mitra

Architecture (graph nodes):
  classify_intent → select_prompt → generate_response

Node 1 — classify_intent
  Reads the farmer's message and decides what kind of question it is:
    "disease_specific"  — asking about the diagnosed disease (diagnosis_context present)
    "general_farming"   — general paddy farming question
    "off_topic"         — not about farming at all

Node 2 — select_prompt
  Builds a dynamic system prompt based on:
    - The intent class
    - The specific diagnosed disease (from diagnosis_context)
    - Full disease treatment data from diseases.json (only the relevant disease, not all 13)
  This keeps the prompt focused and the LLM grounded.

Node 3 — generate_response
  Calls the configured LLM provider with the dynamic prompt and returns the reply.

Provider: set LLM_PROVIDER env var (sambanova | gemini | openai | anthropic)
Model:    set SAMBANOVA_MODEL / GEMINI_MODEL / OPENAI_MODEL / ANTHROPIC_MODEL
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Literal, Optional, TypedDict

from schemas import ChatMessage, DiagnosisContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LLM_PROVIDER_ENV = "LLM_PROVIDER"

PROVIDER_KEYS: dict[str, str] = {
    "sambanova": "SAMBANOVA_API_KEY",
    "gemini":    "GEMINI_API_KEY",
    "openai":    "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}

DEFAULT_MODELS: dict[str, str] = {
    "sambanova": "Meta-Llama-3.1-8B-Instruct",
    "gemini":    "gemini-2.0-flash",
    "openai":    "gpt-4o-mini",
    "anthropic": "claude-haiku-4-5",
}

SAMBANOVA_BASE_URL = "https://api.sambanova.ai/v1"
MAX_HISTORY        = 6
MAX_TOKENS         = 400

DISEASES_FILE = Path(__file__).resolve().parent / "diseases.json"

ERROR_MESSAGES = {
    "hi": "क्षमा करें, अभी उत्तर नहीं दे पा रहे। कृपया थोड़ी देर बाद फिर कोशिश करें।",
    "mr": "क्षमस्व, आत्ता उत्तर देऊ शकत नाही. कृपया थोड्या वेळाने पुन्हा प्रयत्न करा.",
    "en": "Sorry, we could not get an answer right now. Please try again later.",
}

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ChatNotConfiguredError(Exception):
    """No API key set for the active provider."""

class ChatServiceError(Exception):
    """LLM API call failed."""

# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------

_diseases: Optional[dict[str, Any]] = None


def init_knowledge_base() -> None:
    """Load diseases.json once at startup."""
    global _diseases
    if not DISEASES_FILE.exists():
        raise FileNotFoundError(
            f"diseases.json not found at {DISEASES_FILE}. "
            "This file must exist for safe chat responses."
        )
    with open(DISEASES_FILE, "r", encoding="utf-8") as f:
        _diseases = json.load(f)
    logger.info("Knowledge base loaded: %d diseases", len(_diseases))


def _get_diseases() -> dict[str, Any]:
    if _diseases is None:
        init_knowledge_base()
    return _diseases


def _disease_entry(disease_name: str) -> Optional[dict]:
    return _get_diseases().get(disease_name)


def _all_diseases_summary() -> str:
    return ", ".join(_get_diseases().keys())


# ---------------------------------------------------------------------------
# LangGraph state
# ---------------------------------------------------------------------------

IntentType = Literal["disease_specific", "general_farming", "off_topic"]


class GraphState(TypedDict):
    message:           str
    language:          str
    diagnosis_context: Optional[DiagnosisContext]
    history:           list[ChatMessage]
    intent:            Optional[IntentType]
    system_prompt:     Optional[str]
    reply:             Optional[str]


# ---------------------------------------------------------------------------
# Prompt templates — edit these to change LLM behaviour
# ---------------------------------------------------------------------------

DISEASE_SPECIFIC_PROMPT = """\
You are Kisan Mitra, a trusted AI advisor for paddy (rice) farmers in India.

The farmer's plant has been diagnosed with: {disease_name}
Diagnosis confidence: {confidence:.1f}%

RULES:
1. Reply in {language_name}. Match the farmer's language exactly.
2. Give advice ONLY based on the treatment data below. Do not invent chemicals or dosages.
3. Keep your answer to 4-6 sentences. Use simple, practical words.
4. If severity is High or disease is Tungro or Bacterial Panicle Blight, end with:
   "अपने नजदीकी KVK या कृषि विशेषज्ञ से मिलें।" (or equivalent in reply language).

DISEASE DATA for {disease_name}:
  Cause: {cause}
  Severity levels: {severity}
  Organic treatment: {organic}
  Chemical treatment: {chemical}
  Precautions: {precautions}
"""

GENERAL_FARMING_PROMPT = """\
You are Kisan Mitra, a trusted AI advisor for paddy (rice) farmers in India.

RULES:
1. Reply in {language_name}. Match the farmer's language exactly.
2. Only answer questions about paddy/rice farming.
3. For treatment advice, only mention standard agronomic practice. Do not invent dosages.
4. Keep answers to 4-6 sentences. Simple words, no jargon.
5. For serious disease questions, recommend consulting the local KVK.

Paddy diseases you can discuss: {disease_list}
"""

OFF_TOPIC_PROMPT = """\
You are Kisan Mitra, an AI advisor that ONLY helps with paddy/rice farming.
Reply in {language_name}.
Politely tell the farmer you can only help with paddy crop questions.
Keep it to 2 sentences.
"""

LANGUAGE_NAMES = {"hi": "Hindi", "mr": "Marathi", "en": "English"}


# ---------------------------------------------------------------------------
# LangGraph nodes
# ---------------------------------------------------------------------------

def classify_intent(state: GraphState) -> GraphState:
    """
    Node 1: Classify the query — no LLM call, pure logic.

    To extend: add more keyword lists or a lightweight ML classifier here.
    """
    msg = state["message"].lower()
    ctx = state["diagnosis_context"]

    off_topic_keywords = [
        "cricket", "weather", "news", "politics", "movie", "song",
        "football", "stock", "share market", "recipe",
    ]
    if any(k in msg for k in off_topic_keywords):
        return {**state, "intent": "off_topic"}

    # If the farmer has a diagnosis result open, treat as disease-specific
    if ctx is not None:
        return {**state, "intent": "disease_specific"}

    return {**state, "intent": "general_farming"}


def select_prompt(state: GraphState) -> GraphState:
    """
    Node 2: Build the dynamic system prompt for this specific query.

    disease_specific → only injects the one relevant disease's data
    general_farming  → injects disease name list only
    off_topic        → polite refusal template
    """
    intent    = state["intent"]
    lang_name = LANGUAGE_NAMES.get(state["language"], "English")

    if intent == "disease_specific":
        ctx   = state["diagnosis_context"]
        entry = _disease_entry(ctx.disease) if ctx else None
        if ctx and entry:
            prompt = DISEASE_SPECIFIC_PROMPT.format(
                disease_name=ctx.disease,
                confidence=ctx.confidence,
                language_name=lang_name,
                cause=entry.get("cause", "Unknown"),
                severity=", ".join(entry.get("severity_levels", [])) or "varies",
                organic=entry.get("organic_treatment", ""),
                chemical=entry.get("chemical_treatment", ""),
                precautions=entry.get("precautions") or "Follow label instructions carefully.",
            )
        else:
            prompt = GENERAL_FARMING_PROMPT.format(
                language_name=lang_name,
                disease_list=_all_diseases_summary(),
            )

    elif intent == "off_topic":
        prompt = OFF_TOPIC_PROMPT.format(language_name=lang_name)

    else:
        prompt = GENERAL_FARMING_PROMPT.format(
            language_name=lang_name,
            disease_list=_all_diseases_summary(),
        )

    return {**state, "system_prompt": prompt}


def generate_response(state: GraphState) -> GraphState:
    """Node 3: Call the LLM with the dynamic prompt."""
    provider = get_provider()
    history  = state["history"][-MAX_HISTORY:]

    generators = {
        "sambanova": _generate_sambanova,
        "gemini":    _generate_gemini,
        "openai":    _generate_openai,
        "anthropic": _generate_anthropic,
    }
    fn = generators.get(provider)
    if fn is None:
        raise ChatNotConfiguredError(
            f"Unknown LLM_PROVIDER '{provider}'. Valid: {', '.join(generators)}"
        )

    reply = fn(
        system_prompt=state["system_prompt"],
        user_msg=state["message"],
        history=history,
    )
    return {**state, "reply": reply}


# ---------------------------------------------------------------------------
# Build LangGraph
# ---------------------------------------------------------------------------

def _build_graph():
    """
    Compile the three-node graph.

    To add a node (e.g. a safety check):
      1. Write: def safety_check(state: GraphState) -> GraphState
      2. graph.add_node("safety_check", safety_check)
      3. graph.add_edge("select_prompt", "safety_check")
         graph.add_edge("safety_check", "generate_response")
    """
    from langgraph.graph import END, StateGraph

    g = StateGraph(GraphState)
    g.add_node("classify_intent",   classify_intent)
    g.add_node("select_prompt",     select_prompt)
    g.add_node("generate_response", generate_response)

    g.set_entry_point("classify_intent")
    g.add_edge("classify_intent",   "select_prompt")
    g.add_edge("select_prompt",     "generate_response")
    g.add_edge("generate_response", END)

    return g.compile()


_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        _graph = _build_graph()
    return _graph


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def get_provider() -> str:
    return os.environ.get(LLM_PROVIDER_ENV, "sambanova").lower()


def is_chat_configured() -> bool:
    provider = get_provider()
    key_name = PROVIDER_KEYS.get(provider)
    return bool(key_name and os.environ.get(key_name))


def error_message(language: str) -> str:
    return ERROR_MESSAGES.get(language, ERROR_MESSAGES["en"])


# ---------------------------------------------------------------------------
# LLM provider functions
# ---------------------------------------------------------------------------

def _openai_messages(system_prompt: str, user_msg: str, history: list[ChatMessage]) -> list[dict]:
    messages = [{"role": "system", "content": system_prompt}]
    for h in history:
        messages.append({"role": h.role, "content": h.content})
    messages.append({"role": "user", "content": user_msg})
    return messages


def _generate_sambanova(system_prompt: str, user_msg: str, history: list[ChatMessage]) -> str:
    from openai import OpenAI, OpenAIError
    api_key = os.environ.get("SAMBANOVA_API_KEY")
    if not api_key:
        raise ChatNotConfiguredError("SAMBANOVA_API_KEY not set.")
    try:
        client = OpenAI(
            base_url=os.environ.get("SAMBANOVA_BASE_URL", SAMBANOVA_BASE_URL),
            api_key=api_key,
        )
        resp = client.chat.completions.create(
            model=os.environ.get("SAMBANOVA_MODEL", DEFAULT_MODELS["sambanova"]),
            messages=_openai_messages(system_prompt, user_msg, history),
            max_tokens=MAX_TOKENS,
            temperature=0.3,
        )
        reply = (resp.choices[0].message.content or "").strip()
    except OpenAIError as exc:
        raise ChatServiceError(f"SambaNova API error: {exc}") from exc
    if not reply:
        raise ChatServiceError("Empty response from SambaNova.")
    return reply


def _generate_gemini(system_prompt: str, user_msg: str, history: list[ChatMessage]) -> str:
    import google.generativeai as genai
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ChatNotConfiguredError("GEMINI_API_KEY not set.")
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name=os.environ.get("GEMINI_MODEL", DEFAULT_MODELS["gemini"]),
            system_instruction=system_prompt,
        )
        chat  = model.start_chat(history=[
            {"role": "user" if h.role == "user" else "model", "parts": [h.content]}
            for h in history
        ])
        resp  = chat.send_message(user_msg, generation_config={"max_output_tokens": MAX_TOKENS})
        reply = (resp.text or "").strip()
    except Exception as exc:
        raise ChatServiceError(f"Gemini API error: {exc}") from exc
    if not reply:
        raise ChatServiceError("Empty response from Gemini.")
    return reply


def _generate_openai(system_prompt: str, user_msg: str, history: list[ChatMessage]) -> str:
    from openai import OpenAI, OpenAIError
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ChatNotConfiguredError("OPENAI_API_KEY not set.")
    try:
        client = OpenAI(api_key=api_key)
        resp   = client.chat.completions.create(
            model=os.environ.get("OPENAI_MODEL", DEFAULT_MODELS["openai"]),
            messages=_openai_messages(system_prompt, user_msg, history),
            max_tokens=MAX_TOKENS,
            temperature=0.3,
        )
        reply = (resp.choices[0].message.content or "").strip()
    except OpenAIError as exc:
        raise ChatServiceError(f"OpenAI API error: {exc}") from exc
    if not reply:
        raise ChatServiceError("Empty response from OpenAI.")
    return reply


def _generate_anthropic(system_prompt: str, user_msg: str, history: list[ChatMessage]) -> str:
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ChatNotConfiguredError("ANTHROPIC_API_KEY not set.")
    try:
        client = anthropic.Anthropic(api_key=api_key)
        msgs   = [{"role": h.role, "content": h.content} for h in history]
        msgs.append({"role": "user", "content": user_msg})
        resp   = client.messages.create(
            model=os.environ.get("ANTHROPIC_MODEL", DEFAULT_MODELS["anthropic"]),
            max_tokens=MAX_TOKENS,
            system=system_prompt,
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
    Run the LangGraph pipeline and return the reply.

    Flow: classify_intent → select_prompt → generate_response

    Raises:
        ChatNotConfiguredError: no API key set
        ChatServiceError:       LLM call failed
    """
    if not is_chat_configured():
        provider = get_provider()
        key_var  = PROVIDER_KEYS.get(provider, f"{provider.upper()}_API_KEY")
        raise ChatNotConfiguredError(f"Chat not configured. Set {key_var}.")

    final = _get_graph().invoke({
        "message":           message,
        "language":          language,
        "diagnosis_context": diagnosis_context,
        "history":           conversation_history,
        "intent":            None,
        "system_prompt":     None,
        "reply":             None,
    })

    reply = final.get("reply")
    if not reply:
        raise ChatServiceError("Graph completed but produced no reply.")

    logger.info(
        "LangGraph chat [intent=%s lang=%s disease=%s] → %d chars",
        final.get("intent"), language,
        diagnosis_context.disease if diagnosis_context else "none",
        len(reply),
    )
    return reply
