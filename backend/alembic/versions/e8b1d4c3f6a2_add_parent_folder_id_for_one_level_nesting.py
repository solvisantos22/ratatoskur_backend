"""add parent folder id for one-level nesting

Revision ID: e8b1d4c3f6a2
Revises: d7e2b4c1a9f0
Create Date: 2026-03-28 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e8b1d4c3f6a2"
down_revision: Union[str, Sequence[str], None] = "d7e2b4c1a9f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("folders", sa.Column("parent_folder_id", sa.Uuid(), nullable=True))
    op.create_index(
        op.f("ix_folders_parent_folder_id"),
        "folders",
        ["parent_folder_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_folders_parent_folder_id_folders",
        "folders",
        "folders",
        ["parent_folder_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        "fk_folders_parent_folder_id_folders",
        "folders",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_folders_parent_folder_id"), table_name="folders")
    op.drop_column("folders", "parent_folder_id")
