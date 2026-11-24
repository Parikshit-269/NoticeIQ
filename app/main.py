"""FastAPI application factory."""
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config import STATIC_DIR, Settings
from app.db import Database
from app.routes import api


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.ensure_dirs()
    app = FastAPI(title="NoticeIQ", version="1.0.0")
    app.state.settings = settings
    app.state.db = Database(settings.db_path)
    app.include_router(api.router, prefix="/api")
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    return app


app = create_app()
