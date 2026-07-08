"""
schemas.py — Pydantic models for Kisan Mitra API.
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field


class TreatmentInfo(BaseModel):
    cause:              str
    severity_levels:    list[str]
    organic_treatment:  str
    chemical_treatment: str
    precautions:        Optional[str] = None
    refer_to_kvk:       bool = False


class DiagnosisContext(BaseModel):
    disease:    str
    confidence: float


class DiagnoseResponse(BaseModel):
    disease:      str
    confidence:   float = Field(..., ge=0, le=100)
    treatment:    TreatmentInfo
    diagnosis_id: int


class FeedbackRequest(BaseModel):
    diagnosis_id: int
    helpful:      bool


class ChatMessage(BaseModel):
    role:    Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message:              str = Field(..., min_length=1)
    language:             Literal["hi", "mr", "en"] = "hi"
    diagnosis_context:    Optional[DiagnosisContext] = None
    conversation_history: list[ChatMessage] = Field(default_factory=list)


class ChatResponse(BaseModel):
    reply:    str
    language: str
