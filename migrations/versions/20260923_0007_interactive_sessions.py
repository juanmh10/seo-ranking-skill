"""Persist isolated interactive sessions and messages.

Revision ID: 20260923_0007
Revises: 20260923_0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0007"
down_revision: str | None = "20260923_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "interactive_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("experiment_id", sa.String(length=36), nullable=False),
        sa.Column("model_id", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("location", sa.String(length=80), nullable=False),
        sa.Column("endpoint_type", sa.String(length=80), nullable=False),
        sa.Column("system_prompt_id", sa.String(length=36), nullable=False),
        sa.Column("system_prompt_sha256", sa.String(length=64), nullable=False),
        sa.Column("system_prompt_content", sa.Text(), nullable=False),
        sa.Column("content_mode", sa.String(length=16), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("top_p", sa.Float(), nullable=True),
        sa.Column("generation_seed", sa.Integer(), nullable=True),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("source_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(
            ["experiment_id"], ["experiments.id"], ondelete="CASCADE",
            name="fk_interactive_sessions_experiment_id_experiments",
        ),
        sa.ForeignKeyConstraint(
            ["system_prompt_id"], ["prompts.id"],
            name="fk_interactive_sessions_system_prompt_id_prompts",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_interactive_sessions"),
    )
    op.create_index(
        "ix_interactive_sessions_experiment_id", "interactive_sessions", ["experiment_id"]
    )
    op.create_table(
        "interactive_messages",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("interactive_session_id", sa.String(length=36), nullable=False),
        sa.Column("message_number", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.ForeignKeyConstraint(
            ["interactive_session_id"], ["interactive_sessions.id"], ondelete="CASCADE",
            name="fk_interactive_messages_interactive_session_id_interactive_sessions",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_interactive_messages"),
        sa.UniqueConstraint(
            "interactive_session_id", "message_number",
            name="uq_interactive_messages_interactive_session_id",
        ),
    )
    op.create_index(
        "ix_interactive_messages_interactive_session_id",
        "interactive_messages",
        ["interactive_session_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_interactive_messages_interactive_session_id", table_name="interactive_messages"
    )
    op.drop_table("interactive_messages")
    op.drop_index(
        "ix_interactive_sessions_experiment_id", table_name="interactive_sessions"
    )
    op.drop_table("interactive_sessions")
