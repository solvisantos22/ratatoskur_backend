"""Let a teacher disable future full-solution requests for an assignment.

Revision ID: a6d4e2f1b9c0
Revises: f2a7c8d9e1b3
"""

from alembic import op
import sqlalchemy as sa

revision = "a6d4e2f1b9c0"
down_revision = "f2a7c8d9e1b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("assignments", sa.Column("allow_reveal", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column("assignments", "allow_reveal")
