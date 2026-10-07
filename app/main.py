import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.auth import router as auth_router
from app.api.files import router as files_router
from app.config import Settings, get_settings
from app.database import create_db_engine, create_session_factory, init_db
from app.errors import AppError
from app.services.tasks import create_dispatcher


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    engine = create_db_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        settings.storage_dir.mkdir(parents=True, exist_ok=True)
        init_db(engine)
        yield
        engine.dispose()

    app = FastAPI(
        title="Geospatial File Measurement API",
        version="1.1.0",
        description=(
            "Upload a Shapefile (.zip), KML or KMZ file and get the area of every polygon and "
            "the length of every line, measured in an appropriate projected CRS.\n\n"
            "Authenticate with an `X-API-Key` header: create a key with "
            "`POST /api/auth/keys/`, then click **Authorize**."
        ),
        lifespan=lifespan,
    )
    session_factory = create_session_factory(engine)
    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.dispatcher = create_dispatcher(settings, session_factory)

    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth_router)
    app.include_router(files_router)
    _mount_viewer(app, settings)
    return app


def _mount_viewer(app: FastAPI, settings: Settings) -> None:
    """Serve the built map viewer (frontend/dist) at "/", if it has been built.

    Only "/" and "/assets" are claimed, so unknown paths still 404 and "/api/files" still
    redirects to "/api/files/".
    """
    index = settings.frontend_dir / "index.html"
    if not index.is_file():
        return
    app.mount("/assets", StaticFiles(directory=settings.frontend_dir / "assets"), name="assets")

    @app.get("/", include_in_schema=False)
    def viewer() -> FileResponse:
        return FileResponse(index)


app = create_app()
