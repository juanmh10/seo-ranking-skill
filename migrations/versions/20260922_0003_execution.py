"""Add configured models, immutable prompts, run snapshots and events.

Revision ID: 20260922_0003
Revises: 20260922_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260922_0003"
down_revision: str | None = "20260922_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def timestamp() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        server_default=sa.text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "model_registry",
        sa.Column("model_id", sa.String(255), primary_key=True),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("location", sa.String(80), nullable=False),
        sa.Column("endpoint_type", sa.String(80), nullable=False),
        sa.Column("supports_temperature", sa.Boolean(), nullable=False),
        sa.Column("supports_top_p", sa.Boolean(), nullable=False),
        sa.Column("supports_seed", sa.Boolean(), nullable=False),
        sa.Column("supports_reasoning", sa.Boolean(), nullable=False),
        sa.Column("supports_structured_output", sa.Boolean(), nullable=False),
        sa.Column("max_context", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("last_verified_at", sa.DateTime(timezone=True)),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
    )
    op.create_table(
        "prompts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        timestamp(),
        sa.UniqueConstraint("name", "type", "version", name=op.f("uq_prompts_name")),
    )
    op.create_table(
        "model_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(80), nullable=False),
        sa.Column("model_id", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(160), nullable=False),
        sa.Column("location", sa.String(80), nullable=False),
        sa.Column("temperature", sa.Float()),
        sa.Column("top_p", sa.Float()),
        sa.Column("seed", sa.Integer()),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("thinking_config_json", sa.JSON(), nullable=False),
        sa.Column("extra_config_json", sa.JSON(), nullable=False),
        timestamp(),
    )
    op.create_table(
        "run_configs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "experiment_id",
            sa.String(36),
            sa.ForeignKey("experiments.id"),
            nullable=False,
        ),
        sa.Column(
            "dataset_id", sa.String(36), sa.ForeignKey("datasets.id"), nullable=False
        ),
        sa.Column(
            "model_config_id",
            sa.String(36),
            sa.ForeignKey("model_configs.id"),
            nullable=False,
        ),
        sa.Column(
            "system_prompt_id",
            sa.String(36),
            sa.ForeignKey("prompts.id"),
            nullable=False,
        ),
        sa.Column("user_prompt", sa.Text(), nullable=False),
        sa.Column("content_mode", sa.String(16), nullable=False),
        sa.Column("ordering_strategy", sa.String(32), nullable=False),
        sa.Column("random_seed", sa.Integer()),
        sa.Column("repetitions", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        timestamp(),
        sa.UniqueConstraint(
            "experiment_id",
            "idempotency_key",
            name=op.f("uq_run_configs_experiment_id"),
        ),
    )
    op.create_index(
        op.f("ix_run_configs_experiment_id"), "run_configs", ["experiment_id"]
    )
    op.create_table(
        "runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_config_id",
            sa.String(36),
            sa.ForeignKey("run_configs.id"),
            nullable=False,
        ),
        sa.Column("run_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("duration_ms", sa.Integer()),
        sa.Column("model_id_actual", sa.String(255)),
        sa.Column("provider", sa.String(80)),
        sa.Column("region", sa.String(80)),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("total_tokens", sa.Integer()),
        sa.Column("request_id", sa.String(255)),
        sa.Column("trace_id", sa.String(255)),
        sa.Column("response_text", sa.Text()),
        sa.Column("response_json", sa.JSON()),
        sa.Column(
            "output_document_id",
            sa.String(36),
            sa.ForeignKey("documents.id", ondelete="SET NULL"),
        ),
        sa.Column("error_type", sa.String(160)),
        sa.Column("error_message", sa.Text()),
        timestamp(),
        sa.UniqueConstraint(
            "run_config_id", "run_number", name=op.f("uq_runs_run_config_id")
        ),
    )
    op.create_index(op.f("ix_runs_run_config_id"), "runs", ["run_config_id"])
    op.create_table(
        "run_documents",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id"), nullable=False),
        sa.Column(
            "document_id", sa.String(36), sa.ForeignKey("documents.id"), nullable=False
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("content_text", sa.Text(), nullable=False),
        sa.Column("tokens_estimated", sa.Integer(), nullable=False),
        sa.Column("label_snapshot_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint("run_id", "position", name=op.f("uq_run_documents_run_id")),
    )
    op.create_index(op.f("ix_run_documents_run_id"), "run_documents", ["run_id"])
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_config_id",
            sa.String(36),
            sa.ForeignKey("run_configs.id"),
            nullable=False,
        ),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("runs.id")),
        sa.Column("event_type", sa.String(80), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        timestamp(),
    )
    op.create_index(op.f("ix_events_run_config_id"), "events", ["run_config_id"])
    op.create_index(op.f("ix_events_run_id"), "events", ["run_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_events_run_id"), table_name="events")
    op.drop_index(op.f("ix_events_run_config_id"), table_name="events")
    op.drop_table("events")
    op.drop_index(op.f("ix_run_documents_run_id"), table_name="run_documents")
    op.drop_table("run_documents")
    op.drop_index(op.f("ix_runs_run_config_id"), table_name="runs")
    op.drop_table("runs")
    op.drop_index(op.f("ix_run_configs_experiment_id"), table_name="run_configs")
    op.drop_table("run_configs")
    op.drop_table("model_configs")
    op.drop_table("prompts")
    op.drop_table("model_registry")
