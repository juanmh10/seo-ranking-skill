from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class AnalysisSessionCreate(BaseModel):
    run_ids: list[str] | None = Field(default=None, max_length=25)

    @field_validator("run_ids")
    @classmethod
    def unique_run_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("run_ids must not contain duplicates")
        return value


class AnalysisMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)


class AnalysisMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    analysis_session_id: str
    message_number: int
    role: str
    content: str
    metadata_json: dict[str, object]
    created_at: datetime


class AnalysisSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    experiment_id: str
    analysis_model_id: str
    system_prompt_version: str
    system_prompt_sha256: str
    selected_run_ids_json: list[str]
    status: str
    created_at: datetime
    messages: list[AnalysisMessageRead]
