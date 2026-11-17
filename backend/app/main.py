from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.database import Database
from app.domain.model_runner import ModelRunner
from app.models import Base
from app.providers.configured_runner import ConfiguredModelRunner
from app.services.catalog import sync_catalog
from app.services.execution import ExecutionEngine


def create_app(
    settings: Settings | None = None, *, model_runner: ModelRunner | None = None
) -> FastAPI:
    app_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        database = Database(app_settings.database_url)
        application.state.database = database
        application.state.settings = app_settings
        if app_settings.auto_create_schema:
            async with database.engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
        async with database.session_factory() as session:
            await sync_catalog(session, app_settings)
        execution_engine = ExecutionEngine(
            database,
            app_settings,
            model_runner
            or ConfiguredModelRunner(
                app_settings.xai_api_key.get_secret_value()
                if app_settings.xai_api_key is not None
                else None
            ),
        )
        await execution_engine.interrupt_stale()
        application.state.execution_engine = execution_engine
        yield
        await execution_engine.shutdown()
        await database.dispose()

    application = FastAPI(
        title=app_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Idempotency-Key", "Last-Event-ID"],
    )
    application.include_router(api_router)
    return application


app = create_app()
