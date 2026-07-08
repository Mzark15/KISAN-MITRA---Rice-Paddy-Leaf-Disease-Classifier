"""
schemas.py — Pydantic request/response models for Kisan Mitra.
Image diagnosis + text chat only. Voice/audio removed.
"""

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


# ── Shared ────────────────────────────────────────────────────────────────────

class TreatmentInfo(BaseModel):
    cause:              str
    severity_levels:    list[str]
    organic_treatment:  str
    chemical_treatment: str
    precautions:        Optional[str] = None
    refer_to_kvk:       bool          = False


class DiagnosisContext(BaseModel):
    """Passed from a /diagnose result into /chat for disease-specific advice."""
    disease:    str
    confidence: float


# ── /diagnose ─────────────────────────────────────────────────────────────────

class DiagnoseResponse(BaseModel):
    disease:                str
    confidence:             float = Field(..., ge=0, le=100)
    treatment:              TreatmentInfo
    diagnosis_id:           int
    model_mode:             str   # "tflite" | "random"
    safe_to_act:            bool
    low_confidence_message: Optional[str] = None


class FeedbackRequest(BaseModel):
    diagnosis_id: int
    helpful:      bool


# ── /chat ─────────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role:    Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message:              str            = Field(..., min_length=1)
    language:             Literal["hi", "mr", "en"] = "hi"
    diagnosis_context:    Optional[DiagnosisContext] = None
    conversation_history: list[ChatMessage]          = Field(default_factory=list)


class ChatResponse(BaseModel):
    reply:    str
    language: str
    grounded: bool = True


# ── /dashboard ────────────────────────────────────────────────────────────────

class DashboardStatsResponse(BaseModel):
    total_diagnoses:       int
    disease_breakdown:     dict[str, int]
    avg_confidence:        float
    model_mode_breakdown:  dict[str, int]
    total_chats:           int
    total_voice_sessions:  int
    languages_used:        dict[str, int]
    helpful_feedback_pct:  float
    last_7_days_diagnoses: list[dict[str, Any]]
