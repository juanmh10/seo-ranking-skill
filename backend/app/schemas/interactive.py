from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator


class InteractiveSessionCreate(BaseModel):
    model_id: str = Field(min_length=1, max_length=255)
    system_prompt_id: str = Field(min_length=1, max_length=36)
    source_document_ids: list[str] = Field(min_length=1, max_length=5)
    content_mode: Literal["RAW", "NORMALIZED", "BOTH"] = "NORMALIZED"
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, gt=0, le=1)
    seed: int | None = None
    max_output_tokens: int = Field(default=2048, ge=1, le=65536)

    @field_validator("source_document_ids")
    @classmethod
    def unique_document_ids(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("source_document_ids must not contain duplicates")
        return value


class InteractiveMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)


class InteractiveMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    interactive_session_id: str
    message_number: int
    role: str
    content: str
    metadata_json: dict[str, object]
    created_at: datetime


class InteractiveSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    experiment_id: str
    model_id: str
    provider: str
    location: str
    endpoint_type: str
    system_prompt_id: str
    system_prompt_sha256: str
    system_prompt_content: str
    content_mode: str
    temperature: float | None
    top_p: float | None
    generation_seed: int | None
    max_output_tokens: int
    source_snapshot_json: list[dict[str, object]]
    status: str
    created_at: datetime
    messages: list[InteractiveMessageRead]

    @field_serializer("source_snapshot_json")
    def omit_source_text_from_session_payload(
        self, value: list[dict[str, object]]
    ) -> list[dict[str, object]]:
        private_fields = {"raw_content", "normalized_content", "content_text"}
        return [
            {key: item for key, item in source.items() if key not in private_fields}
            for source in value
        ]
