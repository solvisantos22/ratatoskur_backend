"""Add immutable classroom submission snapshots independently of AI attempts.

Revision ID: b3c8d2e1f6a9
Revises: e6a195922bd4
"""

from alembic import op
import sqlalchemy as sa

revision = "b3c8d2e1f6a9"
down_revision = "e6a195922bd4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "classroom_submissions",
        sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
        sa.Column("student_assignment_item_id", sa.Uuid(),
                  sa.ForeignKey("student_assignment_items.id"), nullable=False),
        sa.Column("problem_id", sa.Uuid(),
                  sa.ForeignKey("problems.id", ondelete="SET NULL"), nullable=True),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("solution_page_keys", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("page_count >= 1 AND page_count <= 12", name="ck_submission_page_count"),
    )
    op.create_index("ix_classroom_submissions_student_assignment_item_id",
                    "classroom_submissions", ["student_assignment_item_id"])
    op.create_index("ix_classroom_submissions_problem_id", "classroom_submissions", ["problem_id"])


def downgrade() -> None:
    op.drop_table("classroom_submissions")
