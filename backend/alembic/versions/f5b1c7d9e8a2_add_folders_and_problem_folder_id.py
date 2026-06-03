"""add folders and problem folder_id

Revision ID: f5b1c7d9e8a2
Revises: d3a9e2f7b41c
Create Date: 2026-03-23 00:00:00.000000

"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "f5b1c7d9e8a2"
down_revision: Union[str, Sequence[str], None] = "d3a9e2f7b41c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "folders",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("color", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "name", name="uq_folders_user_id_name"),
    )
    op.create_index(op.f("ix_folders_id"), "folders", ["id"], unique=False)
    op.create_index(op.f("ix_folders_user_id"), "folders", ["user_id"], unique=False)

    op.add_column("problems", sa.Column("folder_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_problems_folder_id"), "problems", ["folder_id"], unique=False)
    op.create_foreign_key(
        "fk_problems_folder_id_folders",
        "problems",
        "folders",
        ["folder_id"],
        ["id"],
    )

    connection = op.get_bind()
    user_ids = connection.execute(sa.text("SELECT id FROM users")).scalars().all()
    now = datetime.now(timezone.utc)
    for user_id in user_ids:
        folder_id = uuid4()
        connection.execute(
            sa.text(
                """
                INSERT INTO folders (id, user_id, name, color, created_at, updated_at, archived_at)
                VALUES (:id, :user_id, :name, :color, :created_at, :updated_at, :archived_at)
                """
            ),
            {
                "id": folder_id,
                "user_id": user_id,
                "name": "Unsorted",
                "color": "#6B7280",
                "created_at": now,
                "updated_at": now,
                "archived_at": None,
            },
        )
        connection.execute(
            sa.text(
                """
                UPDATE problems
                SET folder_id = :folder_id
                WHERE user_id = :user_id AND folder_id IS NULL
                """
            ),
            {"folder_id": folder_id, "user_id": user_id},
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("fk_problems_folder_id_folders", "problems", type_="foreignkey")
    op.drop_index(op.f("ix_problems_folder_id"), table_name="problems")
    op.drop_column("problems", "folder_id")

    op.drop_index(op.f("ix_folders_user_id"), table_name="folders")
    op.drop_index(op.f("ix_folders_id"), table_name="folders")
    op.drop_table("folders")
