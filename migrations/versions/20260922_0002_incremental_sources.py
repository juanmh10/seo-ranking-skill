"""Add incremental source documents and labels.

Revision ID: 20260922_0002
Revises: 20260922_0001
Create Date: 2026-09-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260922_0002"
down_revision: str | None = "20260922_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("dataset_id", sa.String(length=36), nullable=False),
        sa.Column("parent_document_id", sa.String(length=36), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=120), nullable=False),
        sa.Column("content_type", sa.String(length=120), nullable=False),
        sa.Column("source_representation", sa.String(length=32), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("raw_content", sa.Text(), nullable=False),
        sa.Column("normalized_content", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("iteration", sa.Integer(), nullable=False),
        sa.Column("entity_key", sa.String(length=160), nullable=True),
        sa.Column("entity_name", sa.String(length=255), nullable=True),
        sa.Column("aliases_json", sa.JSON(), nullable=False),
        sa.Column("counterfactual_group_key", sa.String(length=160), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "iteration >= 0", name=op.f("ck_documents_iteration_non_negative")
        ),
        sa.CheckConstraint(
            "position IS NULL OR (position >= 1 AND position <= 5)",
            name=op.f("ck_documents_position_between_1_and_5"),
        ),
        sa.ForeignKeyConstraint(
            ["dataset_id"],
            ["datasets.id"],
            name=op.f("fk_documents_dataset_id_datasets"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_document_id"],
            ["documents.id"],
            name=op.f("fk_documents_parent_document_id_documents"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
        sa.UniqueConstraint(
            "dataset_id", "position", name=op.f("uq_documents_dataset_id")
        ),
    )
    op.create_index(
        op.f("ix_documents_dataset_id"), "documents", ["dataset_id"], unique=False
    )
    op.create_index(
        op.f("ix_documents_entity_key"), "documents", ["entity_key"], unique=False
    )
    op.create_index(
        op.f("ix_documents_counterfactual_group_key"),
        "documents",
        ["counterfactual_group_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_documents_parent_document_id"),
        "documents",
        ["parent_document_id"],
        unique=False,
    )
    op.create_index(op.f("ix_documents_sha256"), "documents", ["sha256"], unique=False)

    op.create_table(
        "document_labels",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("technique", sa.String(length=64), nullable=False),
        sa.Column("expected_target", sa.Boolean(), nullable=False),
        sa.Column("annotation", sa.Text(), nullable=True),
        sa.Column("annotator", sa.String(length=160), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name=op.f("fk_document_labels_document_id_documents"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_document_labels")),
        sa.UniqueConstraint("document_id", name=op.f("uq_document_labels_document_id")),
    )


def downgrade() -> None:
    op.drop_table("document_labels")
    op.drop_index(op.f("ix_documents_sha256"), table_name="documents")
    op.drop_index(op.f("ix_documents_parent_document_id"), table_name="documents")
    op.drop_index(op.f("ix_documents_counterfactual_group_key"), table_name="documents")
    op.drop_index(op.f("ix_documents_entity_key"), table_name="documents")
    op.drop_index(op.f("ix_documents_dataset_id"), table_name="documents")
    op.drop_table("documents")
