"""add langfuse observability columns

Revision ID: b9f2e3a1c4d5
Revises: 4b2d6f9c1a0e
Create Date: 2026-03-10 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b9f2e3a1c4d5"
down_revision: Union[str, Sequence[str], None] = "4b2d6f9c1a0e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def add_column_if_missing(table_name: str, column: sa.Column) -> None:
        existing = {c["name"] for c in inspector.get_columns(table_name)}
        if column.name not in existing:
            op.add_column(table_name, column)

    add_column_if_missing("attempts", sa.Column("trace_id", sa.String(length=128), nullable=True))
    add_column_if_missing("attempts", sa.Column("observation_id", sa.String(length=128), nullable=True))
    add_column_if_missing("attempts", sa.Column("request_id", sa.String(length=128), nullable=True))

    add_column_if_missing("attempt_feedback", sa.Column("trace_id", sa.String(length=128), nullable=True))
    add_column_if_missing("attempt_feedback", sa.Column("observation_id", sa.String(length=128), nullable=True))
    add_column_if_missing("attempt_feedback", sa.Column("request_id", sa.String(length=128), nullable=True))
    add_column_if_missing("attempt_feedback", sa.Column("client_request_id", sa.String(length=128), nullable=True))
    add_column_if_missing("attempt_feedback", sa.Column("session_id", sa.String(length=128), nullable=True))
    add_column_if_missing("attempt_feedback", sa.Column("feature", sa.String(length=64), nullable=True))
    add_column_if_missing("attempt_feedback", sa.Column("flow", sa.String(length=64), nullable=True))
    add_column_if_missing("attempt_feedback", sa.Column("route_name", sa.String(length=128), nullable=True))
    add_column_if_missing("attempt_feedback", sa.Column("mode", sa.String(length=32), nullable=True))
    add_column_if_missing("attempt_feedback", sa.Column("model_name", sa.String(length=128), nullable=True))
    add_column_if_missing("attempt_feedback", sa.Column("prompt_version", sa.String(length=64), nullable=True))
    add_column_if_missing("attempt_feedback", sa.Column("latency_ms", sa.Integer(), nullable=True))
    add_column_if_missing("attempt_feedback", sa.Column("tokens_in", sa.Integer(), nullable=True))
    add_column_if_missing("attempt_feedback", sa.Column("tokens_out", sa.Integer(), nullable=True))
    add_column_if_missing("attempt_feedback", sa.Column("tokens_total", sa.Integer(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    def drop_column_if_exists(table_name: str, column_name: str) -> None:
        existing = {c["name"] for c in inspector.get_columns(table_name)}
        if column_name in existing:
            op.drop_column(table_name, column_name)

    drop_column_if_exists("attempt_feedback", "tokens_total")
    drop_column_if_exists("attempt_feedback", "tokens_out")
    drop_column_if_exists("attempt_feedback", "tokens_in")
    drop_column_if_exists("attempt_feedback", "latency_ms")
    drop_column_if_exists("attempt_feedback", "prompt_version")
    drop_column_if_exists("attempt_feedback", "model_name")
    drop_column_if_exists("attempt_feedback", "mode")
    drop_column_if_exists("attempt_feedback", "route_name")
    drop_column_if_exists("attempt_feedback", "flow")
    drop_column_if_exists("attempt_feedback", "feature")
    drop_column_if_exists("attempt_feedback", "session_id")
    drop_column_if_exists("attempt_feedback", "client_request_id")
    drop_column_if_exists("attempt_feedback", "request_id")
    drop_column_if_exists("attempt_feedback", "observation_id")
    drop_column_if_exists("attempt_feedback", "trace_id")

    drop_column_if_exists("attempts", "request_id")
    drop_column_if_exists("attempts", "observation_id")
    drop_column_if_exists("attempts", "trace_id")
