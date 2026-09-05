"""Add teacher-owned classes and assignment notebook links.

Revision ID: f2a7c8d9e1b3
Revises: e8b1d4c3f6a2
"""

from alembic import op
import sqlalchemy as sa

revision = "f2a7c8d9e1b3"
down_revision = "e8b1d4c3f6a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "classrooms",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("teacher_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("join_code", sa.String(12), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_classrooms_teacher_id", "classrooms", ["teacher_id"])
    op.create_table(
        "class_memberships",
        sa.Column(
            "class_id",
            sa.Uuid(),
            sa.ForeignKey("classrooms.id"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id"),
            primary_key=True,
            nullable=False,
        ),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_class_memberships_user_id", "class_memberships", ["user_id"])
    op.create_table(
        "assignments",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "class_id", sa.Uuid(), sa.ForeignKey("classrooms.id"), nullable=False
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_assignments_class_id", "assignments", ["class_id"])
    op.create_table(
        "assignment_items",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "assignment_id", sa.Uuid(), sa.ForeignKey("assignments.id"), nullable=False
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("image_key", sa.String(1024), nullable=False),
        sa.UniqueConstraint(
            "assignment_id", "position", name="uq_assignment_item_position"
        ),
    )
    op.create_index(
        "ix_assignment_items_assignment_id", "assignment_items", ["assignment_id"]
    )
    op.create_table(
        "student_assignment_items",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column(
            "item_id", sa.Uuid(), sa.ForeignKey("assignment_items.id"), nullable=False
        ),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "problem_id",
            sa.Uuid(),
            sa.ForeignKey("problems.id", ondelete="SET NULL"),
            nullable=True,
            unique=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("item_id", "user_id", name="uq_student_assignment_item"),
    )
    op.create_index(
        "ix_student_assignment_items_item_id", "student_assignment_items", ["item_id"]
    )
    op.create_index(
        "ix_student_assignment_items_user_id", "student_assignment_items", ["user_id"]
    )


def downgrade() -> None:
    for table in (
        "student_assignment_items",
        "assignment_items",
        "assignments",
        "class_memberships",
        "classrooms",
    ):
        op.drop_table(table)
