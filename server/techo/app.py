from __future__ import annotations

import re
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import text

from . import clock
from .api import auth, calendar, pages, photos, resources
from .api.dependencies import Authenticated
from .auth import AuthService
from .config import Settings
from .database import Database
from .errors import install_handlers
from .services.calendar import CalendarService
from .services.journal import JournalService
from .services.pages import PageService
from .services.photos import PhotoService
from .services.seed import seed
from .static import OptionalStaticFiles


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    clock.configure(ZoneInfo(settings.timezone))
    database = Database(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            database.migrate()
            seed(database, settings.project_root / "seed.json")
            yield
        finally:
            database.close()

    app = FastAPI(
        title="techo", version="1.2.0", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )
    app.state.settings = settings
    app.state.database = database
    app.state.auth = AuthService(database, settings)
    app.state.journal = JournalService(database)
    app.state.calendar = CalendarService(database)
    app.state.photos = PhotoService(database, settings.photos_path)
    app.state.pages = PageService(database)
    install_handlers(app)
    photo_file = re.compile(re.escape(settings.api_prefix) + r"/photos/[0-9]+")

    @app.middleware("http")
    async def privacy_headers(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith(settings.api_prefix + "/"):
            # Successful photo reads are immutable content-addressed files; everything else is private data.
            if not (
                request.method in {"GET", "HEAD"}
                and response.status_code == 200
                and photo_file.fullmatch(path)
            ):
                response.headers["Cache-Control"] = "no-store"
            response.headers["Vary"] = "Cookie, X-Techo-Token"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        return response

    api = APIRouter(prefix=settings.api_prefix)
    api.include_router(auth.router)
    api.include_router(resources.router)
    api.include_router(calendar.router)
    api.include_router(photos.router)
    api.include_router(pages.router)

    @api.get("/healthz", tags=["operations"])
    def health():
        with database.transaction() as session:
            session.execute(text("SELECT 1"))
        return {"ok": True}

    @api.get("/openapi.json", include_in_schema=False)
    def openapi(actor: Authenticated):
        return app.openapi()

    app.include_router(api)

    @app.get(settings.base_path, include_in_schema=False)
    def trailing_slash():
        return RedirectResponse(settings.base_path + "/", status_code=308)

    app.mount(
        settings.base_path + "/",
        OptionalStaticFiles(directory=str(settings.project_root / "frontend"), html=True, check_dir=False),
        name="frontend",
    )
    return app
