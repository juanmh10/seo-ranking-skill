from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


def new_id() -> str:
    return str(uuid.uuid4())


class ModelRegistry(Base):
    __tablename__ = "model_registry"

    model_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    location: Mapped[str] = mapped_column(String(80), nullable=False)
    endpoint_type: Mapped[str] = mapped_column(String(80), nullable=False)
    supports_temperature: Mapped[bool] = mapped_column(Boolean, nullable=False)
    supports_top_p: Mapped[bool] = mapped_column(Boolean, nullable=False)
    supports_seed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    supports_reasoning: Mapped[bool] = mapped_column(Boolean, nullable=False)
    supports_structured_output: Mapped[bool] = mapped_column(Boolean, nullable=False)
    max_context: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)


class Prompt(Base):
    __tablename__ = "prompts"
    __table_args__ = (UniqueConstraint("name", "type", "version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ModelConfig(Base):
    __tablename__ = "model_configs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(160), nullable=False)
    location: Mapped[str] = mapped_column(String(80), nullable=False)
    temperature: Mapped[float | None] = mapped_column(nullable=True)
    top_p: Mapped[float | None] = mapped_column(nullable=True)
    seed: Mapped[int | None] = mapped_column(Integer)
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    thinking_config_json: Mapped[dict[str, object]] = mapped_column(
        JSON, default=dict, nullable=False
    )
    extra_config_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RunConfig(Base):
    __tablename__ = "run_configs"
    __table_args__ = (UniqueConstraint("experiment_id", "idempotency_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("experiments.id"), nullable=False, index=True
    )
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), nullable=False)
    model_config_id: Mapped[str] = mapped_column(ForeignKey("model_configs.id"), nullable=False)
    system_prompt_id: Mapped[str] = mapped_column(ForeignKey("prompts.id"), nullable=False)
    evaluation_model_config_id: Mapped[str | None] = mapped_column(
        ForeignKey("model_configs.id"), index=True
    )
    user_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    content_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    ordering_strategy: Mapped[str] = mapped_column(String(32), nullable=False)
    random_seed: Mapped[int | None] = mapped_column(Integer)
    repetitions: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    model_config: Mapped[ModelConfig] = relationship(
        foreign_keys=[model_config_id], lazy="selectin"
    )
    evaluation_model_config: Mapped[ModelConfig | None] = relationship(
        foreign_keys=[evaluation_model_config_id], lazy="selectin"
    )
    system_prompt: Mapped[Prompt] = relationship(lazy="selectin")
    runs: Mapped[list[Run]] = relationship(back_populates="run_config", lazy="selectin")


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (UniqueConstraint("run_config_id", "run_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_config_id: Mapped[str] = mapped_column(
        ForeignKey("run_configs.id"), nullable=False, index=True
    )
    run_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="queued", nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    model_id_actual: Mapped[str | None] = mapped_column(String(255))
    provider: Mapped[str | None] = mapped_column(String(80))
    region: Mapped[str | None] = mapped_column(String(80))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    request_id: Mapped[str | None] = mapped_column(String(255))
    trace_id: Mapped[str | None] = mapped_column(String(255))
    response_text: Mapped[str | None] = mapped_column(Text)
    response_json: Mapped[dict[str, object] | None] = mapped_column(JSON)
    output_document_id: Mapped[str | None] = mapped_column(
        ForeignKey("documents.id", ondelete="SET NULL")
    )
    error_type: Mapped[str | None] = mapped_column(String(160))
    error_message: Mapped[str | None] = mapped_column(Text)
    evaluation_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run_config: Mapped[RunConfig] = relationship(back_populates="runs")
    documents: Mapped[list[RunDocument]] = relationship(
        back_populates="run", order_by="RunDocument.position", lazy="selectin"
    )
    eval_results: Mapped[list[EvalResult]] = relationship(back_populates="run", lazy="selectin")


class RunDocument(Base):
    __tablename__ = "run_documents"
    __table_args__ = (UniqueConstraint("run_id", "position"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), nullable=False, index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    tokens_estimated: Mapped[int] = mapped_column(Integer, nullable=False)
    label_snapshot_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)

    run: Mapped[Run] = relationship(back_populates="documents")


class EvalDefinition(Base):
    __tablename__ = "eval_definitions"
    __table_args__ = (
        UniqueConstraint("metric_name", "version", name="uq_eval_definitions_metric_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    evaluator_type: Mapped[str] = mapped_column(String(40), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    config_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    prompt_id: Mapped[str | None] = mapped_column(ForeignKey("prompts.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EvalResult(Base):
    __tablename__ = "eval_results"
    __table_args__ = (
        UniqueConstraint("run_id", "eval_definition_id", name="uq_eval_results_run_definition"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    eval_definition_id: Mapped[str] = mapped_column(
        ForeignKey("eval_definitions.id"), nullable=False, index=True
    )
    score: Mapped[float | None] = mapped_column(Float)
    passed: Mapped[bool | None] = mapped_column(Boolean)
    label: Mapped[str | None] = mapped_column(String(120))
    reasoning: Mapped[str | None] = mapped_column(Text)
    evidence_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    raw_result_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    evaluator_model: Mapped[str | None] = mapped_column(String(255))
    evaluator_version: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped[Run] = relationship(back_populates="eval_results")
    definition: Mapped[EvalDefinition] = relationship(lazy="joined")


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_config_id: Mapped[str] = mapped_column(
        ForeignKey("run_configs.id"), nullable=False, index=True
    )
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
