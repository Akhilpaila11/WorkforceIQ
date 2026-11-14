"""Central HTTP error handling: every error leaves the API in one shape.

``{"error": {"code": ..., "message": ..., "details": ..., "request_id": ...}}``

Domain exceptions (``app.domain.errors``) know nothing about HTTP; the mapping to status codes
lives only here (docs/04-architecture.md section 7).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.domain.errors import (
    BusinessRuleViolation,
    ConflictError,
    DomainError,
    DomainValidationError,
    ImmutableFieldError,
    InvalidStateTransition,
    NotFoundError,
)

logger = logging.getLogger("app.errors")

DOMAIN_STATUS: dict[type[DomainError], int] = {
    NotFoundError: status.HTTP_404_NOT_FOUND,
    ConflictError: status.HTTP_409_CONFLICT,
    BusinessRuleViolation: status.HTTP_409_CONFLICT,
    InvalidStateTransition: status.HTTP_409_CONFLICT,
    ImmutableFieldError: status.HTTP_409_CONFLICT,
    DomainValidationError: status.HTTP_422_UNPROCESSABLE_CONTENT,
}

HTTP_CODES: dict[int, str] = {
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
}


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Any = None
    request_id: str | None = None


class ErrorResponse(BaseModel):
    """Documented in OpenAPI for every route (see ``ERROR_RESPONSES``)."""

    error: ErrorBody


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "Record not found"},
    422: {"model": ErrorResponse, "description": "Invalid path or query parameters"},
}


def error_response(
    request: Request, status_code: int, code: str, message: str, details: Any = None
) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    body = ErrorResponse(
        error=ErrorBody(code=code, message=message, details=details, request_id=request_id)
    )
    headers = {"X-Request-ID": request_id} if request_id else None
    return JSONResponse(body.model_dump(mode="json"), status_code=status_code, headers=headers)


async def _domain_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    code = next((s for t, s in DOMAIN_STATUS.items() if isinstance(exc, t)), 400)
    return error_response(request, code, exc.code, exc.message, exc.details)


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    details = [
        {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
        for e in exc.errors()
    ]
    return error_response(
        request,
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "VALIDATION_ERROR",
        "Request parameters are invalid",
        details,
    )


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
    return error_response(request, exc.status_code, code, str(exc.detail))


async def _database_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error("database unavailable: %s", exc.__class__.__name__, exc_info=exc)
    return error_response(
        request,
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "DATABASE_UNAVAILABLE",
        "The database is unavailable or not migrated (run: alembic upgrade head)",
    )


async def _unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    logger.error("unhandled error", exc_info=exc)
    return error_response(
        request,
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        "INTERNAL_ERROR",
        "An unexpected error occurred",
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _domain_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(OperationalError, _database_error)
    app.add_exception_handler(Exception, _unexpected_error)
