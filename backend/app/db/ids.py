"""Database-backed ID allocation for records created through the API.

The generator assigns IDs itself and then calls :meth:`SqlIdAllocator.ensure_at_least`
so API-created records continue the series (docs/05-data-model.md section 5).
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import IdSequence
from app.domain.ids import ID_FORMATS, EntityKind, format_id


class IdAllocator(Protocol):
    def next_id(self, kind: EntityKind, *, year: int | None = None) -> str: ...


class SqlIdAllocator:
    """Increments ``id_sequence.last_value`` inside the caller's transaction.

    On PostgreSQL the row is locked (``SELECT ... FOR UPDATE``); SQLite serialises writers.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def _row(self, prefix: str) -> IdSequence:
        row = self._session.scalar(
            select(IdSequence).where(IdSequence.prefix == prefix).with_for_update()
        )
        if row is None:
            row = IdSequence(prefix=prefix, last_value=0)
            self._session.add(row)
        return row

    def next_id(self, kind: EntityKind, *, year: int | None = None) -> str:
        row = self._row(ID_FORMATS[kind].prefix)
        row.last_value += 1
        self._session.flush()
        return format_id(kind, row.last_value, year=year)

    def ensure_at_least(self, kind: EntityKind, value: int) -> None:
        row = self._row(ID_FORMATS[kind].prefix)
        row.last_value = max(row.last_value, value)
        self._session.flush()
