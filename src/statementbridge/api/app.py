"""The application object.

The database connection is opened once at startup and lives on ``app.state``.
SQLite in WAL mode handles one writer and many readers, which is what this is:
a handful of clerks reviewing, and a worker or two reporting.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from ..config import Settings, load
from .deps import open_database
from .routes import health, internal, jobs


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        app.state.connection = open_database(settings)
        settings.uploads_dir.mkdir(parents=True, exist_ok=True)
        settings.scratch_dir.mkdir(parents=True, exist_ok=True)
        try:
            yield
        finally:
            app.state.connection.close()

    app = FastAPI(
        title="StatementBridge",
        version="0.1.0",
        summary="Indian bank statements to Tally-ready output. Offline by default.",
        lifespan=lifespan,
    )
    app.include_router(health.router)
    app.include_router(jobs.router)
    app.include_router(internal.router)
    return app


app = create_app
