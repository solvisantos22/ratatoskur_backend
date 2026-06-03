"""default analytics consent false

Revision ID: 1f8a7c2e9d34
Revises: e8b1d4c3f6a2
Create Date: 2026-05-26 09:45:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "1f8a7c2e9d34"
down_revision: Union[str, None] = "e8b1d4c3f6a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "users",
        "consent_analytics",
        existing_type=sa.Boolean(),
        server_default=sa.false(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "users",
        "consent_analytics",
        existing_type=sa.Boolean(),
        server_default=sa.true(),
        existing_nullable=False,
    )
