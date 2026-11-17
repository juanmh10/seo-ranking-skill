from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.models.source_document import SourceOrigin
from app.schemas.source_document import (
    DocumentLabelUpdate,
    SourceContentCreate,
    SourceDocumentList,
    SourceDocumentRead,
    SourceDocumentSummary,
    SourceDocumentUpdate,
)
from app.services.source_documents import (
    DatasetNotEditableError,
    SourceDocumentConflictError,
    SourceDocumentNotFoundError,
    SourceDocumentService,
    SourceProvenance,
)
from app.services.source_normalizer import SourceValidationError, normalize_source

router = APIRouter(tags=["sources"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]


def _raise_service_error(error: Exception) -> None:
    if isinstance(error, SourceDocumentNotFoundError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, (SourceDocumentConflictError, DatasetNotEditableError)):
        raise HTTPException(status_code=409, detail=str(error)) from error
    if isinstance(error, SourceValidationError):
        raise HTTPException(status_code=error.status_code, detail=str(error)) from error
    raise error


@router.post(
    "/experiments/{experiment_id}/documents",
    response_model=SourceDocumentRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    experiment_id: str,
    session: SessionDependency,
    request: Request,
    file: Annotated[UploadFile, File()],
    position: Annotated[int | None, Form(ge=1, le=5)] = None,
    library_only: Annotated[bool, Form()] = False,
    iteration: Annotated[int, Form(ge=0)] = 0,
    parent_document_id: Annotated[str | None, Form()] = None,
    entity_key: Annotated[str | None, Form(max_length=160)] = None,
    entity_name: Annotated[str | None, Form(max_length=255)] = None,
    counterfactual_group_key: Annotated[str | None, Form(max_length=160)] = None,
) -> SourceDocumentRead:
    if library_only and position is not None:
        raise HTTPException(
            status_code=422,
            detail="A library source cannot be assigned to an active position",
        )
    max_bytes: int = request.app.state.settings.max_source_bytes
    if file.size is not None and file.size > max_bytes:
        raise HTTPException(status_code=413, detail="Source exceeds the 5 MiB limit")
    try:
        data = await file.read(max_bytes + 1)
    finally:
        await file.close()
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail="Source exceeds the 5 MiB limit")
    try:
        source = normalize_source(
            filename=file.filename or "",
            data=data,
            declared_content_type=file.content_type,
        )
        document = await SourceDocumentService(session).create(
            experiment_id=experiment_id,
            source=source,
            provenance=SourceProvenance(
                origin=SourceOrigin.UPLOAD,
                iteration=iteration,
                parent_document_id=parent_document_id,
            ),
            position=position,
            auto_assign=not library_only,
            entity_key=entity_key,
            entity_name=entity_name,
            counterfactual_group_key=counterfactual_group_key,
        )
    except Exception as error:
        _raise_service_error(error)
    return SourceDocumentRead.model_validate(document)


@router.post(
    "/experiments/{experiment_id}/documents/content",
    response_model=SourceDocumentRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_content_document(
    experiment_id: str,
    payload: SourceContentCreate,
    session: SessionDependency,
    request: Request,
) -> SourceDocumentRead:
    data = payload.content.encode("utf-8")
    if len(data) > request.app.state.settings.max_source_bytes:
        raise HTTPException(status_code=413, detail="Source exceeds the 5 MiB limit")
    try:
        source = normalize_source(
            filename=payload.filename,
            data=data,
            representation=payload.representation,
        )
        document = await SourceDocumentService(session).create(
            experiment_id=experiment_id,
            source=source,
            provenance=SourceProvenance(
                origin=payload.origin,
                iteration=payload.iteration,
                parent_document_id=payload.parent_document_id,
                metadata={"provenance": payload.provenance},
            ),
            position=payload.position,
            entity_key=payload.entity_key,
            entity_name=payload.entity_name,
            aliases=payload.aliases,
            counterfactual_group_key=payload.counterfactual_group_key,
        )
    except Exception as error:
        _raise_service_error(error)
    return SourceDocumentRead.model_validate(document)


@router.get(
    "/experiments/{experiment_id}/documents",
    response_model=SourceDocumentList,
)
async def list_documents(
    experiment_id: str,
    session: SessionDependency,
) -> SourceDocumentList:
    try:
        documents, active_count = await SourceDocumentService(session).list(experiment_id)
    except Exception as error:
        _raise_service_error(error)
    return SourceDocumentList(
        items=[SourceDocumentSummary.model_validate(document) for document in documents],
        total=len(documents),
        active_count=active_count,
    )


@router.get("/documents/{document_id}", response_model=SourceDocumentRead)
async def get_document(document_id: str, session: SessionDependency) -> SourceDocumentRead:
    try:
        document = await SourceDocumentService(session).get(document_id)
    except Exception as error:
        _raise_service_error(error)
    return SourceDocumentRead.model_validate(document)


@router.patch("/documents/{document_id}", response_model=SourceDocumentRead)
async def update_document(
    document_id: str,
    payload: SourceDocumentUpdate,
    session: SessionDependency,
) -> SourceDocumentRead:
    try:
        document = await SourceDocumentService(session).update(document_id, payload)
    except Exception as error:
        _raise_service_error(error)
    return SourceDocumentRead.model_validate(document)


@router.patch("/documents/{document_id}/label", response_model=SourceDocumentRead)
async def update_document_label(
    document_id: str,
    payload: DocumentLabelUpdate,
    session: SessionDependency,
) -> SourceDocumentRead:
    try:
        document = await SourceDocumentService(session).update_label(document_id, payload)
    except Exception as error:
        _raise_service_error(error)
    return SourceDocumentRead.model_validate(document)


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: str, session: SessionDependency) -> None:
    try:
        await SourceDocumentService(session).delete(document_id)
    except Exception as error:
        _raise_service_error(error)
