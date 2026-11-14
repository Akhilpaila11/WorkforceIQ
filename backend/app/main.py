"""FastAPI application factory.

Run the development server (PowerShell, from ``backend/``)::

    .\\.venv\\Scripts\\python.exe -m uvicorn app.main:create_app --factory --reload --port 8000

Swagger UI: http://localhost:8000/docs - OpenAPI: http://localhost:8000/openapi.json
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Engine

from app import __version__
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.database import create_db_engine, make_session_factory
from app.core.errors import install_error_handlers
from app.core.logging import configure_logging, request_id_var
from app.domain.rules_config import load_rules

access_log = logging.getLogger("app.access")


def create_app(settings: Settings | None = None, *, engine: Engine | None = None) -> FastAPI:
    """Build the app. Tests pass their own ``engine`` (an isolated, disposable database)."""
    settings = settings or get_settings()
    configure_logging(settings)
    db_engine = engine or create_db_engine(settings.database_url(), echo=settings.db_echo)
    owns_engine = engine is None

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        if owns_engine:
            db_engine.dispose()

    app = FastAPI(
        title="WorkforceIQ API",
        version=__version__,
        description=(
            "Workforce demand, capacity, skill gaps, anomaly detection and recommendations."
        ),
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.engine = db_engine
    app.state.session_factory = make_session_factory(db_engine)
    app.state.rules = load_rules(settings.rules_path)

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.state.request_id = request_id
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            access_log.info(
                "%s %s -> %s",
                request.method,
                request.url.path,
                response.status_code,
                extra={"duration_ms": round((time.perf_counter() - started) * 1000, 1)},
            )
            return response
        finally:
            request_id_var.reset(token)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    install_error_handlers(app)
    app.include_router(api_router, prefix=settings.api_prefix)
    return app
