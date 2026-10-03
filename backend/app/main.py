"""RMIT 1NE API.

Run:  uvicorn app.main:app --reload --port 8000   (from backend/)
The Pupil Angular app (frontend/) calls the /api routes; / serves the RMIT 1NE study chat.
"""

from __future__ import annotations

import logging

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.cors import CORSMiddleware

from app.api import academic, auth, canvas, ingestion, pupil, query, resources, study
from app.core.config import get_settings
from app.core.security import configure_logging

configure_logging()
log = logging.getLogger("rmit1ne")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="RMIT ONE - WEB", version="2.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,  # bearer tokens, not cookies
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        # never leak internals (SQL, tokens, stack traces) to the client
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Internal server error"})

    static_dir = Path(__file__).parent / "static"

    @app.get("/", include_in_schema=False)
    async def home():
        return FileResponse(static_dir / "index.html")

    @app.get("/health")
    async def health():
        return {"status": "ok", "llm_enabled": settings.llm_enabled, "llm_model": settings.llm_model if settings.llm_enabled else None,
                "storage": "postgres" if settings.use_postgres else "sqlite"}

    for r in (auth.router, academic.router, query.router, canvas.router, ingestion.router, resources.router, study.router,
              pupil.router):
        app.include_router(r)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    return app


app = create_app()
