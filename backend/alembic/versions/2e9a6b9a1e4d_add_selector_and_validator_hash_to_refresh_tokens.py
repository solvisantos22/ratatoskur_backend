"""add selector and validator_hash to refresh_tokens

Revision ID: 2e9a6b9a1e4d
Revises: 7aaa92a346d0
Create Date: 2026-02-08 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2e9a6b9a1e4d"
down_revision: Union[str, Sequence[str], None] = "7aaa92a346d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "refresh_tokens",
        sa.Column("selector", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "refresh_tokens",
        sa.Column("validator_hash", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_refresh_tokens_selector",
        "refresh_tokens",
        ["selector"],
        unique=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("ix_refresh_tokens_selector", table_name="refresh_tokens")
    op.drop_column("refresh_tokens", "validator_hash")
    op.drop_column("refresh_tokens", "selector")
