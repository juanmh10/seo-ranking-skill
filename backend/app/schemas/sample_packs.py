from pydantic import BaseModel, ConfigDict

from app.schemas.source_document import SourceDocumentSummary


class SamplePackRead(BaseModel):
    id: str
    name: str
    description: str
    document_count: int
    recommended_question: str


class SamplePackImportRead(BaseModel):
    sample_pack: SamplePackRead
    dataset_id: str
    documents: list[SourceDocumentSummary]

    model_config = ConfigDict(from_attributes=True)
