"""Version 1 router: health check plus every module router."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app import __version__
from app.modules.analytics.router import router as analytics_router
from app.modules.projects.router import router as projects_router
from app.modules.reporting.router import router as reporting_router
from app.modules.workforce.router import router as workforce_router


class DatabaseHealth(BaseModel):
    ok: bool
    dialect: str
    schema_revision: str | None


class HealthOut(BaseModel):
    status: Literal["ok", "unavailable"]
    version: str
    environment: str
    database: DatabaseHealth


def _database_health(engine: Engine) -> DatabaseHealth:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            revision = (
                conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
                if inspect(conn).has_table("alembic_version")
                else None
            )
        return DatabaseHealth(ok=True, dialect=engine.dialect.name, schema_revision=revision)
    except SQLAlchemyError:
        return DatabaseHealth(ok=False, dialect=engine.dialect.name, schema_revision=None)


health_router = APIRouter(tags=["health"])


@health_router.get(
    "/health", responses={503: {"model": HealthOut, "description": "Database unavailable"}}
)
def health(request: Request, response: Response) -> HealthOut:
    """Liveness and database connectivity (``503`` when the database cannot be reached)."""
    database = _database_health(request.app.state.engine)
    if not database.ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthOut(
        status="ok" if database.ok else "unavailable",
        version=__version__,
        environment=request.app.state.settings.env,
        database=database,
    )


api_router = APIRouter()
for module_router in (
    health_router,
    workforce_router,
    projects_router,
    reporting_router,
    analytics_router,
):
    api_router.include_router(module_router)
