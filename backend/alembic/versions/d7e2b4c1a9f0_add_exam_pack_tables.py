"""add exam pack tables

Revision ID: d7e2b4c1a9f0
Revises: c9e7a1d2f4b6
Create Date: 2026-03-26 00:30:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "d7e2b4c1a9f0"
down_revision: Union[str, Sequence[str], None] = "c9e7a1d2f4b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "exam_packs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("anon_user_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("pack_size", sa.Integer(), nullable=False),
        sa.Column("build_mode", sa.String(length=16), nullable=False),
        sa.Column("feedback_mode", sa.String(length=16), nullable=False),
        sa.Column(
            "topics_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("manual_error_targets_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ready"),
        sa.Column("generation_model", sa.String(length=128), nullable=True),
        sa.Column("generation_prompt_version", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_exam_packs_id"), "exam_packs", ["id"], unique=False)
    op.create_index(op.f("ix_exam_packs_user_id"), "exam_packs", ["user_id"], unique=False)
    op.create_index(op.f("ix_exam_packs_anon_user_id"), "exam_packs", ["anon_user_id"], unique=False)

    op.create_table(
        "exam_pack_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pack_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("topic", sa.String(length=32), nullable=False),
        sa.Column("difficulty", sa.String(length=16), nullable=False),
        sa.Column("target_error_type", sa.String(length=64), nullable=True),
        sa.Column("target_concept_tag", sa.String(length=128), nullable=True),
        sa.Column("question_text", sa.String(), nullable=False),
        sa.Column(
            "correct_answer_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "grading_rubric_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "validator_notes_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("answer_format", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["pack_id"], ["exam_packs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pack_id", "position", name="uq_exam_pack_items_pack_position"),
    )
    op.create_index(op.f("ix_exam_pack_items_id"), "exam_pack_items", ["id"], unique=False)
    op.create_index(op.f("ix_exam_pack_items_pack_id"), "exam_pack_items", ["pack_id"], unique=False)

    op.create_table(
        "exam_sessions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("pack_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("anon_user_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="in_progress"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("graded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("score_correct", sa.Integer(), nullable=True),
        sa.Column("score_total", sa.Integer(), nullable=True),
        sa.Column("score_percent", sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(["pack_id"], ["exam_packs.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_exam_sessions_id"), "exam_sessions", ["id"], unique=False)
    op.create_index(op.f("ix_exam_sessions_pack_id"), "exam_sessions", ["pack_id"], unique=False)
    op.create_index(op.f("ix_exam_sessions_user_id"), "exam_sessions", ["user_id"], unique=False)
    op.create_index(op.f("ix_exam_sessions_anon_user_id"), "exam_sessions", ["anon_user_id"], unique=False)

    op.create_table(
        "exam_session_answers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("session_id", sa.Uuid(), nullable=False),
        sa.Column("pack_item_id", sa.Uuid(), nullable=False),
        sa.Column("answer_text", sa.String(), nullable=True),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("feedback_text", sa.String(), nullable=True),
        sa.Column("graded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("grading_model", sa.String(length=128), nullable=True),
        sa.Column("grading_prompt_version", sa.String(length=64), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["pack_item_id"], ["exam_pack_items.id"]),
        sa.ForeignKeyConstraint(["session_id"], ["exam_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_id", "pack_item_id", name="uq_exam_session_answers_session_item"),
    )
    op.create_index(op.f("ix_exam_session_answers_id"), "exam_session_answers", ["id"], unique=False)
    op.create_index(
        op.f("ix_exam_session_answers_session_id"),
        "exam_session_answers",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_exam_session_answers_pack_item_id"),
        "exam_session_answers",
        ["pack_item_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_exam_session_answers_pack_item_id"), table_name="exam_session_answers")
    op.drop_index(op.f("ix_exam_session_answers_session_id"), table_name="exam_session_answers")
    op.drop_index(op.f("ix_exam_session_answers_id"), table_name="exam_session_answers")
    op.drop_table("exam_session_answers")

    op.drop_index(op.f("ix_exam_sessions_anon_user_id"), table_name="exam_sessions")
    op.drop_index(op.f("ix_exam_sessions_user_id"), table_name="exam_sessions")
    op.drop_index(op.f("ix_exam_sessions_pack_id"), table_name="exam_sessions")
    op.drop_index(op.f("ix_exam_sessions_id"), table_name="exam_sessions")
    op.drop_table("exam_sessions")

    op.drop_index(op.f("ix_exam_pack_items_pack_id"), table_name="exam_pack_items")
    op.drop_index(op.f("ix_exam_pack_items_id"), table_name="exam_pack_items")
    op.drop_table("exam_pack_items")

    op.drop_index(op.f("ix_exam_packs_anon_user_id"), table_name="exam_packs")
    op.drop_index(op.f("ix_exam_packs_user_id"), table_name="exam_packs")
    op.drop_index(op.f("ix_exam_packs_id"), table_name="exam_packs")
    op.drop_table("exam_packs")
