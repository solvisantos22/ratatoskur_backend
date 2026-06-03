from datetime import datetime
from uuid import UUID

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class ProblemCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    folder_id: UUID | None = None


class ProblemCreateResponse(BaseModel):
    id: UUID
    user_id: UUID
    folder_id: UUID | None = None
    folder_name: str | None = None
    title: str
    created_at: datetime
    updated_at: datetime


class FolderCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    color: str | None = Field(default=None, max_length=32)
    parent_folder_id: UUID | None = None


class FolderUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    color: str | None = Field(default=None, max_length=32)
    parent_folder_id: UUID | None = None


class FolderResponse(BaseModel):
    id: UUID
    user_id: UUID
    parent_folder_id: UUID | None = None
    name: str
    color: str | None = None
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None = None
    problem_count: int | None = None


class ProblemMoveRequest(BaseModel):
    folder_id: UUID


class ProblemBatchMoveRequest(BaseModel):
    problem_ids: list[UUID] = Field(min_length=1, max_length=200)
    folder_id: UUID


class ProblemBatchMoveResponse(BaseModel):
    moved_count: int


class AttemptResponse(BaseModel):
    id: UUID
    problem_id: UUID
    user_id: UUID
    mode: str
    page_count: int | None = None
    problem_image_url: str | None
    solution_image_url: str | None
    verdict: str | None
    response_type: str | None
    message_is: str | None
    model_name: str | None = None
    prompt_version: str | None = None
    latency_ms: int | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    tokens_thoughts: int | None = None
    tokens_total: int | None = None
    created_at: datetime


class AttemptFeedbackCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    rating: str = Field(min_length=1, max_length=16)
    comment: str | None = None
    trace_id: str | None = Field(
        default=None,
        max_length=128,
        validation_alias=AliasChoices("traceId", "trace_id"),
    )
    observation_id: str | None = Field(
        default=None,
        max_length=128,
        validation_alias=AliasChoices("observationId", "observation_id"),
    )
    message_id: str | None = Field(
        default=None,
        max_length=128,
        validation_alias=AliasChoices("messageId", "message_id"),
    )
    request_id: str | None = Field(
        default=None,
        max_length=128,
        validation_alias=AliasChoices("requestId", "request_id"),
    )
    client_request_id: str | None = Field(
        default=None,
        max_length=128,
        validation_alias=AliasChoices("clientRequestId", "client_request_id"),
    )
    session_id: str | None = Field(
        default=None,
        max_length=128,
        validation_alias=AliasChoices("sessionId", "session_id"),
    )
    feature: str | None = Field(default=None, max_length=64)
    flow: str | None = Field(default=None, max_length=64)
    route_name: str | None = Field(
        default=None,
        max_length=128,
        validation_alias=AliasChoices("routeName", "route_name"),
    )
    mode: str | None = Field(default=None, max_length=32)
    model_name: str | None = Field(
        default=None,
        max_length=128,
        validation_alias=AliasChoices("modelName", "model_name"),
    )
    prompt_version: str | None = Field(
        default=None,
        max_length=64,
        validation_alias=AliasChoices("promptVersion", "prompt_version"),
    )
    latency_ms: int | None = Field(
        default=None,
        validation_alias=AliasChoices("latencyMs", "latency_ms"),
    )
    tokens_in: int | None = Field(
        default=None,
        validation_alias=AliasChoices("tokensIn", "tokens_in"),
    )
    tokens_out: int | None = Field(
        default=None,
        validation_alias=AliasChoices("tokensOut", "tokens_out"),
    )
    tokens_total: int | None = Field(
        default=None,
        validation_alias=AliasChoices("tokensTotal", "tokens_total"),
    )


class AttemptFeedbackResponse(BaseModel):
    id: UUID
    attempt_id: UUID
    user_id: UUID
    rating: str | None
    comment: str | None
    created_at: datetime
    score_submitted: bool | None = None
    score_error: str | None = None


class AnalyticsEventResponse(BaseModel):
    id: UUID
    user_id: UUID
    problem_id: UUID | None = None
    attempt_id: UUID | None = None
    event_type: str | None
    mode: str | None
    verdict: str | None
    created_at: datetime
    metadata_json: str | None


class UserStatsSummaryResponse(BaseModel):
    solved_problems_count_current: int
    solved_problems_count_pre: int
    average_error_current: float
    average_error_pre: float
    active_streak: int
    average_attempts_current: float
    average_attempts_pre: float
    most_common_mode: str | None = None


class ErrorBankEntryResponse(BaseModel):
    error_type: str
    concept_tag: str | None = None
    count: int
    fixed_count: int
    unclear_count: int
    unresolved_count: int
    resolution_ratio: float
    unclear_ratio: float
    last_seen_at: datetime


class ErrorBankSummaryResponse(BaseModel):
    total_occurrences: int
    total_distinct_errors: int
    entries: list[ErrorBankEntryResponse]


class ErrorEventTypeCountEntryResponse(BaseModel):
    error_type: str
    count: int


class ErrorEventTypeCountSummaryResponse(BaseModel):
    total_occurrences: int
    total_distinct_error_types: int
    entries: list[ErrorEventTypeCountEntryResponse]


class ErrorEventListItemResponse(BaseModel):
    id: UUID
    attempt_id: UUID
    problem_id: UUID
    problem_title: str
    folder_id: UUID | None = None
    folder_name: str | None = None
    topic: str | None = None
    subtopic: str | None = None
    wrong_step: str | None = None
    correct_step: str | None = None
    error_type: str
    confidence: float | None = None
    created_at: datetime


class ErrorEventListResponse(BaseModel):
    items: list[ErrorEventListItemResponse]
    next_cursor: str | None = None


class AttemptLabelCreateRequest(BaseModel):
    label_source: str = Field(min_length=1, max_length=32)
    label_name: str = Field(min_length=1, max_length=64)
    label_value: str = Field(min_length=1, max_length=256)
    confidence: float | None = None
    notes: str | None = None


class AttemptLabelResponse(BaseModel):
    id: UUID
    attempt_id: UUID
    user_id: UUID
    anon_user_id: str
    label_source: str
    label_name: str
    label_value: str
    confidence: float | None = None
    notes: str | None = None
    created_at: datetime
