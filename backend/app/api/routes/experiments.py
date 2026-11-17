from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.schemas.experiment import (
    ExperimentCreate,
    ExperimentList,
    ExperimentRead,
    ExperimentUpdate,
)
from app.services.experiments import ExperimentNotFoundError, ExperimentService

router = APIRouter(prefix="/experiments", tags=["experiments"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]


@router.post("", response_model=ExperimentRead, status_code=status.HTTP_201_CREATED)
async def create_experiment(
    payload: ExperimentCreate, session: SessionDependency
) -> ExperimentRead:
    experiment = await ExperimentService(session).create(payload)
    return ExperimentRead.model_validate(experiment)


@router.get("", response_model=ExperimentList)
async def list_experiments(
    session: SessionDependency,
    include_archived: Annotated[bool, Query()] = False,
) -> ExperimentList:
    items, total = await ExperimentService(session).list(include_archived=include_archived)
    return ExperimentList(
        items=[ExperimentRead.model_validate(item) for item in items],
        total=total,
    )


@router.get("/{experiment_id}", response_model=ExperimentRead)
async def get_experiment(experiment_id: str, session: SessionDependency) -> ExperimentRead:
    try:
        experiment = await ExperimentService(session).get(experiment_id)
    except ExperimentNotFoundError as error:
        raise HTTPException(status_code=404, detail="Experiment not found") from error
    return ExperimentRead.model_validate(experiment)


@router.patch("/{experiment_id}", response_model=ExperimentRead)
async def update_experiment(
    experiment_id: str,
    payload: ExperimentUpdate,
    session: SessionDependency,
) -> ExperimentRead:
    try:
        experiment = await ExperimentService(session).update(experiment_id, payload)
    except ExperimentNotFoundError as error:
        raise HTTPException(status_code=404, detail="Experiment not found") from error
    return ExperimentRead.model_validate(experiment)
