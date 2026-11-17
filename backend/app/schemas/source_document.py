from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.source_document import Severity, SourceOrigin, SourceRepresentation, Technique


class DocumentLabelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    severity: Severity
    technique: Technique
    expected_target: bool
    annotation: str | None
    annotator: str | None


class DocumentLabelUpdate(BaseModel):
    severity: Severity | None = None
    technique: Technique | None = None
    expected_target: bool | None = None
    annotation: str | None = Field(default=None, max_length=4000)
    annotator: str | None = Field(default=None, max_length=160)


class SourceDocumentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    dataset_id: str
    parent_document_id: str | None
    filename: str
    mime_type: str
    source_representation: SourceRepresentation
    origin: SourceOrigin
    sha256: str
    byte_size: int
    position: int | None
    iteration: int
    entity_key: str | None
    entity_name: str | None
    counterfactual_group_key: str | None
    label: DocumentLabelRead
    created_at: datetime


class SourceDocumentRead(SourceDocumentSummary):
    content_type: str
    raw_content: str
    normalized_content: str
    aliases_json: list[str]
    metadata_json: dict[str, object]


class SourceDocumentList(BaseModel):
    items: list[SourceDocumentSummary]
    total: int
    active_count: int


class SourceDocumentUpdate(BaseModel):
    position: int | None = Field(default=None, ge=1, le=5)
    entity_key: str | None = Field(default=None, max_length=160)
    entity_name: str | None = Field(default=None, max_length=255)
    aliases: list[str] | None = Field(default=None, max_length=50)
    counterfactual_group_key: str | None = Field(default=None, max_length=160)


class SourceContentCreate(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    representation: SourceRepresentation
    origin: SourceOrigin = SourceOrigin.MANUAL
    position: int | None = Field(default=None, ge=1, le=5)
    iteration: int = Field(default=0, ge=0)
    parent_document_id: str | None = None
    entity_key: str | None = Field(default=None, max_length=160)
    entity_name: str | None = Field(default=None, max_length=255)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    counterfactual_group_key: str | None = Field(default=None, max_length=160)
    provenance: dict[str, object] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_model_output_iteration(self) -> "SourceContentCreate":
        if self.origin is SourceOrigin.UPLOAD:
            raise ValueError("Use the multipart upload endpoint for uploaded sources")
        if self.origin is SourceOrigin.MODEL_OUTPUT and self.iteration < 1:
            raise ValueError("Model outputs require iteration >= 1")
        return self
