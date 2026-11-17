from typing import Literal

from fastapi import APIRouter, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.database import Database

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok", "not_ready"]
    service: str
    database: Literal["ok", "unavailable"] | None = None


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service="llm-source-manipulation-benchmark")


@router.get("/readiness", response_model=HealthResponse)
async def readiness(request: Request) -> HealthResponse | JSONResponse:
    database: Database = request.app.state.database
    try:
        await database.ping()
    except Exception:
        payload = HealthResponse(
            status="not_ready",
            service="llm-source-manipulation-benchmark",
            database="unavailable",
        )
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload.model_dump()
        )
    return HealthResponse(
        status="ok",
        service="llm-source-manipulation-benchmark",
        database="ok",
    )
