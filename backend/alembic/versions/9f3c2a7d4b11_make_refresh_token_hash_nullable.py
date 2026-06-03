"""make refresh_tokens.token_hash nullable after selector migration

Revision ID: 9f3c2a7d4b11
Revises: 2e9a6b9a1e4d
Create Date: 2026-02-08 15:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9f3c2a7d4b11"
down_revision: Union[str, Sequence[str], None] = "2e9a6b9a1e4d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "refresh_tokens",
        "token_hash",
        existing_type=sa.String(length=255),
        nullable=True,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "refresh_tokens",
        "token_hash",
        existing_type=sa.String(length=255),
        nullable=False,
    )
