"""Request / response bodies of POST /chat (docs/api-spec.md)."""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

MAX_MESSAGE_CHARS = 500
MAX_SESSION_ID_CHARS = 100


class ChatRequest(BaseModel):
    session_id: Optional[str] = Field(None, max_length=MAX_SESSION_ID_CHARS,
                                      description="이어서 대화할 세션 ID. 없으면 서버가 새로 만든다.")
    message: str = Field(..., min_length=1, max_length=MAX_MESSAGE_CHARS, description="사용자 메시지")

    @field_validator("message")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message must not be blank")
        return v

    @field_validator("session_id")
    @classmethod
    def blank_session_is_none(cls, v: Optional[str]) -> Optional[str]:
        return (v or "").strip() or None


class ChatResponse(BaseModel):
    # common
    session_id: str
    status: Literal["ask", "ready"]
    intent: str
    reply: Optional[str] = None
    messages: list[str] = []
    notice: Optional[str] = None
    missing_inputs: list[str] = []
    candidates: list[dict[str, Any]] = []
    available_date_range: Optional[dict[str, str]] = None
    baby_age_months: Optional[int] = None
    travels_during_nap: Optional[bool] = None
    departure_location: Optional[dict[str, Any]] = None
    outing_date: Optional[str] = None
    departure_time: Optional[str] = None
    exclude_keywords: list[str] = []
    include_keywords: list[str] = []
    preference_text: Optional[str] = None
    reference_place: Optional[str] = None
    reference_candidates: list[dict[str, Any]] = []
    # recommendation (only when this turn ran the recommendation)
    result_cards: Optional[list[dict[str, Any]]] = None
    max_drive_hours: Optional[float] = None
    radius_km: Optional[float] = None
    radius_expanded: Optional[bool] = None
    failed_sources: Optional[list[str]] = None
    elapsed_s: Optional[float] = None
    preference_status: Optional[str] = None
