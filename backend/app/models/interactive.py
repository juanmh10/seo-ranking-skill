from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
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
from app.models.execution import new_id


class InteractiveSession(Base):
    __tablename__ = "interactive_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False)
    location: Mapped[str] = mapped_column(String(80), nullable=False)
    endpoint_type: Mapped[str] = mapped_column(String(80), nullable=False)
    system_prompt_id: Mapped[str] = mapped_column(ForeignKey("prompts.id"), nullable=False)
    system_prompt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    system_prompt_content: Mapped[str] = mapped_column(Text, nullable=False)
    content_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    temperature: Mapped[float | None] = mapped_column(Float)
    top_p: Mapped[float | None] = mapped_column(Float)
    generation_seed: Mapped[int | None] = mapped_column(Integer)
    max_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    source_snapshot_json: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    messages: Mapped[list[InteractiveMessage]] = relationship(
        back_populates="interactive_session",
        cascade="all, delete-orphan",
        order_by="InteractiveMessage.message_number",
        lazy="selectin",
    )


class InteractiveMessage(Base):
    __tablename__ = "interactive_messages"
    __table_args__ = (
        UniqueConstraint("interactive_session_id", "message_number"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    interactive_session_id: Mapped[str] = mapped_column(
        ForeignKey("interactive_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_number: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    interactive_session: Mapped[InteractiveSession] = relationship(back_populates="messages")
