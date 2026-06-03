from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


PACK_SIZES = {10, 20, 30}
BUILD_MODES = {"auto", "manual"}
FEEDBACK_MODES = {"per_question", "end_exam"}
TOPICS = {"algebra", "fractions"}


class ExamPackCreateRequest(BaseModel):
    title: str = Field(default="Exam Prep Pack", min_length=1, max_length=160)
    pack_size: int = Field(default=10)
    build_mode: str = Field(default="auto")
    feedback_mode: str = Field(default="end_exam")
    topics: list[str] = Field(default_factory=lambda: ["algebra", "fractions"])
    manual_error_targets: list[str] | None = None


class ExamPackItemResponse(BaseModel):
    id: UUID
    position: int
    topic: str
    difficulty: str
    target_error_type: str | None = None
    target_concept_tag: str | None = None
    question_text: str
    answer_format: str


class ExamPackResponse(BaseModel):
    id: UUID
    title: str
    pack_size: int
    build_mode: str
    feedback_mode: str
    topics: list[str]
    manual_error_targets: list[str] | None = None
    status: str
    generation_model: str | None = None
    generation_prompt_version: str | None = None
    created_at: datetime
    updated_at: datetime


class ExamPackDetailResponse(ExamPackResponse):
    items: list[ExamPackItemResponse]


class ExamSessionStartResponse(BaseModel):
    session_id: UUID
    pack: ExamPackDetailResponse


class ExamAnswerUpdateRequest(BaseModel):
    answer_text: str | None = None
    answer_image_base64: str | None = None


class ExamAnswerUpdateResponse(BaseModel):
    session_id: UUID
    item_id: UUID
    answer_text: str | None = None
    is_correct: bool | None = None
    score: float | None = None
    feedback_text: str | None = None
    graded: bool


class ExamSessionSubmitResponse(BaseModel):
    session_id: UUID
    status: str
    score_correct: int
    score_total: int
    score_percent: float


class ExamSessionResultItemResponse(BaseModel):
    item_id: UUID
    position: int
    topic: str
    difficulty: str
    target_error_type: str | None = None
    question_text: str
    answer_format: str
    answer_text: str | None = None
    is_correct: bool | None = None
    score: float | None = None
    feedback_text: str | None = None


class ExamSessionResultsResponse(BaseModel):
    session_id: UUID
    pack_id: UUID
    status: str
    feedback_mode: str
    score_correct: int | None = None
    score_total: int | None = None
    score_percent: float | None = None
    started_at: datetime
    submitted_at: datetime | None = None
    graded_at: datetime | None = None
    items: list[ExamSessionResultItemResponse]
