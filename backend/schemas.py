from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class TreatmentInfo(BaseModel):
    cause: str
    severity_levels: list[str]
    organic_treatment: str
    chemical_treatment: str


class DiagnoseResponse(BaseModel):
    disease: str
    confidence: float
    treatment: TreatmentInfo
    diagnosis_id: int


class FeedbackRequest(BaseModel):
    diagnosis_id: int
    helpful: bool


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class DiagnosisContext(BaseModel):
    disease: str
    confidence: float


class ChatRequest(BaseModel):
    message: str
    language: Literal["hi", "mr", "en"] = "hi"
    diagnosis_context: Optional[DiagnosisContext] = None
    conversation_history: list[ChatMessage] = Field(default_factory=list)


class ChatResponse(BaseModel):
    reply: str
    language: str
    grounded: bool = True


class VoiceSTTResponse(BaseModel):
    text: str
    language: str


class VoiceTTSRequest(BaseModel):
    text: str
    language: Literal["hi", "mr", "en", "ta", "te", "kn", "pa", "gu", "bn", "ml"] = "hi"


class VoiceChatResponse(BaseModel):
    transcript: str
    reply_text: str
    reply_audio_url: str


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
