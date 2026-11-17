from collections.abc import AsyncIterator
from pathlib import Path

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def ensure_sqlite_directory(url: str) -> None:
    prefix = "sqlite+aiosqlite:///"
    if not url.startswith(prefix):
        return
    raw_path = url.removeprefix(prefix)
    if raw_path == ":memory:" or raw_path.startswith("file:"):
        return
    Path(raw_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


class Database:
    def __init__(self, url: str) -> None:
        self.url = url
        ensure_sqlite_directory(url)
        self.engine = self._create_engine()
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    def _create_engine(self) -> AsyncEngine:
        engine = create_async_engine(self.url, pool_pre_ping=True)

        if self.url.startswith("sqlite"):

            @event.listens_for(engine.sync_engine, "connect")
            def configure_sqlite(dbapi_connection: object, _: object) -> None:
                cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA busy_timeout=5000")
                cursor.close()

        return engine

    async def session(self) -> AsyncIterator[AsyncSession]:
        async with self.session_factory() as session:
            yield session

    async def ping(self) -> None:
        async with self.engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            await connection.execute(text("SELECT 1 FROM experiments LIMIT 1"))

    async def dispose(self) -> None:
        await self.engine.dispose()
