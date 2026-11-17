"""Persist read-only analysis sessions and messages.

Revision ID: 20260923_0006
Revises: 20260923_0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0006"
down_revision: str | None = "20260923_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analysis_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("experiment_id", sa.String(length=36), nullable=False),
        sa.Column("analysis_model_id", sa.String(length=255), nullable=False),
        sa.Column("system_prompt_version", sa.String(length=80), nullable=False),
        sa.Column("system_prompt_sha256", sa.String(length=64), nullable=False),
        sa.Column("selected_run_ids_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["experiment_id"],
            ["experiments.id"],
            ondelete="CASCADE",
            name="fk_analysis_sessions_experiment_id_experiments",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_analysis_sessions"),
    )
    op.create_index(
        "ix_analysis_sessions_experiment_id", "analysis_sessions", ["experiment_id"]
    )
    op.create_table(
        "analysis_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("analysis_session_id", sa.String(length=36), nullable=False),
        sa.Column("message_number", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["analysis_session_id"],
            ["analysis_sessions.id"],
            ondelete="CASCADE",
            name="fk_analysis_messages_analysis_session_id_analysis_sessions",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_analysis_messages"),
        sa.UniqueConstraint(
            "analysis_session_id",
            "message_number",
            name="uq_analysis_messages_analysis_session_id",
        ),
    )
    op.create_index(
        "ix_analysis_messages_analysis_session_id",
        "analysis_messages",
        ["analysis_session_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_analysis_messages_analysis_session_id", table_name="analysis_messages"
    )
    op.drop_table("analysis_messages")
    op.drop_index("ix_analysis_sessions_experiment_id", table_name="analysis_sessions")
    op.drop_table("analysis_sessions")
