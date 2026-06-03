"""add full_name to users

Revision ID: a6d4f1b8c2e7
Revises: b9f2e3a1c4d5
Create Date: 2026-03-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a6d4f1b8c2e7"
down_revision: Union[str, Sequence[str], None] = "b9f2e3a1c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("full_name", sa.String(length=128), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("users", "full_name")
