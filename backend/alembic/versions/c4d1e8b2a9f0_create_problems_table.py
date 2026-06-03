"""create problems table

Revision ID: c4d1e8b2a9f0
Revises: 9f3c2a7d4b11
Create Date: 2026-02-16 18:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c4d1e8b2a9f0"
down_revision: Union[str, Sequence[str], None] = "9f3c2a7d4b11"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "problems",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_problems_id"), "problems", ["id"], unique=False)
    op.create_index(op.f("ix_problems_user_id"), "problems", ["user_id"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_problems_user_id"), table_name="problems")
    op.drop_index(op.f("ix_problems_id"), table_name="problems")
    op.drop_table("problems")
