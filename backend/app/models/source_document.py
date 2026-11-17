from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class SourceOrigin(StrEnum):
    UPLOAD = "upload"
    MANUAL = "manual"
    MODEL_OUTPUT = "model_output"


class SourceRepresentation(StrEnum):
    HTML = "html"
    TEXT = "text"
    MARKDOWN = "markdown"
    JSON = "json"
    JSON_LD = "jsonld"
    XML = "xml"


class Severity(StrEnum):
    NEUTRAL = "neutral"
    LOW = "low"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"
    HARMFUL = "harmful"


class Technique(StrEnum):
    NONE = "none"
    SELF_PROMOTION = "self_promotion"
    AUTHORITY_CLAIM = "authority_claim"
    RANKING_INSTRUCTION = "ranking_instruction"
    DIRECT_PROMPT_INJECTION = "direct_prompt_injection"
    INDIRECT_PROMPT_INJECTION = "indirect_prompt_injection"
    SYSTEM_IMPERSONATION = "system_impersonation"
    COMPETITOR_SUPPRESSION = "competitor_suppression"
    FABRICATED_CONSENSUS = "fabricated_consensus"
    CITATION_MANIPULATION = "citation_manipulation"
    STRUCTURED_DATA_MANIPULATION = "structured_data_manipulation"
    HIDDEN_CONTENT = "hidden_content"
    INSTRUCTION_OVERRIDE = "instruction_override"


class SourceDocument(Base):
    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("dataset_id", "position"),
        CheckConstraint(
            "position IS NULL OR (position >= 1 AND position <= 5)",
            name="position_between_1_and_5",
        ),
        CheckConstraint("iteration >= 0", name="iteration_non_negative"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    lineage_id: Mapped[str | None] = mapped_column(String(36), index=True)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    parent_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    source_representation: Mapped[str] = mapped_column(String(32), nullable=False)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_content: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_content: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int | None] = mapped_column(Integer)
    iteration: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    entity_key: Mapped[str | None] = mapped_column(String(160), index=True)
    entity_name: Mapped[str | None] = mapped_column(String(255))
    aliases_json: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    counterfactual_group_key: Mapped[str | None] = mapped_column(String(160), index=True)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    dataset: Mapped[Dataset] = relationship(back_populates="documents")
    label: Mapped[DocumentLabel] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        single_parent=True,
        uselist=False,
        lazy="selectin",
    )
    parent: Mapped[SourceDocument | None] = relationship(
        back_populates="children",
        remote_side="SourceDocument.id",
    )
    children: Mapped[list[SourceDocument]] = relationship(back_populates="parent")


class DocumentLabel(Base):
    __tablename__ = "document_labels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    document_id: Mapped[str] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    severity: Mapped[str] = mapped_column(
        String(32), default=Severity.NEUTRAL.value, nullable=False
    )
    technique: Mapped[str] = mapped_column(String(64), default=Technique.NONE.value, nullable=False)
    expected_target: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    annotation: Mapped[str | None] = mapped_column(Text)
    annotator: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    document: Mapped[SourceDocument] = relationship(back_populates="label")


from app.models.experiment import Dataset  # noqa: E402
