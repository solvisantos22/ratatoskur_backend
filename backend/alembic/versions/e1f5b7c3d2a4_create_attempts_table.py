"""create attempts table

Revision ID: e1f5b7c3d2a4
Revises: c4d1e8b2a9f0
Create Date: 2026-02-16 20:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e1f5b7c3d2a4"
down_revision: Union[str, Sequence[str], None] = "c4d1e8b2a9f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "attempts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("problem_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("problem_image_key", sa.String(length=1024), nullable=True),
        sa.Column("solution_image_key", sa.String(length=1024), nullable=True),
        sa.Column("drawing_data_key", sa.String(length=1024), nullable=True),
        sa.Column("verdict", sa.String(length=64), nullable=True),
        sa.Column("response_type", sa.String(length=64), nullable=True),
        sa.Column("message_is", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["problem_id"], ["problems.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_attempts_id"), "attempts", ["id"], unique=False)
    op.create_index(op.f("ix_attempts_problem_id"), "attempts", ["problem_id"], unique=False)
    op.create_index(op.f("ix_attempts_user_id"), "attempts", ["user_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_attempts_user_id"), table_name="attempts")
    op.drop_index(op.f("ix_attempts_problem_id"), table_name="attempts")
    op.drop_index(op.f("ix_attempts_id"), table_name="attempts")
    op.drop_table("attempts")
