import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.domain.model_runner import ModelResponse
from app.schemas.interactive import (
    InteractiveMessageCreate,
    InteractiveSessionCreate,
    InteractiveSessionRead,
)
from app.services.interactive import (
    InteractiveInputError,
    InteractiveModelUnavailableError,
    InteractiveNotFoundError,
    InteractiveService,
    InteractiveSessionBusyError,
)

router = APIRouter(tags=["interactive"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]


def _raise_interactive_error(error: Exception) -> None:
    if isinstance(error, InteractiveNotFoundError):
        raise HTTPException(status_code=404, detail=str(error)) from error
    if isinstance(error, InteractiveSessionBusyError):
        raise HTTPException(status_code=409, detail=str(error)) from error
    if isinstance(error, (InteractiveInputError, InteractiveModelUnavailableError)):
        raise HTTPException(status_code=422, detail=str(error)) from error
    raise error


def _response_metadata(response: ModelResponse) -> dict[str, object]:
    return {
        "status": "completed",
        "model_id_actual": response.model_id_actual,
        "input_tokens": response.input_tokens,
        "output_tokens": response.output_tokens,
        "total_tokens": response.total_tokens,
        "request_id": response.request_id,
        "trace_id": response.trace_id,
    }


def _sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post(
    "/experiments/{experiment_id}/interactive/sessions",
    response_model=InteractiveSessionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_interactive_session(
    experiment_id: str,
    payload: InteractiveSessionCreate,
    request: Request,
    session: SessionDependency,
) -> InteractiveSessionRead:
    try:
        result = await InteractiveService(session, request.app.state.settings).create_session(
            experiment_id, payload
        )
    except (
        InteractiveNotFoundError,
        InteractiveInputError,
        InteractiveModelUnavailableError,
    ) as error:
        _raise_interactive_error(error)
    return InteractiveSessionRead.model_validate(result)


@router.get(
    "/experiments/{experiment_id}/interactive/sessions",
    response_model=list[InteractiveSessionRead],
)
async def list_interactive_sessions(
    experiment_id: str,
    request: Request,
    session: SessionDependency,
) -> list[InteractiveSessionRead]:
    try:
        results = await InteractiveService(session, request.app.state.settings).list_sessions(
            experiment_id
        )
    except InteractiveNotFoundError as error:
        _raise_interactive_error(error)
    return [InteractiveSessionRead.model_validate(result) for result in results]


@router.get("/interactive/sessions/{session_id}", response_model=InteractiveSessionRead)
async def get_interactive_session(
    session_id: str,
    request: Request,
    session: SessionDependency,
) -> InteractiveSessionRead:
    try:
        result = await InteractiveService(session, request.app.state.settings).get_session(
            session_id
        )
    except InteractiveNotFoundError as error:
        _raise_interactive_error(error)
    return InteractiveSessionRead.model_validate(result)


@router.post(
    "/interactive/sessions/{session_id}/reset",
    response_model=InteractiveSessionRead,
    status_code=status.HTTP_201_CREATED,
)
async def reset_interactive_session(
    session_id: str,
    request: Request,
    session: SessionDependency,
) -> InteractiveSessionRead:
    try:
        result = await InteractiveService(session, request.app.state.settings).create_reset_session(
            session_id
        )
    except (InteractiveNotFoundError, InteractiveSessionBusyError) as error:
        _raise_interactive_error(error)
    return InteractiveSessionRead.model_validate(result)


@router.post(
    "/interactive/sessions/{session_id}/messages",
    response_model=InteractiveSessionRead,
)
async def create_interactive_message(
    session_id: str,
    payload: InteractiveMessageCreate,
    request: Request,
    session: SessionDependency,
) -> InteractiveSessionRead:
    service = InteractiveService(session, request.app.state.settings)
    try:
        model_request = await service.begin_message(session_id, payload.content)
    except (
        InteractiveNotFoundError,
        InteractiveInputError,
        InteractiveModelUnavailableError,
        InteractiveSessionBusyError,
    ) as error:
        _raise_interactive_error(error)

    settings = request.app.state.settings
    runner = request.app.state.execution_engine.runner
    try:
        async with asyncio.timeout(settings.model_timeout_seconds):
            response = await runner.run(model_request)
    except asyncio.CancelledError:
        raise
    except Exception as error:
        is_timeout = isinstance(error, TimeoutError)
        await service.persist_model_response(
            session_id,
            content=(
                "A resposta excedeu o limite de tempo configurado. Tente novamente."
                if is_timeout
                else "O modelo não concluiu a resposta. Tente novamente."
            ),
            metadata={"status": "failed", "error_type": type(error).__name__},
        )
    else:
        await service.persist_model_response(
            session_id, content=response.text, metadata=_response_metadata(response)
        )
    return InteractiveSessionRead.model_validate(await service.get_session(session_id))


@router.post("/interactive/sessions/{session_id}/messages/stream")
async def stream_interactive_message(
    session_id: str,
    payload: InteractiveMessageCreate,
    request: Request,
    session: SessionDependency,
) -> StreamingResponse:
    service = InteractiveService(session, request.app.state.settings)
    try:
        model_request = await service.begin_message(session_id, payload.content)
    except (
        InteractiveNotFoundError,
        InteractiveInputError,
        InteractiveModelUnavailableError,
        InteractiveSessionBusyError,
    ) as error:
        _raise_interactive_error(error)

    settings = request.app.state.settings
    runner = request.app.state.execution_engine.runner

    async def events():
        deltas: list[str] = []
        response: ModelResponse | None = None
        try:
            async with asyncio.timeout(settings.model_timeout_seconds):
                async for item in runner.stream(model_request):
                    if item.text_delta:
                        deltas.append(item.text_delta)
                        yield _sse("delta", {"text": item.text_delta})
                    if item.response is not None:
                        response = item.response
            if response is None:
                raise RuntimeError("Model stream ended without a final response")
            if not deltas and response.text:
                yield _sse("delta", {"text": response.text})
            await service.persist_model_response(
                session_id, content=response.text, metadata=_response_metadata(response)
            )
            latest = await service.get_session(session_id)
            completed = InteractiveSessionRead.model_validate(latest).model_dump(mode="json")
            yield _sse("done", {"session": completed})
        except asyncio.CancelledError:
            partial = "".join(deltas)
            await service.persist_model_response(
                session_id,
                content=partial or "A resposta foi interrompida antes de chegar ao navegador.",
                metadata={"status": "interrupted", "partial": bool(partial)},
            )
            raise
        except Exception as error:
            is_timeout = isinstance(error, TimeoutError)
            failure_text = (
                "A resposta excedeu o limite de tempo configurado. Tente novamente."
                if is_timeout
                else "O modelo não concluiu a resposta. Tente novamente."
            )
            await service.persist_model_response(
                session_id,
                content=failure_text,
                metadata={"status": "failed", "error_type": type(error).__name__},
            )
            yield _sse("error", {"detail": failure_text})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
