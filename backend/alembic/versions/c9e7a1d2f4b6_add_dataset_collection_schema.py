"""add dataset collection schema

Revision ID: c9e7a1d2f4b6
Revises: f5b1c7d9e8a2
Create Date: 2026-03-26 00:00:00.000000

"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Sequence, Union
from uuid import uuid4

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c9e7a1d2f4b6"
down_revision: Union[str, Sequence[str], None] = "f5b1c7d9e8a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("anon_user_id", sa.String(length=64), nullable=True))
    op.add_column(
        "users",
        sa.Column("consent_analytics", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("consent_dataset_internal", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("consent_dataset_publish", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("users", sa.Column("consent_updated_at", sa.DateTime(timezone=True), nullable=True))

    op.create_index("ix_users_anon_user_id", "users", ["anon_user_id"], unique=True)

    connection = op.get_bind()
    user_ids = connection.execute(sa.text("SELECT id FROM users")).scalars().all()
    for user_id in user_ids:
        connection.execute(
            sa.text("UPDATE users SET anon_user_id = :anon_user_id WHERE id = :id"),
            {"anon_user_id": str(uuid4()), "id": user_id},
        )
    op.alter_column("users", "anon_user_id", nullable=False)

    op.add_column("attempts", sa.Column("anon_user_id", sa.String(length=64), nullable=True))
    op.add_column("attempts", sa.Column("client_request_id", sa.String(length=128), nullable=True))
    op.add_column("attempts", sa.Column("session_id", sa.String(length=128), nullable=True))
    op.add_column("attempts", sa.Column("prompt_variant", sa.String(length=32), nullable=True))
    op.add_column("attempts", sa.Column("pipeline_mode", sa.String(length=32), nullable=True))
    op.add_column("attempts", sa.Column("expert_mode", sa.String(length=32), nullable=True))
    op.add_column(
        "attempts",
        sa.Column("solution_page_keys", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "attempts",
        sa.Column("drawing_page_keys", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "attempts",
        sa.Column("raw_response_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    connection.execute(
        sa.text(
            """
            UPDATE attempts a
            SET anon_user_id = u.anon_user_id
            FROM users u
            WHERE a.user_id = u.id
              AND a.anon_user_id IS NULL
            """
        )
    )
    op.alter_column("attempts", "anon_user_id", nullable=False)

    op.create_index(op.f("ix_attempts_anon_user_id"), "attempts", ["anon_user_id"], unique=False)
    op.create_index(
        "ix_attempts_anon_user_id_created_at",
        "attempts",
        ["anon_user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_attempts_prompt_variant_model_name_created_at",
        "attempts",
        ["prompt_variant", "model_name", "created_at"],
        unique=False,
    )

    op.create_table(
        "attempt_labels",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("anon_user_id", sa.String(length=64), nullable=False),
        sa.Column("label_source", sa.String(length=32), nullable=False),
        sa.Column("label_name", sa.String(length=64), nullable=False),
        sa.Column("label_value", sa.String(length=256), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["attempt_id"], ["attempts.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_attempt_labels_id"), "attempt_labels", ["id"], unique=False)
    op.create_index(op.f("ix_attempt_labels_attempt_id"), "attempt_labels", ["attempt_id"], unique=False)
    op.create_index(op.f("ix_attempt_labels_user_id"), "attempt_labels", ["user_id"], unique=False)
    op.create_index(op.f("ix_attempt_labels_anon_user_id"), "attempt_labels", ["anon_user_id"], unique=False)
    op.create_index(
        "ix_attempt_labels_attempt_id_label_name",
        "attempt_labels",
        ["attempt_id", "label_name"],
        unique=False,
    )

    op.create_table(
        "attempt_stage_metrics",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("anon_user_id", sa.String(length=64), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("tokens_total", sa.Integer(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["attempt_id"], ["attempts.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_attempt_stage_metrics_id"), "attempt_stage_metrics", ["id"], unique=False)
    op.create_index(
        op.f("ix_attempt_stage_metrics_attempt_id"),
        "attempt_stage_metrics",
        ["attempt_id"],
        unique=False,
    )
    op.create_index(op.f("ix_attempt_stage_metrics_user_id"), "attempt_stage_metrics", ["user_id"], unique=False)
    op.create_index(
        op.f("ix_attempt_stage_metrics_anon_user_id"),
        "attempt_stage_metrics",
        ["anon_user_id"],
        unique=False,
    )

    op.create_table(
        "error_bank_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("anon_user_id", sa.String(length=64), nullable=False),
        sa.Column("error_type", sa.String(length=64), nullable=False),
        sa.Column("concept_tag", sa.String(length=128), nullable=False, server_default=sa.text("''")),
        sa.Column("count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("fixed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unclear_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "anon_user_id",
            "error_type",
            "concept_tag",
            name="uq_error_bank_entries_anon_error_concept",
        ),
    )
    op.create_index(op.f("ix_error_bank_entries_id"), "error_bank_entries", ["id"], unique=False)
    op.create_index(
        op.f("ix_error_bank_entries_anon_user_id"),
        "error_bank_entries",
        ["anon_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_error_bank_entries_anon_error_concept",
        "error_bank_entries",
        ["anon_user_id", "error_type", "concept_tag"],
        unique=False,
    )

    op.create_table(
        "eval_datasets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "filters_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_eval_datasets_id"), "eval_datasets", ["id"], unique=False)
    op.create_index(op.f("ix_eval_datasets_name"), "eval_datasets", ["name"], unique=False)
    op.create_index(
        op.f("ix_eval_datasets_created_by_user_id"),
        "eval_datasets",
        ["created_by_user_id"],
        unique=False,
    )

    op.create_table(
        "eval_dataset_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("split", sa.String(length=16), nullable=False, server_default="eval"),
        sa.Column("weight", sa.Float(), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["attempt_id"], ["attempts.id"]),
        sa.ForeignKeyConstraint(["dataset_id"], ["eval_datasets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("dataset_id", "attempt_id", name="uq_eval_dataset_items_dataset_attempt"),
    )
    op.create_index(op.f("ix_eval_dataset_items_id"), "eval_dataset_items", ["id"], unique=False)
    op.create_index(op.f("ix_eval_dataset_items_dataset_id"), "eval_dataset_items", ["dataset_id"], unique=False)
    op.create_index(op.f("ix_eval_dataset_items_attempt_id"), "eval_dataset_items", ["attempt_id"], unique=False)

    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=True),
        sa.Column("prompt_version", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="created"),
        sa.Column(
            "config_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["dataset_id"], ["eval_datasets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_eval_runs_id"), "eval_runs", ["id"], unique=False)
    op.create_index(op.f("ix_eval_runs_dataset_id"), "eval_runs", ["dataset_id"], unique=False)

    op.create_table(
        "eval_run_results",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("attempt_id", sa.Uuid(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("verdict_match", sa.Boolean(), nullable=True),
        sa.Column("output_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("notes", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["attempt_id"], ["attempts.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["eval_runs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "attempt_id", name="uq_eval_run_results_run_attempt"),
    )
    op.create_index(op.f("ix_eval_run_results_id"), "eval_run_results", ["id"], unique=False)
    op.create_index(op.f("ix_eval_run_results_run_id"), "eval_run_results", ["run_id"], unique=False)
    op.create_index(op.f("ix_eval_run_results_attempt_id"), "eval_run_results", ["attempt_id"], unique=False)

    op.create_table(
        "dataset_exports",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column(
            "filters_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("row_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("contains_publishable_data", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("storage_uri", sa.String(length=512), nullable=True),
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_dataset_exports_id"), "dataset_exports", ["id"], unique=False)
    op.create_index(op.f("ix_dataset_exports_name"), "dataset_exports", ["name"], unique=False)
    op.create_index(
        op.f("ix_dataset_exports_created_by_user_id"),
        "dataset_exports",
        ["created_by_user_id"],
        unique=False,
    )

    connection.execute(
        sa.text(
            """
            UPDATE users
            SET consent_updated_at = :updated_at
            WHERE consent_updated_at IS NULL
            """
        ),
        {"updated_at": datetime.now(timezone.utc)},
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_dataset_exports_created_by_user_id"), table_name="dataset_exports")
    op.drop_index(op.f("ix_dataset_exports_name"), table_name="dataset_exports")
    op.drop_index(op.f("ix_dataset_exports_id"), table_name="dataset_exports")
    op.drop_table("dataset_exports")

    op.drop_index(op.f("ix_eval_run_results_attempt_id"), table_name="eval_run_results")
    op.drop_index(op.f("ix_eval_run_results_run_id"), table_name="eval_run_results")
    op.drop_index(op.f("ix_eval_run_results_id"), table_name="eval_run_results")
    op.drop_table("eval_run_results")

    op.drop_index(op.f("ix_eval_runs_dataset_id"), table_name="eval_runs")
    op.drop_index(op.f("ix_eval_runs_id"), table_name="eval_runs")
    op.drop_table("eval_runs")

    op.drop_index(op.f("ix_eval_dataset_items_attempt_id"), table_name="eval_dataset_items")
    op.drop_index(op.f("ix_eval_dataset_items_dataset_id"), table_name="eval_dataset_items")
    op.drop_index(op.f("ix_eval_dataset_items_id"), table_name="eval_dataset_items")
    op.drop_table("eval_dataset_items")

    op.drop_index(op.f("ix_eval_datasets_created_by_user_id"), table_name="eval_datasets")
    op.drop_index(op.f("ix_eval_datasets_name"), table_name="eval_datasets")
    op.drop_index(op.f("ix_eval_datasets_id"), table_name="eval_datasets")
    op.drop_table("eval_datasets")

    op.drop_index("ix_error_bank_entries_anon_error_concept", table_name="error_bank_entries")
    op.drop_index(op.f("ix_error_bank_entries_anon_user_id"), table_name="error_bank_entries")
    op.drop_index(op.f("ix_error_bank_entries_id"), table_name="error_bank_entries")
    op.drop_table("error_bank_entries")

    op.drop_index(op.f("ix_attempt_stage_metrics_anon_user_id"), table_name="attempt_stage_metrics")
    op.drop_index(op.f("ix_attempt_stage_metrics_user_id"), table_name="attempt_stage_metrics")
    op.drop_index(op.f("ix_attempt_stage_metrics_attempt_id"), table_name="attempt_stage_metrics")
    op.drop_index(op.f("ix_attempt_stage_metrics_id"), table_name="attempt_stage_metrics")
    op.drop_table("attempt_stage_metrics")

    op.drop_index("ix_attempt_labels_attempt_id_label_name", table_name="attempt_labels")
    op.drop_index(op.f("ix_attempt_labels_anon_user_id"), table_name="attempt_labels")
    op.drop_index(op.f("ix_attempt_labels_user_id"), table_name="attempt_labels")
    op.drop_index(op.f("ix_attempt_labels_attempt_id"), table_name="attempt_labels")
    op.drop_index(op.f("ix_attempt_labels_id"), table_name="attempt_labels")
    op.drop_table("attempt_labels")

    op.drop_index("ix_attempts_prompt_variant_model_name_created_at", table_name="attempts")
    op.drop_index("ix_attempts_anon_user_id_created_at", table_name="attempts")
    op.drop_index(op.f("ix_attempts_anon_user_id"), table_name="attempts")
    op.drop_column("attempts", "raw_response_json")
    op.drop_column("attempts", "drawing_page_keys")
    op.drop_column("attempts", "solution_page_keys")
    op.drop_column("attempts", "expert_mode")
    op.drop_column("attempts", "pipeline_mode")
    op.drop_column("attempts", "prompt_variant")
    op.drop_column("attempts", "session_id")
    op.drop_column("attempts", "client_request_id")
    op.drop_column("attempts", "anon_user_id")

    op.drop_index("ix_users_anon_user_id", table_name="users")
    op.drop_column("users", "consent_updated_at")
    op.drop_column("users", "consent_dataset_publish")
    op.drop_column("users", "consent_dataset_internal")
    op.drop_column("users", "consent_analytics")
    op.drop_column("users", "anon_user_id")
