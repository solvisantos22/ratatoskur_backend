from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from sqlmodel import SQLModel, Field, Relationship, Column
from sqlalchemy import JSON, String, DateTime, Boolean, Index, Integer, Float, UniqueConstraint
from sqlalchemy.orm import relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_anon_user_id() -> str:
    return str(uuid4())


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    anon_user_id: str = Field(
        default_factory=new_anon_user_id,
        sa_column=Column(String(64), nullable=False, unique=True, index=True),
    )

    email: str = Field(
        sa_column=Column(String(320), nullable=False, unique=True, index=True)
    )
    full_name: Optional[str] = Field(default=None, sa_column=Column(String(128)))
    consent_analytics: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    consent_dataset_internal: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    consent_dataset_publish: bool = Field(default=False, sa_column=Column(Boolean, nullable=False))
    consent_updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    # Store a bcrypt hash, never the raw password
    password_hash: str = Field(sa_column=Column(String(255), nullable=False))

    is_active: bool = Field(default=True, sa_column=Column(Boolean, nullable=False))

    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    refresh_tokens: list["RefreshToken"] = Relationship(
        sa_relationship=relationship("RefreshToken", back_populates="user")
    )
    problems: list["Problem"] = Relationship(
        sa_relationship=relationship("Problem", back_populates="user")
    )
    folders: list["Folder"] = Relationship(
        sa_relationship=relationship("Folder", back_populates="user")
    )
    attempts: list["Attempt"] = Relationship(
        sa_relationship=relationship("Attempt", back_populates="user")
    )


class RefreshToken(SQLModel, table=True):
    __tablename__ = "refresh_tokens"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)

    user_id: UUID = Field(foreign_key="users.id", index=True)

    # Public token identifier (stored in cookie + DB lookup)
    selector: str = Field(sa_column=Column(String(128), nullable=False))

    # Secret token hash (validator portion); never store validator in plaintext
    validator_hash: str = Field(sa_column=Column(String(255), nullable=False))

    # Optional metadata (nice to have)
    user_agent: Optional[str] = Field(default=None, sa_column=Column(String(512)))
    ip_address: Optional[str] = Field(default=None, sa_column=Column(String(64)))

    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    expires_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))

    revoked_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    user: User = Relationship(
        sa_relationship=relationship("User", back_populates="refresh_tokens")
    )

    # Helpful indexes/constraints
    __table_args__ = (
        Index("ix_refresh_tokens_user_id_expires_at", "user_id", "expires_at"),
        Index("ix_refresh_tokens_selector", "selector", unique=True),
    )


class Problem(SQLModel, table=True):
    __tablename__ = "problems"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    folder_id: Optional[UUID] = Field(default=None, foreign_key="folders.id", index=True)
    title: Optional[str] = Field(default=None, sa_column=Column(String(255)))
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    user: User = Relationship(
        sa_relationship=relationship("User", back_populates="problems")
    )
    folder: Optional["Folder"] = Relationship(
        sa_relationship=relationship("Folder", back_populates="problems")
    )
    attempts: list["Attempt"] = Relationship(
        sa_relationship=relationship("Attempt", back_populates="problem")
    )


class Folder(SQLModel, table=True):
    __tablename__ = "folders"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    parent_folder_id: Optional[UUID] = Field(
        default=None,
        foreign_key="folders.id",
        index=True,
    )
    name: str = Field(sa_column=Column(String(128), nullable=False))
    color: Optional[str] = Field(default=None, sa_column=Column(String(32)))
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    archived_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )

    user: User = Relationship(
        sa_relationship=relationship("User", back_populates="folders")
    )
    parent: Optional["Folder"] = Relationship(
        sa_relationship=relationship(
            "Folder",
            remote_side="Folder.id",
            back_populates="children",
        )
    )
    children: list["Folder"] = Relationship(
        sa_relationship=relationship("Folder", back_populates="parent")
    )
    problems: list[Problem] = Relationship(
        sa_relationship=relationship("Problem", back_populates="folder")
    )

    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_folders_user_id_name"),
    )


class Attempt(SQLModel, table=True):
    __tablename__ = "attempts"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    problem_id: UUID = Field(foreign_key="problems.id", index=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    anon_user_id: str = Field(sa_column=Column(String(64), nullable=False, index=True))
    mode: str = Field(sa_column=Column(String(32), nullable=False))
    page_count: Optional[int] = Field(default=None, sa_column=Column(Integer))
    client_request_id: Optional[str] = Field(default=None, sa_column=Column(String(128)))
    session_id: Optional[str] = Field(default=None, sa_column=Column(String(128)))
    prompt_variant: Optional[str] = Field(default=None, sa_column=Column(String(32)))
    pipeline_mode: Optional[str] = Field(default=None, sa_column=Column(String(32)))
    expert_mode: Optional[str] = Field(default=None, sa_column=Column(String(32)))

    problem_image_key: Optional[str] = Field(default=None, sa_column=Column(String(1024)))
    solution_image_key: Optional[str] = Field(default=None, sa_column=Column(String(1024)))
    drawing_data_key: Optional[str] = Field(default=None, sa_column=Column(String(1024)))
    solution_page_keys: Optional[list[str]] = Field(default=None, sa_column=Column(JSON))
    drawing_page_keys: Optional[list[str]] = Field(default=None, sa_column=Column(JSON))
    raw_response_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))

    verdict: Optional[str] = Field(default=None, sa_column=Column(String(64)))
    response_type: Optional[str] = Field(default=None, sa_column=Column(String(64)))
    model_name: Optional[str] = Field(default=None, sa_column=Column(String(128)))
    prompt_version: Optional[str] = Field(default=None, sa_column=Column(String(64)))
    latency_ms: Optional[int] = Field(default=None, sa_column=Column(Integer))
    tokens_in: Optional[int] = Field(default=None, sa_column=Column(Integer))
    tokens_out: Optional[int] = Field(default=None, sa_column=Column(Integer))
    tokens_thoughts: Optional[int] = Field(default=None, sa_column=Column(Integer))
    tokens_total: Optional[int] = Field(default=None, sa_column=Column(Integer))
    trace_id: Optional[str] = Field(default=None, sa_column=Column(String(128)))
    observation_id: Optional[str] = Field(default=None, sa_column=Column(String(128)))
    request_id: Optional[str] = Field(default=None, sa_column=Column(String(128)))
    message_is: Optional[str] = Field(default=None, sa_column=Column(String))
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    problem: Problem = Relationship(
        sa_relationship=relationship("Problem", back_populates="attempts")
    )
    user: User = Relationship(
        sa_relationship=relationship("User", back_populates="attempts")
    )


class AttemptFeedback(SQLModel, table=True):
    __tablename__ = "attempt_feedback"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    attempt_id: UUID = Field(foreign_key="attempts.id", index=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    rating: Optional[str] = Field(default=None, sa_column=Column(String(16)))
    comment: Optional[str] = Field(default=None, sa_column=Column(String))
    trace_id: Optional[str] = Field(default=None, sa_column=Column(String(128)))
    observation_id: Optional[str] = Field(default=None, sa_column=Column(String(128)))
    request_id: Optional[str] = Field(default=None, sa_column=Column(String(128)))
    client_request_id: Optional[str] = Field(default=None, sa_column=Column(String(128)))
    session_id: Optional[str] = Field(default=None, sa_column=Column(String(128)))
    feature: Optional[str] = Field(default=None, sa_column=Column(String(64)))
    flow: Optional[str] = Field(default=None, sa_column=Column(String(64)))
    route_name: Optional[str] = Field(default=None, sa_column=Column(String(128)))
    mode: Optional[str] = Field(default=None, sa_column=Column(String(32)))
    model_name: Optional[str] = Field(default=None, sa_column=Column(String(128)))
    prompt_version: Optional[str] = Field(default=None, sa_column=Column(String(64)))
    latency_ms: Optional[int] = Field(default=None, sa_column=Column(Integer))
    tokens_in: Optional[int] = Field(default=None, sa_column=Column(Integer))
    tokens_out: Optional[int] = Field(default=None, sa_column=Column(Integer))
    tokens_total: Optional[int] = Field(default=None, sa_column=Column(Integer))
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class AnalyticsEvent(SQLModel, table=True):
    __tablename__ = "analytics_events"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    problem_id: Optional[UUID] = Field(default=None, foreign_key="problems.id", index=True)
    attempt_id: Optional[UUID] = Field(default=None, foreign_key="attempts.id", index=True)
    event_type: Optional[str] = Field(default=None, sa_column=Column(String(64)))
    mode: Optional[str] = Field(default=None, sa_column=Column(String(32)))
    verdict: Optional[str] = Field(default=None, sa_column=Column(String(64)))
    metadata_json: Optional[str] = Field(default=None, sa_column=Column(String))
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ErrorEvent(SQLModel, table=True):
    __tablename__ = "error_events"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    attempt_id: UUID = Field(foreign_key="attempts.id", index=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    topic: Optional[str] = Field(default=None, sa_column=Column(String(128)))
    subtopic: Optional[str] = Field(default=None, sa_column=Column(String(128)))
    wrong_step: Optional[str] = Field(default=None, sa_column=Column(String))
    correct_step: Optional[str] = Field(default=None, sa_column=Column(String))
    error_type: Optional[str] = Field(default=None, sa_column=Column(String(64)))
    confidence: Optional[float] = Field(default=None, sa_column=Column(Float))
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class AttemptLabel(SQLModel, table=True):
    __tablename__ = "attempt_labels"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    attempt_id: UUID = Field(foreign_key="attempts.id", index=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    anon_user_id: str = Field(sa_column=Column(String(64), nullable=False, index=True))
    label_source: str = Field(sa_column=Column(String(32), nullable=False))
    label_name: str = Field(sa_column=Column(String(64), nullable=False))
    label_value: str = Field(sa_column=Column(String(256), nullable=False))
    confidence: Optional[float] = Field(default=None, sa_column=Column(Float))
    notes: Optional[str] = Field(default=None, sa_column=Column(String))
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class AttemptStageMetric(SQLModel, table=True):
    __tablename__ = "attempt_stage_metrics"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    attempt_id: UUID = Field(foreign_key="attempts.id", index=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    anon_user_id: str = Field(sa_column=Column(String(64), nullable=False, index=True))
    stage: str = Field(sa_column=Column(String(32), nullable=False))
    latency_ms: Optional[int] = Field(default=None, sa_column=Column(Integer))
    tokens_in: Optional[int] = Field(default=None, sa_column=Column(Integer))
    tokens_out: Optional[int] = Field(default=None, sa_column=Column(Integer))
    tokens_total: Optional[int] = Field(default=None, sa_column=Column(Integer))
    retry_count: Optional[int] = Field(default=None, sa_column=Column(Integer))
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ErrorBankEntry(SQLModel, table=True):
    __tablename__ = "error_bank_entries"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    anon_user_id: str = Field(sa_column=Column(String(64), nullable=False, index=True))
    error_type: str = Field(sa_column=Column(String(64), nullable=False))
    concept_tag: str = Field(default="", sa_column=Column(String(128), nullable=False))
    count: int = Field(default=1, sa_column=Column(Integer, nullable=False))
    fixed_count: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    unclear_count: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    last_seen_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    __table_args__ = (
        UniqueConstraint(
            "anon_user_id",
            "error_type",
            "concept_tag",
            name="uq_error_bank_entries_anon_error_concept",
        ),
    )


class EvalDataset(SQLModel, table=True):
    __tablename__ = "eval_datasets"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    name: str = Field(sa_column=Column(String(128), nullable=False, index=True))
    description: Optional[str] = Field(default=None, sa_column=Column(String))
    filters_json: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_by_user_id: Optional[UUID] = Field(default=None, foreign_key="users.id", index=True)
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class EvalDatasetItem(SQLModel, table=True):
    __tablename__ = "eval_dataset_items"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    dataset_id: UUID = Field(foreign_key="eval_datasets.id", index=True)
    attempt_id: UUID = Field(foreign_key="attempts.id", index=True)
    split: str = Field(default="eval", sa_column=Column(String(16), nullable=False))
    weight: Optional[float] = Field(default=None, sa_column=Column(Float))
    notes: Optional[str] = Field(default=None, sa_column=Column(String))
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    __table_args__ = (
        UniqueConstraint("dataset_id", "attempt_id", name="uq_eval_dataset_items_dataset_attempt"),
    )


class EvalRun(SQLModel, table=True):
    __tablename__ = "eval_runs"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    dataset_id: UUID = Field(foreign_key="eval_datasets.id", index=True)
    name: str = Field(sa_column=Column(String(128), nullable=False))
    model_name: Optional[str] = Field(default=None, sa_column=Column(String(128)))
    prompt_version: Optional[str] = Field(default=None, sa_column=Column(String(64)))
    status: str = Field(default="created", sa_column=Column(String(32), nullable=False))
    config_json: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    started_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    completed_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class EvalRunResult(SQLModel, table=True):
    __tablename__ = "eval_run_results"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    run_id: UUID = Field(foreign_key="eval_runs.id", index=True)
    attempt_id: UUID = Field(foreign_key="attempts.id", index=True)
    score: Optional[float] = Field(default=None, sa_column=Column(Float))
    verdict_match: Optional[bool] = Field(default=None, sa_column=Column(Boolean))
    output_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    notes: Optional[str] = Field(default=None, sa_column=Column(String))
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    __table_args__ = (
        UniqueConstraint("run_id", "attempt_id", name="uq_eval_run_results_run_attempt"),
    )


class DatasetExport(SQLModel, table=True):
    __tablename__ = "dataset_exports"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    name: str = Field(sa_column=Column(String(128), nullable=False, index=True))
    filters_json: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    row_count: int = Field(default=0, sa_column=Column(Integer, nullable=False))
    contains_publishable_data: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False),
    )
    storage_uri: Optional[str] = Field(default=None, sa_column=Column(String(512)))
    created_by_user_id: Optional[UUID] = Field(default=None, foreign_key="users.id", index=True)
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ExamPack(SQLModel, table=True):
    __tablename__ = "exam_packs"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    anon_user_id: str = Field(sa_column=Column(String(64), nullable=False, index=True))
    title: str = Field(sa_column=Column(String(160), nullable=False))
    pack_size: int = Field(sa_column=Column(Integer, nullable=False))
    build_mode: str = Field(sa_column=Column(String(16), nullable=False))
    feedback_mode: str = Field(sa_column=Column(String(16), nullable=False))
    topics_json: list[str] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    manual_error_targets_json: list[str] | None = Field(default=None, sa_column=Column(JSON))
    status: str = Field(default="ready", sa_column=Column(String(16), nullable=False))
    generation_model: str | None = Field(default=None, sa_column=Column(String(128)))
    generation_prompt_version: str | None = Field(default=None, sa_column=Column(String(64)))
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class ExamPackItem(SQLModel, table=True):
    __tablename__ = "exam_pack_items"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    pack_id: UUID = Field(foreign_key="exam_packs.id", index=True)
    position: int = Field(sa_column=Column(Integer, nullable=False))
    topic: str = Field(sa_column=Column(String(32), nullable=False))
    difficulty: str = Field(sa_column=Column(String(16), nullable=False))
    target_error_type: str | None = Field(default=None, sa_column=Column(String(64)))
    target_concept_tag: str | None = Field(default=None, sa_column=Column(String(128)))
    question_text: str = Field(sa_column=Column(String, nullable=False))
    answer_format: str = Field(sa_column=Column(String(32), nullable=False))
    correct_answer_json: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    grading_rubric_json: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    validator_notes_json: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    created_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    __table_args__ = (
        UniqueConstraint("pack_id", "position", name="uq_exam_pack_items_pack_position"),
    )


class ExamSession(SQLModel, table=True):
    __tablename__ = "exam_sessions"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    pack_id: UUID = Field(foreign_key="exam_packs.id", index=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    anon_user_id: str = Field(sa_column=Column(String(64), nullable=False, index=True))
    status: str = Field(default="in_progress", sa_column=Column(String(16), nullable=False))
    started_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    submitted_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    graded_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    score_correct: int | None = Field(default=None, sa_column=Column(Integer))
    score_total: int | None = Field(default=None, sa_column=Column(Integer))
    score_percent: float | None = Field(default=None, sa_column=Column(Float))


class ExamSessionAnswer(SQLModel, table=True):
    __tablename__ = "exam_session_answers"

    id: UUID = Field(default_factory=uuid4, primary_key=True, index=True)
    session_id: UUID = Field(foreign_key="exam_sessions.id", index=True)
    pack_item_id: UUID = Field(foreign_key="exam_pack_items.id", index=True)
    answer_text: str | None = Field(default=None, sa_column=Column(String))
    is_correct: bool | None = Field(default=None, sa_column=Column(Boolean))
    score: float | None = Field(default=None, sa_column=Column(Float))
    feedback_text: str | None = Field(default=None, sa_column=Column(String))
    graded_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))
    grading_model: str | None = Field(default=None, sa_column=Column(String(128)))
    grading_prompt_version: str | None = Field(default=None, sa_column=Column(String(64)))
    updated_at: datetime = Field(
        default_factory=utcnow,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )

    __table_args__ = (
        UniqueConstraint("session_id", "pack_item_id", name="uq_exam_session_answers_session_item"),
    )
