"""add attempt analytics columns and event tables

Revision ID: 4b2d6f9c1a0e
Revises: e1f5b7c3d2a4
Create Date: 2026-03-09 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "4b2d6f9c1a0e"
down_revision: Union[str, Sequence[str], None] = "e1f5b7c3d2a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("attempts", sa.Column("error_type", sa.String(length=64), nullable=True))
    op.add_column("attempts", sa.Column("model_name", sa.String(length=128), nullable=True))
    op.add_column("attempts", sa.Column("prompt_version", sa.String(length=64), nullable=True))
    op.add_column("attempts", sa.Column("latency_ms", sa.Integer(), nullable=True))
    op.add_column("attempts", sa.Column("tokens_in", sa.Integer(), nullable=True))
    op.add_column("attempts", sa.Column("tokens_out", sa.Integer(), nullable=True))
    op.add_column("attempts", sa.Column("tokens_thoughts", sa.Integer(), nullable=True))
    op.add_column("attempts", sa.Column("tokens_total", sa.Integer(), nullable=True))

    op.create_table(
        "attempt_feedback",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("rating", sa.String(length=16), nullable=True),
        sa.Column("comment", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["attempt_id"], ["attempts.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_attempt_feedback_id"), "attempt_feedback", ["id"], unique=False)
    op.create_index(op.f("ix_attempt_feedback_attempt_id"), "attempt_feedback", ["attempt_id"], unique=False)
    op.create_index(op.f("ix_attempt_feedback_user_id"), "attempt_feedback", ["user_id"], unique=False)

    op.create_table(
        "analytics_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("problem_id", sa.Uuid(), nullable=True),
        sa.Column("attempt_id", sa.Uuid(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=True),
        sa.Column("mode", sa.String(length=32), nullable=True),
        sa.Column("verdict", sa.String(length=64), nullable=True),
        sa.Column("metadata_json", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["attempt_id"], ["attempts.id"]),
        sa.ForeignKeyConstraint(["problem_id"], ["problems.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_analytics_events_id"), "analytics_events", ["id"], unique=False)
    op.create_index(op.f("ix_analytics_events_user_id"), "analytics_events", ["user_id"], unique=False)
    op.create_index(op.f("ix_analytics_events_problem_id"), "analytics_events", ["problem_id"], unique=False)
    op.create_index(op.f("ix_analytics_events_attempt_id"), "analytics_events", ["attempt_id"], unique=False)

    op.create_table(
        "error_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("topic", sa.String(length=128), nullable=True),
        sa.Column("subtopic", sa.String(length=128), nullable=True),
        sa.Column("wrong_step", sa.String(), nullable=True),
        sa.Column("correct_step", sa.String(), nullable=True),
        sa.Column("error_type", sa.String(length=64), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["attempt_id"], ["attempts.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_error_events_id"), "error_events", ["id"], unique=False)
    op.create_index(op.f("ix_error_events_attempt_id"), "error_events", ["attempt_id"], unique=False)
    op.create_index(op.f("ix_error_events_user_id"), "error_events", ["user_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_error_events_user_id"), table_name="error_events")
    op.drop_index(op.f("ix_error_events_attempt_id"), table_name="error_events")
    op.drop_index(op.f("ix_error_events_id"), table_name="error_events")
    op.drop_table("error_events")

    op.drop_index(op.f("ix_analytics_events_attempt_id"), table_name="analytics_events")
    op.drop_index(op.f("ix_analytics_events_problem_id"), table_name="analytics_events")
    op.drop_index(op.f("ix_analytics_events_user_id"), table_name="analytics_events")
    op.drop_index(op.f("ix_analytics_events_id"), table_name="analytics_events")
    op.drop_table("analytics_events")

    op.drop_index(op.f("ix_attempt_feedback_user_id"), table_name="attempt_feedback")
    op.drop_index(op.f("ix_attempt_feedback_attempt_id"), table_name="attempt_feedback")
    op.drop_index(op.f("ix_attempt_feedback_id"), table_name="attempt_feedback")
    op.drop_table("attempt_feedback")

    op.drop_column("attempts", "tokens_total")
    op.drop_column("attempts", "tokens_thoughts")
    op.drop_column("attempts", "tokens_out")
    op.drop_column("attempts", "tokens_in")
    op.drop_column("attempts", "latency_ms")
    op.drop_column("attempts", "prompt_version")
    op.drop_column("attempts", "model_name")
    op.drop_column("attempts", "error_type")
