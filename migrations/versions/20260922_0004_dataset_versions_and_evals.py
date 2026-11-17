"""Add copy-on-write lineage and deterministic evaluation results.

Revision ID: 20260922_0004
Revises: 20260922_0003
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260922_0004"
down_revision: str | None = "20260922_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("documents", sa.Column("lineage_id", sa.String(36), nullable=True))
    op.create_index("ix_documents_lineage_id", "documents", ["lineage_id"])
    op.execute("UPDATE documents SET lineage_id = id WHERE lineage_id IS NULL")
    op.execute(
        "UPDATE datasets SET status = 'frozen' "
        "WHERE id IN (SELECT DISTINCT dataset_id FROM run_configs)"
    )
    op.add_column("runs", sa.Column("evaluation_error", sa.Text(), nullable=True))

    op.create_table(
        "eval_definitions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("evaluator_type", sa.String(40), nullable=False),
        sa.Column("metric_name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("config_json", sa.JSON(), nullable=False),
        sa.Column("prompt_id", sa.String(36), sa.ForeignKey("prompts.id")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "metric_name", "version", name="uq_eval_definitions_metric_version"
        ),
    )
    op.create_table(
        "eval_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "eval_definition_id",
            sa.String(36),
            sa.ForeignKey("eval_definitions.id"),
            nullable=False,
        ),
        sa.Column("score", sa.Float()),
        sa.Column("passed", sa.Boolean()),
        sa.Column("label", sa.String(120)),
        sa.Column("reasoning", sa.Text()),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("raw_result_json", sa.JSON(), nullable=False),
        sa.Column("evaluator_model", sa.String(255)),
        sa.Column("evaluator_version", sa.String(80), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "run_id", "eval_definition_id", name="uq_eval_results_run_definition"
        ),
    )
    op.create_index("ix_eval_results_run_id", "eval_results", ["run_id"])
    op.create_index(
        "ix_eval_results_eval_definition_id", "eval_results", ["eval_definition_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_eval_results_eval_definition_id", table_name="eval_results")
    op.drop_index("ix_eval_results_run_id", table_name="eval_results")
    op.drop_table("eval_results")
    op.drop_table("eval_definitions")
    op.drop_column("runs", "evaluation_error")
    op.drop_index("ix_documents_lineage_id", table_name="documents")
    op.drop_column("documents", "lineage_id")
