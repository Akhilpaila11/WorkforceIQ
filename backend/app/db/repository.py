"""Repository pattern (Interface Segregation + Dependency Inversion).

Services depend on the small ``Protocol`` interfaces below - never on SQLAlchemy.
:class:`SqlAlchemyRepository` is one implementation; tests can pass in-memory fakes.

Beginner note: a ``Protocol`` is Python's way to describe "anything that has these methods".
A class satisfies it without inheriting from it (structural typing), which keeps business
code independent of the database library.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol, TypeVar

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.orm import InstrumentedAttribute, Session
from sqlalchemy.orm.interfaces import ORMOption

from app.db.base import Base

T = TypeVar("T", bound=Base)
T_co = TypeVar("T_co", covariant=True)
T_contra = TypeVar("T_contra", contravariant=True)

MAX_PAGE_SIZE = 200


@dataclass(frozen=True, slots=True)
class Page[ItemT]:
    items: Sequence[ItemT]
    page: int
    page_size: int
    total: int


class Reader(Protocol[T_co]):
    def get(self, entity_id: Any) -> T_co | None: ...

    def exists(self, entity_id: Any) -> bool: ...


class Lister(Protocol[T_co]):
    def list_page(
        self, *, page: int = 1, page_size: int = 50, filters: Mapping[str, Any] | None = None
    ) -> Page[T_co]: ...


class Writer(Protocol[T_contra]):
    def add(self, entity: T_contra) -> None: ...


class SqlAlchemyRepository[ModelT: Base]:
    """Generic repository for one ORM model. Implements Reader, Lister and Writer."""

    def __init__(self, session: Session, model: type[ModelT]) -> None:
        self._session = session
        self._model = model

    def get(self, entity_id: Any) -> ModelT | None:
        return self._session.get(self._model, entity_id)

    def exists(self, entity_id: Any) -> bool:
        return self.get(entity_id) is not None

    def add(self, entity: ModelT) -> None:
        self._session.add(entity)
        self._session.flush()  # surface constraint errors inside the current transaction

    def list_page(
        self, *, page: int = 1, page_size: int = 50, filters: Mapping[str, Any] | None = None
    ) -> Page[ModelT]:
        conditions = [getattr(self._model, k) == v for k, v in (filters or {}).items()]
        return self._paginate(conditions, page=page, page_size=page_size)

    def _paginate(
        self,
        conditions: Sequence[ColumnElement[bool]],
        *,
        page: int,
        page_size: int,
        options: Sequence[ORMOption] = (),
    ) -> Page[ModelT]:
        """One page of rows matching all ``conditions``, in primary-key order (stable)."""
        if page < 1 or not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"page must be >= 1 and page_size within 1..{MAX_PAGE_SIZE}")
        pk_cols = list(self._model.__table__.primary_key.columns)  # type: ignore[attr-defined]
        query = select(self._model).where(*conditions).order_by(*pk_cols).options(*options)
        total = self._session.scalar(
            select(func.count()).select_from(self._model).where(*conditions)
        )
        rows = self._session.scalars(query.offset((page - 1) * page_size).limit(page_size))
        return Page(items=list(rows), page=page, page_size=page_size, total=int(total or 0))


def equal_to(model: type[Base], values: Mapping[str, Any]) -> list[ColumnElement[bool]]:
    """``column == value`` for every value that is not ``None`` (absent filter)."""
    return [getattr(model, k) == v for k, v in values.items() if v is not None]


def overlapping(
    start: InstrumentedAttribute[date],
    end: InstrumentedAttribute[date] | InstrumentedAttribute[date | None],
    date_from: date | None,
    date_to: date | None,
) -> list[ColumnElement[bool]]:
    """Rows whose ``start..end`` period (open-ended when ``end`` is NULL) overlaps the window."""
    conditions: list[ColumnElement[bool]] = []
    if date_to is not None:
        conditions.append(start <= date_to)
    if date_from is not None:
        conditions.append(or_(end.is_(None), end >= date_from))
    return conditions
