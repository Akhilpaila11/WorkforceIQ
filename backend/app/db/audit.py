"""Append-only audit trail (A-29).

Services call :meth:`AuditRecorder.record` in the same transaction as the change itself, so
a change and its audit event are committed - or rolled back - together.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Protocol

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.db.base import Base
from app.db.models import AuditEvent
from app.domain.enums import AuditAction

_SKIPPED_COLUMNS = frozenset({"created_at", "updated_at"})


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


def snapshot(entity: Base) -> dict[str, Any]:
    """Current column values of an ORM object as a JSON-compatible dict."""
    mapper = inspect(type(entity))
    return {
        col.key: json_safe(getattr(entity, col.key))
        for col in mapper.column_attrs
        if col.key not in _SKIPPED_COLUMNS
    }


def primary_key_string(entity: Base) -> str:
    identity = inspect(type(entity)).primary_key_from_instance(entity)
    return "|".join(json_safe(v) if not isinstance(v, str) else v for v in identity)


class AuditRecorder(Protocol):
    def record(
        self,
        *,
        entity: Base,
        action: AuditAction,
        before: dict[str, Any] | None,
        actor: str,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> None: ...


class SqlAlchemyAuditRecorder:
    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        *,
        entity: Base,
        action: AuditAction,
        before: dict[str, Any] | None,
        actor: str,
        reason: str | None = None,
        request_id: str | None = None,
    ) -> None:
        after = None if action is AuditAction.DELETE else snapshot(entity)
        self._session.add(
            AuditEvent(
                actor=actor,
                request_id=request_id,
                entity_type=type(entity).__tablename__,
                entity_id=primary_key_string(entity),
                action=action,
                before_state=before,
                after_state=after,
                reason=reason,
            )
        )
        self._session.flush()
