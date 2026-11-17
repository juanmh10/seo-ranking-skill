from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.execution import new_id


class AnalysisSession(Base):
    __tablename__ = "analysis_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("experiments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    analysis_model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    system_prompt_version: Mapped[str] = mapped_column(String(80), nullable=False)
    system_prompt_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    selected_run_ids_json: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="active", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    messages: Mapped[list[AnalysisMessage]] = relationship(
        back_populates="analysis_session",
        cascade="all, delete-orphan",
        order_by="AnalysisMessage.message_number",
        lazy="selectin",
    )


class AnalysisMessage(Base):
    __tablename__ = "analysis_messages"
    __table_args__ = (UniqueConstraint("analysis_session_id", "message_number"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    analysis_session_id: Mapped[str] = mapped_column(
        ForeignKey("analysis_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_number: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(24), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    analysis_session: Mapped[AnalysisSession] = relationship(back_populates="messages")
