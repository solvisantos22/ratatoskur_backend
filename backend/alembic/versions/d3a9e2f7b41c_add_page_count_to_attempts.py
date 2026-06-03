"""add page_count to attempts

Revision ID: d3a9e2f7b41c
Revises: a6d4f1b8c2e7
Create Date: 2026-03-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d3a9e2f7b41c"
down_revision: Union[str, Sequence[str], None] = "a6d4f1b8c2e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("attempts", sa.Column("page_count", sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("attempts", "page_count")
