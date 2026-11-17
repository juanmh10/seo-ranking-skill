from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.schemas.sample_packs import SamplePackImportRead, SamplePackRead
from app.schemas.source_document import SourceDocumentSummary
from app.services.sample_packs import (
    SamplePackConflictError,
    SamplePackNotFoundError,
    import_sample_pack,
    list_sample_packs,
)

router = APIRouter(tags=["sample-packs"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]


@router.get("/sample-packs", response_model=list[SamplePackRead])
async def get_sample_packs() -> list[SamplePackRead]:
    return await list_sample_packs()


@router.post(
    "/experiments/{experiment_id}/sample-packs/{sample_pack_id}",
    response_model=SamplePackImportRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_sample_pack(
    experiment_id: str,
    sample_pack_id: str,
    session: SessionDependency,
) -> SamplePackImportRead:
    try:
        pack, dataset_id, documents = await import_sample_pack(
            session, experiment_id, sample_pack_id
        )
    except SamplePackNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except SamplePackConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return SamplePackImportRead(
        sample_pack=pack,
        dataset_id=dataset_id,
        documents=[SourceDocumentSummary.model_validate(document) for document in documents],
    )
