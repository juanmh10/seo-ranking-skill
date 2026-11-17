"""Persist optional model-judge configuration for each run.

Revision ID: 20260923_0005
Revises: 20260922_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260923_0005"
down_revision: str | None = "20260922_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("run_configs") as batch_op:
        batch_op.add_column(
            sa.Column("evaluation_model_config_id", sa.String(36), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_run_configs_evaluation_model_config_id_model_configs",
            "model_configs",
            ["evaluation_model_config_id"],
            ["id"],
        )
    op.create_index(
        "ix_run_configs_evaluation_model_config_id",
        "run_configs",
        ["evaluation_model_config_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_run_configs_evaluation_model_config_id", table_name="run_configs"
    )
    with op.batch_alter_table("run_configs") as batch_op:
        batch_op.drop_constraint(
            "fk_run_configs_evaluation_model_config_id_model_configs",
            type_="foreignkey",
        )
        batch_op.drop_column("evaluation_model_config_id")
