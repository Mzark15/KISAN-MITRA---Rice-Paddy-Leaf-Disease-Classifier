"""
schemas.py — All Pydantic request/response models for Kisan Mitra.

Add new fields here first, then update the relevant router and service.
Every model has clear field descriptions so API docs (FastAPI /docs) are useful.
"""

from typing import Any, Literal, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Shared sub-models
# ---------------------------------------------------------------------------

class TreatmentInfo(BaseModel):
    """Vetted treatment data from diseases.json. Never AI-generated."""
    cause: str                          = Field(..., description="Root cause of the disease")
    severity_levels: list[str]          = Field(..., description="Possible severity levels, e.g. Low/Medium/High")
    organic_treatment: str              = Field(..., description="Organic/natural treatment steps")
    chemical_treatment: str             = Field(..., description="Chemical treatment with safe dosages")
    precautions: Optional[str]          = Field(None, description="Extra safety precautions")
    refer_to_kvk: bool                  = Field(False, description="True for severe diseases — farmer should contact KVK")


class DiagnosisContext(BaseModel):
    """Passed from diagnosis result into the chat so the AI gives disease-specific advice."""
    disease: str
    confidence: float
    safe_to_act: bool                   = Field(True, description="False when the photo result was low-confidence")
    alternatives: list[str]             = Field(default_factory=list, description="Other likely diseases (top 3 minus the first)")


# ---------------------------------------------------------------------------
# /auth
# ---------------------------------------------------------------------------

class OtpStartRequest(BaseModel):
    phone: str                          = Field(..., max_length=20, example="9876543210")


class OtpStartResponse(BaseModel):
    phone: str                          = Field(..., description="Normalised E.164 number, e.g. +919876543210")
    flow: Literal["signup", "signin"]   = Field(..., description="Send back unchanged to /auth/otp/verify")
    session: Optional[str]              = Field(None, description="Send back unchanged to /auth/otp/verify")
    resend_after: int                   = Field(..., description="Seconds before another code may be requested")


class OtpVerifyRequest(BaseModel):
    phone: str                          = Field(..., max_length=20)
    code: str                           = Field(..., max_length=8)
    flow: Literal["signup", "signin"]
    session: Optional[str]              = Field(None, max_length=4096)


class RefreshRequest(BaseModel):
    refresh_token: str                  = Field(..., max_length=8192)
    username: str                       = Field(..., max_length=128)


class LogoutRequest(BaseModel):
    refresh_token: str                  = Field(..., max_length=8192)


class ProfileUpdate(BaseModel):
    language: Optional[Literal["hi", "mr", "en"]] = None
    village: Optional[str]              = Field(None, max_length=100)
    name: Optional[str]                 = Field(None, max_length=100)


class StaffLoginRequest(BaseModel):
    email: str                          = Field(..., max_length=254)
    password: str                       = Field(..., max_length=256)


class StaffChallengeRequest(BaseModel):
    username: str                       = Field(..., max_length=128)
    challenge: Literal["NEW_PASSWORD_REQUIRED", "MFA_SETUP", "SOFTWARE_TOKEN_MFA"]
    session: str                        = Field(..., max_length=4096)
    new_password: Optional[str]         = Field(None, max_length=256)
    code: Optional[str]                 = Field(None, max_length=8)


# ---------------------------------------------------------------------------
# /diagnose
# ---------------------------------------------------------------------------

class PredictionScore(BaseModel):
    disease: str
    confidence: float                   = Field(..., ge=0, le=100)


class DiagnoseResponse(BaseModel):
    disease: str                        = Field(..., example="Brown Spot")
    confidence: float                   = Field(..., ge=0, le=100, example=87.4)
    treatment: TreatmentInfo
    diagnosis_id: str                   = Field(..., description="Diagnosis ID; use this for feedback submission")
    model_mode: str                     = Field(..., example="tflite", description="'tflite' = real model, 'random' = demo stub")
    safe_to_act: bool                   = Field(..., description="False when confidence is too low — ask farmer for clearer photo")
    low_confidence_message: Optional[str] = Field(None, description="Populated when safe_to_act is False")
    top_predictions: list[PredictionScore] = Field(default_factory=list, description="Top 3 classes, highest first")


class FeedbackRequest(BaseModel):
    diagnosis_id: str                   = Field(..., max_length=64)
    helpful: bool


# ---------------------------------------------------------------------------
# /chat
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str                        = Field(..., min_length=1, example="मेरी फसल में पीले धब्बे हैं")
    language: Literal["hi", "mr", "en"] = Field("hi", description="Reply language: hi=Hindi, mr=Marathi, en=English")
    diagnosis_context: Optional[DiagnosisContext] = Field(None, description="Pass after a photo diagnosis for disease-specific advice")
    conversation_history: list[ChatMessage] = Field(default_factory=list, description="Last N turns; service trims to MAX_HISTORY automatically")


class ChatResponse(BaseModel):
    reply: str
    language: str
    grounded: bool = Field(True, description="Always True — advice comes from diseases.json, not AI hallucination")


# ---------------------------------------------------------------------------
# /voice
# ---------------------------------------------------------------------------

class VoiceSTTResponse(BaseModel):
    text: str
    language: str


class VoiceTTSRequest(BaseModel):
    text: str
    language: Literal["hi", "mr", "en", "ta", "te", "kn", "pa", "gu", "bn", "ml"] = "hi"


class VoiceChatResponse(BaseModel):
    transcript: str                     = Field(..., description="What the farmer said")
    reply_text: str                     = Field(..., description="Advisor reply text")
    reply_audio_url: str                = Field(..., description="POST /voice/tts to get audio for this reply")


# ---------------------------------------------------------------------------
# /dashboard
# ---------------------------------------------------------------------------

class DashboardStatsResponse(BaseModel):
    total_diagnoses: int
    disease_breakdown: dict[str, int]
    avg_confidence: float
    model_mode_breakdown: dict[str, int]
    total_chats: int
    total_voice_sessions: int
    languages_used: dict[str, int]
    helpful_feedback_pct: float
    last_7_days_diagnoses: list[dict[str, Any]]
