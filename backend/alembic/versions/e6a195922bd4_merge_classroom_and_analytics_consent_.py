"""merge classroom and analytics consent heads

Revision ID: e6a195922bd4
Revises: 1f8a7c2e9d34, a6d4e2f1b9c0
Create Date: 2026-09-06 11:06:39.806013

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e6a195922bd4'
down_revision: Union[str, Sequence[str], None] = ('1f8a7c2e9d34', 'a6d4e2f1b9c0')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
