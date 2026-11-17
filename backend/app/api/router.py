from fastapi import APIRouter

from app.api.routes import (
    analysis,
    documents,
    execution,
    experiments,
    health,
    interactive,
    sample_packs,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router)
api_router.include_router(analysis.router)
api_router.include_router(interactive.router)
api_router.include_router(experiments.router)
api_router.include_router(documents.router)
api_router.include_router(execution.router)
api_router.include_router(sample_packs.router)
