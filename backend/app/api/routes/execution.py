import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.dependencies import get_session
from app.models.execution import EvalResult, Event, ModelRegistry, Run, RunConfig
from app.models.experiment import Experiment
from app.schemas.execution import (
    EvalRecomputeRequest,
    EvalResultRead,
    EventRead,
    ExperimentMetricsRead,
    ModelRead,
    PromptCreate,
    PromptRead,
    RunAccepted,
    RunConfigRead,
    RunCreate,
    RunRead,
)
from app.schemas.source_document import SourceDocumentRead
from app.services.catalog import PromptService
from app.services.evaluation import EvaluationService
from app.services.execution import ExecutionService, RunConflictError, RunPreflightError
from app.services.manifest import ManifestService
from app.services.metrics import MetricsService
from app.services.source_documents import DatasetNotEditableError, SourceDocumentNotFoundError

router = APIRouter(tags=["execution"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]


@router.get("/models", response_model=list[ModelRead])
async def list_models(request: Request, session: SessionDependency) -> list[ModelRead]:
    models = (
        await session.scalars(
            select(ModelRegistry)
            .where(ModelRegistry.enabled.is_(True))
            .order_by(ModelRegistry.display_name)
        )
    ).all()
    return [_model_read(model, request) for model in models]


@router.get("/models/{model_id}/capabilities", response_model=ModelRead)
async def model_capabilities(
    model_id: str, request: Request, session: SessionDependency
) -> ModelRead:
    model = await session.get(ModelRegistry, model_id)
    if model is None or not model.enabled:
        raise HTTPException(status_code=404, detail="Model not found")
    return _model_read(model, request)


def _model_read(model: ModelRegistry, request: Request) -> ModelRead:
    result = ModelRead.model_validate(model)
    settings = request.app.state.settings
    if model.endpoint_type == "xai_responses":
        has_xai_key = bool(
            settings.xai_api_key and settings.xai_api_key.get_secret_value().strip()
        )
        result.runnable = has_xai_key
        result.availability_note = (
            None
            if has_xai_key
            else "Configure APP_XAI_API_KEY no backend para habilitar este modelo."
        )
    elif model.endpoint_type == "vertex_anthropic":
        result.runnable = True
        result.availability_note = (
            "Requer que o modelo Claude esteja habilitado e os termos aceitos no Model Garden."
        )
    elif model.endpoint_type == "vertex_gemini":
        result.runnable = True
        result.availability_note = None
    else:
        result.runnable = False
        result.availability_note = "O adapter deste endpoint ainda não está configurado."
    return result


@router.get("/prompts", response_model=list[PromptRead])
async def list_prompts(session: SessionDependency) -> list[PromptRead]:
    return [PromptRead.model_validate(item) for item in await PromptService(session).list()]


@router.post("/prompts", response_model=PromptRead, status_code=status.HTTP_201_CREATED)
async def create_prompt(payload: PromptCreate, session: SessionDependency) -> PromptRead:
    try:
        prompt = await PromptService(session).create(payload.name, payload.content)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return PromptRead.model_validate(prompt)


@router.get("/experiments/{experiment_id}/run-configs", response_model=list[RunConfigRead])
async def list_run_configs(
    experiment_id: str, session: SessionDependency, request: Request
) -> list[RunConfigRead]:
    service = ExecutionService(session, request.app.state.settings)
    return [
        RunConfigRead.model_validate(item) for item in await service.list_configs(experiment_id)
    ]


@router.post(
    "/experiments/{experiment_id}/runs",
    response_model=RunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_run(
    experiment_id: str,
    payload: RunCreate,
    request: Request,
    session: SessionDependency,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=255)],
) -> RunAccepted:
    try:
        config, created = await ExecutionService(session, request.app.state.settings).create(
            experiment_id, payload, idempotency_key
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except RunConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except RunPreflightError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if created:
        request.app.state.execution_engine.enqueue(config.id)
    return RunAccepted(
        run_config_id=config.id,
        run_ids=[run.id for run in sorted(config.runs, key=lambda run: run.run_number)],
        status=config.status,
    )


@router.get("/run-configs/{config_id}", response_model=RunConfigRead)
async def get_run_config(
    config_id: str, request: Request, session: SessionDependency
) -> RunConfigRead:
    try:
        config = await ExecutionService(session, request.app.state.settings).get_config(config_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return RunConfigRead.model_validate(config)


@router.get("/runs/{run_id}", response_model=RunRead)
async def get_run(run_id: str, request: Request, session: SessionDependency) -> RunRead:
    try:
        run = await ExecutionService(session, request.app.state.settings).get_run(run_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return RunRead.model_validate(run)


@router.get("/run-configs/{config_id}/events", response_model=list[EventRead])
async def list_run_events(config_id: str, session: SessionDependency) -> list[EventRead]:
    events = (
        await session.scalars(
            select(Event).where(Event.run_config_id == config_id).order_by(Event.id)
        )
    ).all()
    return [EventRead.model_validate(event) for event in events]


@router.get("/runs/{run_id}/events", response_model=list[EventRead])
async def list_individual_run_events(run_id: str, session: SessionDependency) -> list[EventRead]:
    events = (
        await session.scalars(select(Event).where(Event.run_id == run_id).order_by(Event.id))
    ).all()
    return [EventRead.model_validate(event) for event in events]


@router.get("/runs/{run_id}/evals", response_model=list[EvalResultRead])
async def list_run_evals(run_id: str, session: SessionDependency) -> list[EvalResultRead]:
    if await session.get(Run, run_id) is None:
        raise HTTPException(status_code=404, detail="Run not found")
    results = (
        await session.scalars(
            select(EvalResult)
            .where(EvalResult.run_id == run_id)
            .order_by(EvalResult.created_at, EvalResult.eval_definition_id)
        )
    ).all()
    return [EvalResultRead.model_validate(result) for result in results]


@router.post("/runs/{run_id}/evals/recompute", response_model=list[EvalResultRead])
async def recompute_run_evals(
    run_id: str,
    payload: EvalRecomputeRequest,
    request: Request,
    session: SessionDependency,
) -> list[EvalResultRead]:
    settings = request.app.state.settings
    try:
        async with asyncio.timeout(settings.model_timeout_seconds):
            await EvaluationService(session).recompute_run(
                run_id,
                runner=request.app.state.execution_engine.runner,
                project=settings.gcp_project or "",
                evaluator_model_id=payload.evaluator_model_id,
            )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except TimeoutError as error:
        await session.rollback()
        run = await session.get(Run, run_id)
        if run is not None:
            session.add(
                Event(
                    run_config_id=run.run_config_id,
                    run_id=run_id,
                    event_type="eval_recompute_failed",
                    payload_json={"error_type": "TimeoutError"},
                )
            )
            await session.commit()
        raise HTTPException(
            status_code=504,
            detail="Evaluation model timed out after the configured backend limit",
        ) from error
    results = (
        await session.scalars(
            select(EvalResult)
            .where(EvalResult.run_id == run_id)
            .options(joinedload(EvalResult.definition))
            .order_by(EvalResult.created_at, EvalResult.eval_definition_id)
        )
    ).all()
    return [EvalResultRead.model_validate(result) for result in results]


@router.get("/experiments/{experiment_id}/metrics", response_model=ExperimentMetricsRead)
async def get_experiment_metrics(
    experiment_id: str, session: SessionDependency
) -> ExperimentMetricsRead:
    if await session.get(Experiment, experiment_id) is None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return await MetricsService(session).experiment(experiment_id)


@router.get("/experiments/{experiment_id}/manifest")
async def get_experiment_manifest(
    experiment_id: str, session: SessionDependency
) -> JSONResponse:
    try:
        manifest = await ManifestService(session).build(experiment_id)
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return JSONResponse(
        content=manifest,
        headers={
            "Content-Disposition": (
                f'attachment; filename="experiment-{experiment_id}-manifest.json"'
            )
        },
    )


@router.get("/run-configs/{config_id}/stream")
async def stream_run_events(
    config_id: str,
    request: Request,
    last_event_id: Annotated[int | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    database = request.app.state.database
    async with database.session_factory() as session:
        if await session.get(RunConfig, config_id) is None:
            raise HTTPException(status_code=404, detail="Run configuration not found")

    async def stream():
        cursor = last_event_id or 0
        idle_ticks = 0
        while True:
            if await request.is_disconnected():
                return
            async with database.session_factory() as session:
                events = (
                    await session.scalars(
                        select(Event)
                        .where(Event.run_config_id == config_id, Event.id > cursor)
                        .order_by(Event.id)
                        .limit(100)
                    )
                ).all()
                config = await session.get(RunConfig, config_id)
            for event in events:
                cursor = event.id
                data = EventRead.model_validate(event).model_dump(mode="json")
                yield f"id: {event.id}\nevent: {event.event_type}\ndata: {json.dumps(data)}\n\n"
            if config is None or (
                config.status
                in {"completed", "completed_with_eval_errors", "failed", "interrupted"}
                and not events
            ):
                yield "event: stream_end\ndata: {}\n\n"
                return
            await asyncio.sleep(1)
            idle_ticks += 1
            if idle_ticks >= 15:
                yield ": heartbeat\n\n"
                idle_ticks = 0

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/runs/{run_id}/stream")
async def stream_individual_run_events(
    run_id: str,
    request: Request,
    last_event_id: Annotated[int | None, Header(alias="Last-Event-ID")] = None,
) -> StreamingResponse:
    database = request.app.state.database
    async with database.session_factory() as session:
        if await session.get(Run, run_id) is None:
            raise HTTPException(status_code=404, detail="Run not found")

    async def stream():
        cursor = last_event_id or 0
        idle_ticks = 0
        terminal_statuses = {
            "completed",
            "completed_with_eval_errors",
            "failed",
            "interrupted",
        }
        while True:
            if await request.is_disconnected():
                return
            async with database.session_factory() as session:
                events = (
                    await session.scalars(
                        select(Event)
                        .where(Event.run_id == run_id, Event.id > cursor)
                        .order_by(Event.id)
                        .limit(100)
                    )
                ).all()
                run = await session.get(Run, run_id)
            for event in events:
                cursor = event.id
                data = EventRead.model_validate(event).model_dump(mode="json")
                yield f"id: {event.id}\nevent: {event.event_type}\ndata: {json.dumps(data)}\n\n"
            if run is None or (run.status in terminal_statuses and not events):
                yield "event: stream_end\ndata: {}\n\n"
                return
            await asyncio.sleep(1)
            idle_ticks += 1
            if idle_ticks >= 15:
                yield ": heartbeat\n\n"
                idle_ticks = 0

    return StreamingResponse(stream(), media_type="text/event-stream")


class PromoteOutputRequest(BaseModel):
    parent_document_id: str | None = None


@router.post("/runs/{run_id}/source", response_model=SourceDocumentRead, status_code=201)
async def promote_run_output(
    run_id: str, payload: PromoteOutputRequest, request: Request, session: SessionDependency
) -> SourceDocumentRead:
    try:
        document = await ExecutionService(session, request.app.state.settings).promote_output(
            run_id, payload.parent_document_id
        )
    except LookupError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except SourceDocumentNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except (RunPreflightError, DatasetNotEditableError) as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return SourceDocumentRead.model_validate(document)
