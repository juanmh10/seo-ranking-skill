import asyncio
import json
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.schemas.analysis import (
    AnalysisMessageCreate,
    AnalysisSessionCreate,
    AnalysisSessionRead,
)
from app.services.analysis import (
    AnalysisInputError,
    AnalysisModelUnavailableError,
    AnalysisNotFoundError,
    AnalysisService,
)

router = APIRouter(tags=["analysis"])
SessionDependency = Annotated[AsyncSession, Depends(get_session)]


def _sse(event: str, data: dict[str, object]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post(
    "/experiments/{experiment_id}/analysis/sessions",
    response_model=AnalysisSessionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_analysis_session(
    experiment_id: str,
    payload: AnalysisSessionCreate,
    request: Request,
    session: SessionDependency,
) -> AnalysisSessionRead:
    service = AnalysisService(session, request.app.state.settings)
    try:
        result = await service.create_session(experiment_id, payload)
    except AnalysisNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except AnalysisModelUnavailableError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except AnalysisInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return AnalysisSessionRead.model_validate(result)


@router.get(
    "/analysis/sessions/{session_id}",
    response_model=AnalysisSessionRead,
)
async def get_analysis_session(
    session_id: str,
    request: Request,
    session: SessionDependency,
) -> AnalysisSessionRead:
    try:
        result = await AnalysisService(session, request.app.state.settings).get_session(session_id)
    except AnalysisNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return AnalysisSessionRead.model_validate(result)


@router.get(
    "/experiments/{experiment_id}/analysis/sessions",
    response_model=list[AnalysisSessionRead],
)
async def list_analysis_sessions(
    experiment_id: str,
    request: Request,
    session: SessionDependency,
) -> list[AnalysisSessionRead]:
    try:
        result = await AnalysisService(session, request.app.state.settings).list_sessions(
            experiment_id
        )
    except AnalysisNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return [AnalysisSessionRead.model_validate(item) for item in result]


@router.post(
    "/analysis/sessions/{session_id}/messages",
    response_model=AnalysisSessionRead,
)
async def create_analysis_message(
    session_id: str,
    payload: AnalysisMessageCreate,
    request: Request,
    session: SessionDependency,
) -> AnalysisSessionRead:
    settings = request.app.state.settings
    service = AnalysisService(session, settings)
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="Analysis message cannot be empty")
    try:
        await service.add_message(session_id, "user", content)
        analysis_session = await service.get_session(session_id)
        analysis_session.status = "running"
        await session.commit()
        model_request = await service.build_model_request(session_id)
        await session.commit()
    except AnalysisNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except AnalysisInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except AnalysisModelUnavailableError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

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
                "A análise excedeu o limite de tempo configurado. Tente novamente."
                if is_timeout
                else "O modelo de análise não concluiu a resposta. Tente novamente."
            ),
            metadata={"status": "failed", "error_type": type(error).__name__},
        )
    else:
        await service.persist_model_response(
            session_id,
            content=response.text,
            metadata={
                "status": "completed",
                "model_id_actual": response.model_id_actual,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "total_tokens": response.total_tokens,
                "request_id": response.request_id,
                "trace_id": response.trace_id,
            },
        )
    return AnalysisSessionRead.model_validate(await service.get_session(session_id))


@router.post("/analysis/sessions/{session_id}/messages/stream")
async def stream_analysis_message(
    session_id: str,
    payload: AnalysisMessageCreate,
    request: Request,
    session: SessionDependency,
) -> StreamingResponse:
    settings = request.app.state.settings
    service = AnalysisService(session, settings)
    content = payload.content.strip()
    if not content:
        raise HTTPException(status_code=422, detail="Analysis message cannot be empty")
    try:
        analysis_session = await service.get_session(session_id)
        if analysis_session.status == "running":
            raise HTTPException(status_code=409, detail="Wait for the current analysis response")
        await service.add_message(session_id, "user", content)
        analysis_session = await service.get_session(session_id)
        analysis_session.status = "running"
        await session.commit()
        model_request = await service.build_model_request(session_id)
        await session.commit()
    except AnalysisNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except AnalysisInputError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except AnalysisModelUnavailableError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error

    runner = request.app.state.execution_engine.runner

    async def events():
        deltas: list[str] = []
        response = None
        try:
            async with asyncio.timeout(settings.model_timeout_seconds):
                async for item in runner.stream(model_request):
                    if item.text_delta:
                        deltas.append(item.text_delta)
                        yield _sse("delta", {"text": item.text_delta})
                    if item.response is not None:
                        response = item.response
            if response is None:
                raise RuntimeError("Analysis stream ended without a final response")
            if not deltas and response.text:
                yield _sse("delta", {"text": response.text})
            await service.persist_model_response(
                session_id,
                content=response.text,
                metadata={
                    "status": "completed",
                    "model_id_actual": response.model_id_actual,
                    "input_tokens": response.input_tokens,
                    "output_tokens": response.output_tokens,
                    "total_tokens": response.total_tokens,
                    "request_id": response.request_id,
                    "trace_id": response.trace_id,
                },
            )
            latest = await service.get_session(session_id)
            result = AnalysisSessionRead.model_validate(latest).model_dump(mode="json")
            yield _sse("done", {"session": result})
        except asyncio.CancelledError:
            await service.persist_model_response(
                session_id,
                content="".join(deltas)
                or "A análise foi interrompida antes de chegar ao navegador.",
                metadata={"status": "interrupted", "partial": bool(deltas)},
            )
            raise
        except Exception as error:
            failure_text = (
                "A análise excedeu o limite de tempo configurado. Tente novamente."
                if isinstance(error, TimeoutError)
                else "O modelo de análise não concluiu a resposta. Tente novamente."
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
